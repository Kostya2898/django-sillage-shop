from django.contrib import admin

from .models import Order, OrderItem, OrderStatusHistory, ShippingAddress
from .services import cancel_order


@admin.register(ShippingAddress)
class ShippingAddressAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'user', 'city', 'phone', 'is_default']
    list_filter = ['is_default', 'country', 'city']
    search_fields = ['full_name', 'phone', 'city', 'user__username']


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['product', 'product_name', 'price', 'quantity']
    can_delete = False


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    readonly_fields = ['status', 'note', 'created_by', 'created_at']
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        'order_number',
        'user',
        'total_amount',
        'items_total',
        'payment_method',
        'status',
        'created_at',
    ]
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = [
        'order_number',
        'user__username',
        'user__email',
        'shipping_full_name',
        'shipping_phone',
    ]
    readonly_fields = ['order_number', 'created_at', 'updated_at']
    inlines = [OrderItemInline, OrderStatusHistoryInline]
    actions = ['mark_shipped', 'mark_delivered', 'mark_cancelled']
    date_hierarchy = 'created_at'

    def get_queryset(self, request):
        """Користувач і кошик — одним запитом, а позиції — префетчем.

        Без цього список замовлень робив би по запиту на кожен рядок:
        один на користувача і ще один на підрахунок позицій.
        """
        return (
            super().get_queryset(request).select_related('user', 'cart').prefetch_related('items')
        )

    @admin.display(description='Позицій')
    def items_total(self, obj):
        # items уже в префетчі, тож len() не ходить у базу.
        return len(obj.items.all())

    def _change_status(self, request, queryset, status, label):
        changed = 0
        for order in queryset:
            if order.status == status:
                continue
            order.status = status
            order.save(update_fields=['status', 'updated_at'])
            OrderStatusHistory.objects.create(
                order=order,
                status=status,
                note=f'Статус змінено через адмінку на «{label}»',
                created_by=request.user,
            )
            changed += 1
        # Рахуємо саме змінені, а не весь queryset: замовлення, які вже мали
        # цей статус, ми пропустили вище.
        self.message_user(request, f'Оновлено замовлень: {changed}')

    def _cancel(self, request, queryset):
        """Скасування — не просто зміна статусу: воно повертає товар на склад."""
        cancelled = sum(
            1
            for order in queryset
            if cancel_order(
                order,
                actor=request.user,
                note='Скасовано через адмінку, товари повернуто на склад',
            )
        )
        self.message_user(request, f'Скасовано замовлень: {cancelled}')

    def save_model(self, request, obj, form, change):
        """Статус, змінений у формі на «Скасовано», теж має повернути склад."""
        becoming_cancelled = (
            change and obj.status == Order.STATUS_CANCELLED and 'status' in form.changed_data
        )

        if not becoming_cancelled:
            super().save_model(request, obj, form, change)
            return

        # Зберігаємо решту полів зі старим статусом, а сам перехід віддаємо
        # сервісу — щоб склад повернувся в тій самій транзакції.
        obj.status = form.initial.get('status', Order.STATUS_PENDING)
        super().save_model(request, obj, form, change)
        cancel_order(obj, actor=request.user, note='Скасовано через форму адмінки')

    @admin.action(description='Позначити як відправлені')
    def mark_shipped(self, request, queryset):
        self._change_status(request, queryset, Order.STATUS_SHIPPED, 'Відправлено')

    @admin.action(description='Позначити як доставлені')
    def mark_delivered(self, request, queryset):
        self._change_status(request, queryset, Order.STATUS_DELIVERED, 'Доставлено')

    @admin.action(description='Скасувати замовлення і повернути товар на склад')
    def mark_cancelled(self, request, queryset):
        self._cancel(request, queryset)

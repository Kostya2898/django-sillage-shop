from django.contrib import admin

from .models import Order, OrderItem, OrderStatusHistory, ShippingAddress


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
        'order_number', 'user', 'total_amount', 'payment_method', 'status', 'created_at',
    ]
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = ['order_number', 'user__username', 'shipping_full_name', 'shipping_phone']
    readonly_fields = ['order_number', 'created_at', 'updated_at']
    inlines = [OrderItemInline, OrderStatusHistoryInline]
    actions = ['mark_shipped', 'mark_delivered', 'mark_cancelled']

    def _change_status(self, request, queryset, status, label):
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
        self.message_user(request, f'Оновлено замовлень: {queryset.count()}')

    @admin.action(description='Позначити як відправлені')
    def mark_shipped(self, request, queryset):
        self._change_status(request, queryset, Order.STATUS_SHIPPED, 'Відправлено')

    @admin.action(description='Позначити як доставлені')
    def mark_delivered(self, request, queryset):
        self._change_status(request, queryset, Order.STATUS_DELIVERED, 'Доставлено')

    @admin.action(description='Скасувати замовлення')
    def mark_cancelled(self, request, queryset):
        self._change_status(request, queryset, Order.STATUS_CANCELLED, 'Скасовано')

from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    Coupon,
    DeliveryMethod,
    Order,
    OrderItem,
    OrderStatusHistory,
    ShippingAddress,
)
from .services import cancel_order


@admin.register(ShippingAddress)
class ShippingAddressAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'user', 'city', 'phone', 'is_default']
    list_filter = ['is_default', 'country', 'city']
    search_fields = ['full_name', 'phone', 'city', 'user__username']


@admin.register(DeliveryMethod)
class DeliveryMethodAdmin(admin.ModelAdmin):
    list_display = ['name', 'price', 'free_from', 'estimated_days', 'is_active', 'sort_order']
    list_editable = ['price', 'free_from', 'is_active', 'sort_order']
    list_filter = ['is_active']
    search_fields = ['name']


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = [
        'code',
        'discount_summary',
        'validity',
        'usage',
        'min_order_amount',
        'is_active',
    ]
    list_filter = ['is_active', 'discount_type', 'valid_to']
    search_fields = ['code', 'description']
    readonly_fields = ['used_count', 'created_at']
    date_hierarchy = 'valid_to'

    @admin.display(description='Знижка')
    def discount_summary(self, obj):
        return obj.get_discount_display()

    @admin.display(description='Дійсний')
    def validity(self, obj):
        window = f'{obj.valid_from:%d.%m.%Y} — {obj.valid_to:%d.%m.%Y}'
        if obj.valid_to < timezone.now():
            return format_html('<span style="color:#b8615a;">{} (минув)</span>', window)
        return window

    @admin.display(description='Використань')
    def usage(self, obj):
        if not obj.max_uses:
            return f'{obj.used_count} (без ліміту)'
        return f'{obj.used_count} / {obj.max_uses}'


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


class CustomerTypeFilter(admin.SimpleListFilter):
    """Гостьові замовлення проти замовлень з акаунтом.

    Окремий фільтр, бо це перше, про що питають після запуску гостьового
    checkout: скільки покупок іде повз реєстрацію.
    """

    title = 'Тип покупця'
    parameter_name = 'customer'

    def lookups(self, request, model_admin):
        return [('guest', 'Гість'), ('registered', 'З акаунтом')]

    def queryset(self, request, queryset):
        if self.value() == 'guest':
            return queryset.filter(user__isnull=True)
        if self.value() == 'registered':
            return queryset.filter(user__isnull=False)
        return queryset


class OrderPeriodFilter(admin.SimpleListFilter):
    """Фільтр за періодом: сьогодні, тиждень, місяць.

    `date_hierarchy` уміє тільки точні дати, а «що продалося за тиждень» —
    найчастіше питання до цього списку.
    """

    title = 'Період'
    parameter_name = 'period'

    def lookups(self, request, model_admin):
        return [
            ('today', 'Сьогодні'),
            ('7days', 'Останні 7 днів'),
            ('30days', 'Останні 30 днів'),
            ('year', 'Цього року'),
        ]

    def queryset(self, request, queryset):
        now = timezone.now()
        windows = {
            'today': timezone.timedelta(days=1),
            '7days': timezone.timedelta(days=7),
            '30days': timezone.timedelta(days=30),
        }

        value = self.value()
        if value in windows:
            return queryset.filter(created_at__gte=now - windows[value])
        if value == 'year':
            return queryset.filter(created_at__year=now.year)
        return queryset


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        'order_number',
        'customer',
        'total_amount',
        'discount_summary',
        'items_total_count',
        'delivery_summary',
        'payment_method',
        'status',
        'created_at',
        'invoice_link',
    ]
    list_filter = [
        'status',
        'payment_method',
        OrderPeriodFilter,
        CustomerTypeFilter,
        'delivery_method',
        'created_at',
    ]
    search_fields = [
        'order_number',
        'user__username',
        'user__email',
        'guest_email',
        'coupon_code',
        'shipping_full_name',
        'shipping_phone',
    ]
    readonly_fields = ['order_number', 'created_at', 'updated_at', 'invoice_link']
    inlines = [OrderItemInline, OrderStatusHistoryInline]
    actions = ['mark_paid', 'mark_shipped', 'mark_delivered', 'mark_cancelled']
    date_hierarchy = 'created_at'

    def get_queryset(self, request):
        """Користувач, кошик, купон і доставка — одним запитом, позиції — префетчем.

        Без цього список замовлень робив би по запиту на кожен рядок:
        один на користувача і ще один на підрахунок позицій.
        """
        return (
            super()
            .get_queryset(request)
            .select_related('user', 'cart', 'coupon', 'delivery_method')
            .prefetch_related('items')
        )

    @admin.display(description='Покупець', ordering='user__username')
    def customer(self, obj):
        if obj.user_id:
            return obj.user.username
        return format_html('<span title="Гостьове замовлення">гість · {}</span>', obj.guest_email)

    @admin.display(description='Позицій')
    def items_total_count(self, obj):
        # items уже в префетчі, тож len() не ходить у базу.
        return len(obj.items.all())

    @admin.display(description='Знижка')
    def discount_summary(self, obj):
        if not obj.discount_amount:
            return '—'
        return format_html(
            '<span style="color:#b8615a;">−{}</span> {}',
            obj.discount_amount,
            obj.coupon_code or '',
        )

    @admin.display(description='Доставка')
    def delivery_summary(self, obj):
        if not obj.delivery_name:
            return '—'
        price = 'безкоштовно' if not obj.delivery_price else f'{obj.delivery_price}'
        return f'{obj.delivery_name} · {price}'

    @admin.display(description='Рахунок')
    def invoice_link(self, obj):
        if not obj.pk:
            return '—'
        url = reverse('orders:order_invoice', args=[obj.order_number])
        return format_html('<a href="{}" target="_blank" rel="noopener">PDF</a>', url)

    def _change_status(self, request, queryset, status, label):
        """Масова зміна статусу.

        Історію й лист покупцю пише сигнал `record_status_change`; тут ми лише
        повідомляємо йому причину та автора. Тому й цикл, а не `update()`:
        `queryset.update()` не викликає сигналів, і зміна пройшла б непомітно
        для історії та для покупця.
        """
        changed = 0
        for order in queryset:
            if order.status == status:
                continue
            order.status = status
            order._status_note = f'Статус змінено через адмінку на «{label}»'
            order._status_actor = request.user
            order.save(update_fields=['status', 'updated_at'])
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

    @admin.action(description='Позначити як оплачені')
    def mark_paid(self, request, queryset):
        self._change_status(request, queryset, Order.STATUS_PAID, 'Оплачено')

    @admin.action(description='Позначити як відправлені')
    def mark_shipped(self, request, queryset):
        self._change_status(request, queryset, Order.STATUS_SHIPPED, 'Відправлено')

    @admin.action(description='Позначити як доставлені')
    def mark_delivered(self, request, queryset):
        self._change_status(request, queryset, Order.STATUS_DELIVERED, 'Доставлено')

    @admin.action(description='Скасувати замовлення і повернути товар на склад')
    def mark_cancelled(self, request, queryset):
        self._cancel(request, queryset)

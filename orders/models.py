"""Моделі замовлень: адреси доставки, замовлення, позиції та історія статусів."""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from cart.services import format_price
from shop.models import Product

# Скільки часу після оформлення покупець може скасувати замовлення сам.
# У налаштуваннях цьому місце не потрібне: 24 години — це умова публічної
# оферти магазину, а не параметр середовища.
CANCELLATION_WINDOW = timedelta(hours=24)


class ShippingAddress(models.Model):
    """Адреса доставки, збережена в адресній книзі користувача."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='addresses',
        verbose_name='Користувач',
    )
    full_name = models.CharField('ПІБ', max_length=200)
    phone = models.CharField('Телефон', max_length=20)

    country = models.CharField('Країна', max_length=100, default='Україна')
    city = models.CharField('Місто', max_length=100)
    postal_code = models.CharField('Поштовий індекс', max_length=20)
    address_line1 = models.CharField('Адреса (рядок 1)', max_length=250)
    address_line2 = models.CharField('Адреса (рядок 2)', max_length=250, blank=True)

    is_default = models.BooleanField('За замовчуванням', default=False)
    created_at = models.DateTimeField('Створено', auto_now_add=True)

    class Meta:
        verbose_name = 'Адреса доставки'
        verbose_name_plural = 'Адреси доставки'
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f'{self.full_name} — {self.city}, {self.address_line1}'

    def save(self, *args, **kwargs):
        """Адреса за замовчуванням може бути тільки одна на користувача."""
        if self.is_default:
            ShippingAddress.objects.filter(user=self.user, is_default=True).exclude(
                pk=self.pk
            ).update(is_default=False)
        super().save(*args, **kwargs)


class DeliveryMethod(models.Model):
    """Спосіб доставки: скільки коштує, від якої суми безкоштовно, коли приїде.

    Ціна й назва потрапляють у замовлення знімком (`Order.delivery_name`,
    `Order.delivery_price`): тариф перевізника може змінитися завтра, а вже
    оформлене замовлення має лишитись таким, яким його підтвердили.
    """

    name = models.CharField('Назва', max_length=120)
    description = models.CharField('Опис', max_length=250, blank=True)
    price = models.DecimalField(
        'Вартість',
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    free_from = models.DecimalField(
        'Безкоштовно від суми',
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Порожньо — доставка платна завжди',
    )
    estimated_days = models.PositiveSmallIntegerField('Днів у дорозі', default=2)
    is_active = models.BooleanField('Активний', default=True)
    sort_order = models.PositiveSmallIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Спосіб доставки'
        verbose_name_plural = 'Способи доставки'
        ordering = ['sort_order', 'price']

    def __str__(self):
        return self.name

    def price_for(self, subtotal):
        """Скільки коштує доставка при такій сумі товарів."""
        if self.free_from is not None and subtotal >= self.free_from:
            return Decimal('0.00')
        return self.price

    def is_free_for(self, subtotal):
        return self.price_for(subtotal) == Decimal('0.00')

    def missing_for_free(self, subtotal):
        """Скільки не вистачає до безкоштовної доставки, або None.

        Рахуємо тут, а не в шаблоні: підказка «додайте ще на 300 ₴» — це
        найдієвіший апсел на checkout, і вона має бути однаковою скрізь.
        """
        if self.free_from is None or subtotal >= self.free_from:
            return None
        return self.free_from - subtotal

    def estimated_date(self, since=None):
        return (since or timezone.localdate()) + timedelta(days=self.estimated_days)


class Coupon(models.Model):
    """Промокод на знижку — у відсотках або фіксованою сумою."""

    TYPE_PERCENT = 'percent'
    TYPE_FIXED = 'fixed'

    TYPE_CHOICES = [
        (TYPE_PERCENT, 'Відсоток від суми'),
        (TYPE_FIXED, 'Фіксована сума'),
    ]

    code = models.CharField(
        'Код',
        max_length=32,
        unique=True,
        help_text='Зберігається у верхньому регістрі',
    )
    description = models.CharField('Опис', max_length=250, blank=True)
    discount_type = models.CharField(
        'Тип знижки', max_length=10, choices=TYPE_CHOICES, default=TYPE_PERCENT
    )
    discount_value = models.DecimalField(
        'Розмір знижки',
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Для відсоткової знижки — від 1 до 100',
    )
    valid_from = models.DateTimeField('Діє з')
    valid_to = models.DateTimeField('Діє до')
    max_uses = models.PositiveIntegerField(
        'Ліміт використань', default=0, help_text='0 — без обмеження'
    )
    used_count = models.PositiveIntegerField('Використано разів', default=0)
    min_order_amount = models.DecimalField(
        'Мінімальна сума замовлення',
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    is_active = models.BooleanField('Активний', default=True)
    created_at = models.DateTimeField('Створено', auto_now_add=True)

    class Meta:
        verbose_name = 'Промокод'
        verbose_name_plural = 'Промокоди'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['code'])]

    def __str__(self):
        return f'{self.code} ({self.get_discount_display()})'

    def save(self, *args, **kwargs):
        """Код завжди у верхньому регістрі — інакше «sillage» і «SILLAGE»
        стали б двома різними промокодами, а покупець набирає як завгодно."""
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def get_discount_display(self):
        # `:g` на Decimal лишає «50.00», тож цілі значення округлюємо явно:
        # «−10%» на кнопці читається, «−10.00%» виглядає як помилка верстки.
        if self.discount_value == self.discount_value.to_integral_value():
            value = f'{self.discount_value:.0f}'
        else:
            value = f'{self.discount_value:.2f}'

        if self.discount_type == self.TYPE_PERCENT:
            return f'−{value}%'
        # Грошова знижка — це ціна на екрані, тому тільки через спільний
        # форматувальник: інакше купон показує «−1500 ₴» біля «1 500 ₴» у підсумку.
        return f'−{format_price(self.discount_value)}'

    @property
    def uses_left(self):
        """Скільки використань лишилось, або None для безлімітного купона."""
        if not self.max_uses:
            return None
        return max(self.max_uses - self.used_count, 0)

    def discount_for(self, amount):
        """Розмір знижки для такої суми — ніколи не більший за саму суму."""
        if self.discount_type == self.TYPE_PERCENT:
            discount = amount * self.discount_value / Decimal('100')
        else:
            discount = self.discount_value
        return min(discount, amount).quantize(Decimal('0.01'))

    def is_valid_for(self, cart_total):
        """Чи можна застосувати купон. Повертає (можна, причина_відмови).

        Причина — готовий текст для покупця, а не код помилки: людині треба
        знати, що саме не так, інакше вона просто набере код ще раз.
        """
        now = timezone.now()

        if not self.is_active:
            return False, f'Промокод «{self.code}» більше не діє'

        if now < self.valid_from:
            return (
                False,
                f'Промокод почне діяти {date_format(timezone.localtime(self.valid_from), "j E Y")}',
            )

        if now > self.valid_to:
            return (
                False,
                f'Промокод діяв до {date_format(timezone.localtime(self.valid_to), "j E Y")}',
            )

        if self.max_uses and self.used_count >= self.max_uses:
            return False, f'Промокод «{self.code}» вичерпав ліміт використань'

        if cart_total < self.min_order_amount:
            return False, f'Мінімальна сума замовлення — {self.min_order_amount:.0f} ₴'

        return True, ''


class Order(models.Model):
    """Замовлення.

    Адреса доставки та назви/ціни товарів зберігаються як **знімок**:
    якщо користувач потім змінить адресу або магазин підніме ціну,
    вже оформлене замовлення має лишитися таким, яким його підтвердили.
    """

    STATUS_PENDING = 'pending'
    STATUS_PAID = 'paid'
    STATUS_SHIPPED = 'shipped'
    STATUS_DELIVERED = 'delivered'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Очікує обробки'),
        (STATUS_PAID, 'Оплачено'),
        (STATUS_SHIPPED, 'Відправлено'),
        (STATUS_DELIVERED, 'Доставлено'),
        (STATUS_CANCELLED, 'Скасовано'),
    ]

    PAYMENT_CHOICES = [
        ('cash', 'Готівкою при отриманні'),
        ('card', 'Оплата карткою онлайн'),
        ('bank', 'Банківський переказ'),
    ]

    order_number = models.CharField('Номер замовлення', max_length=32, unique=True, blank=True)
    # Замовлення без користувача — це гостьова покупка. PROTECT лишається:
    # видалення акаунта не має стирати історію продажів магазину.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='orders',
        null=True,
        blank=True,
        verbose_name='Користувач',
    )
    guest_email = models.EmailField('Email гостя', blank=True)
    guest_phone = models.CharField('Телефон гостя', max_length=20, blank=True)
    # Кошик, з якого зроблене замовлення. Потрібен, щоб після оплати закрити
    # саме його, а не «останній неоплачений кошик користувача» — той міг бути
    # уже новим. Nullable: замовлення можна створити й без кошика (адмінка),
    # а сам кошик колись підчистить прибирання старих даних.
    cart = models.ForeignKey(
        'cart.Cart',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='Кошик',
    )

    # Знімок адреси доставки
    shipping_full_name = models.CharField('ПІБ отримувача', max_length=200)
    shipping_phone = models.CharField('Телефон', max_length=20)
    shipping_country = models.CharField('Країна', max_length=100)
    shipping_city = models.CharField('Місто', max_length=100)
    shipping_postal_code = models.CharField('Поштовий індекс', max_length=20)
    shipping_address_line1 = models.CharField('Адреса (рядок 1)', max_length=250)
    shipping_address_line2 = models.CharField('Адреса (рядок 2)', max_length=250, blank=True)

    # Підсумок розкладено на складові: товари − знижка + доставка = total_amount.
    # `total_amount` лишається тим, що покупець платить, — на нього й далі
    # спирається payments/, тому його зміст не змінився.
    items_total = models.DecimalField(
        'Сума товарів', max_digits=10, decimal_places=2, default=Decimal('0.00')
    )
    coupon = models.ForeignKey(
        Coupon,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='Промокод',
    )
    # Знімок коду: сам купон можуть видалити, а в рахунку він має лишитись.
    coupon_code = models.CharField('Код промокоду', max_length=32, blank=True)
    discount_amount = models.DecimalField(
        'Знижка', max_digits=10, decimal_places=2, default=Decimal('0.00')
    )
    delivery_method = models.ForeignKey(
        DeliveryMethod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='Спосіб доставки',
    )
    delivery_name = models.CharField('Доставка (знімок назви)', max_length=120, blank=True)
    delivery_price = models.DecimalField(
        'Вартість доставки', max_digits=10, decimal_places=2, default=Decimal('0.00')
    )
    estimated_delivery_date = models.DateField('Очікувана доставка', null=True, blank=True)
    total_amount = models.DecimalField('Разом до сплати', max_digits=10, decimal_places=2)
    payment_method = models.CharField(
        'Спосіб оплати', max_length=20, choices=PAYMENT_CHOICES, default='cash'
    )
    status = models.CharField(
        'Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    notes = models.TextField('Коментар до замовлення', blank=True)

    created_at = models.DateTimeField('Створено', auto_now_add=True)
    updated_at = models.DateTimeField('Змінено', auto_now=True)

    class Meta:
        verbose_name = 'Замовлення'
        verbose_name_plural = 'Замовлення'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['order_number'])]
        constraints = [
            # Або акаунт, або email гостя — але не порожнеча. Без цього
            # замовлення могло б лишитись без жодного способу звʼязку.
            models.CheckConstraint(
                condition=models.Q(user__isnull=False) | ~models.Q(guest_email=''),
                name='order_has_customer',
            ),
        ]

    def __str__(self):
        return f'Замовлення {self.order_number}'

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self._generate_order_number()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_order_number():
        """Номер виду ORD-20260727-1A2B3C4D — читабельний і практично унікальний."""
        return f'ORD-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}'

    def get_absolute_url(self):
        return reverse('orders:order_detail', args=[self.order_number])

    def get_shipping_address_display(self):
        parts = [
            self.shipping_full_name,
            self.shipping_phone,
            f'{self.shipping_postal_code}, {self.shipping_city}, {self.shipping_country}',
            self.shipping_address_line1,
            self.shipping_address_line2,
        ]
        return '\n'.join(part for part in parts if part)

    def get_total_items(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def is_paid(self):
        return self.status not in (Order.STATUS_PENDING, Order.STATUS_CANCELLED)

    @property
    def requires_online_payment(self):
        return self.payment_method == 'card' and self.status == Order.STATUS_PENDING

    @property
    def is_guest_order(self):
        return self.user_id is None

    @property
    def customer_email(self):
        """Куди слати листи — незалежно від того, є акаунт чи ні."""
        if self.user_id and self.user.email:
            return self.user.email
        return self.guest_email

    @property
    def customer_name(self):
        """Як звертатись до покупця в листі й у рахунку."""
        if self.user_id:
            return self.user.get_display_name()
        return self.shipping_full_name or self.guest_email

    @property
    def customer_phone(self):
        return self.shipping_phone or self.guest_phone

    @property
    def has_discount(self):
        return self.discount_amount > 0

    def can_be_cancelled(self):
        """Скасувати можна лише необроблене замовлення і лише першу добу.

        Після `pending` замовлення вже поїхало на склад комплектуватись, і
        відкотити його самотужки покупець не може — тільки через підтримку.
        """
        if self.status != Order.STATUS_PENDING:
            return False
        if self.created_at is None:
            return False
        return timezone.now() - self.created_at <= CANCELLATION_WINDOW

    def cancellation_deadline(self):
        """Момент, до якого кнопка «Скасувати» ще активна."""
        if self.created_at is None:
            return None
        return self.created_at + CANCELLATION_WINDOW

    def cancel(self, by_user=None, note=''):
        """Скасувати замовлення й повернути товари на склад.

        Тонка обгортка над `orders.services.cancel_order`: логіка транзакції
        живе в одному місці, а модель дає до неї зручний вхід.
        """
        from .services import cancel_order

        return cancel_order(self, actor=by_user, note=note)


class OrderItem(models.Model):
    """Позиція замовлення — знімок товару на момент покупки."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Замовлення',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Товар',
    )
    product_name = models.CharField('Назва товару', max_length=150)
    price = models.DecimalField('Ціна за одиницю', max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField('Кількість', default=1)

    class Meta:
        verbose_name = 'Позиція замовлення'
        verbose_name_plural = 'Позиції замовлення'

    def __str__(self):
        return f'{self.quantity} x {self.product_name}'

    def get_total_price(self):
        return self.price * self.quantity


class OrderStatusHistory(models.Model):
    """Журнал змін статусу замовлення."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='status_history',
        verbose_name='Замовлення',
    )
    status = models.CharField('Статус', max_length=20, choices=Order.STATUS_CHOICES)
    note = models.TextField('Примітка', blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Автор зміни',
    )
    created_at = models.DateTimeField('Створено', auto_now_add=True)

    class Meta:
        verbose_name = 'Історія статусів'
        verbose_name_plural = 'Історія статусів'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.order.order_number}: {self.get_status_display()}'

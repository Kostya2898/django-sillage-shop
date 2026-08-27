"""Моделі замовлень: адреси доставки, замовлення, позиції та історія статусів."""

import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from shop.models import Product


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
            ShippingAddress.objects.filter(
                user=self.user, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


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
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='orders',
        verbose_name='Користувач',
    )

    # Знімок адреси доставки
    shipping_full_name = models.CharField('ПІБ отримувача', max_length=200)
    shipping_phone = models.CharField('Телефон', max_length=20)
    shipping_country = models.CharField('Країна', max_length=100)
    shipping_city = models.CharField('Місто', max_length=100)
    shipping_postal_code = models.CharField('Поштовий індекс', max_length=20)
    shipping_address_line1 = models.CharField('Адреса (рядок 1)', max_length=250)
    shipping_address_line2 = models.CharField('Адреса (рядок 2)', max_length=250, blank=True)

    total_amount = models.DecimalField('Сума замовлення', max_digits=10, decimal_places=2)
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

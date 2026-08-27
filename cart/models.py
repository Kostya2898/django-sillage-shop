"""Моделі кошика, що зберігається в базі даних."""

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models

from shop.models import Product


class Cart(models.Model):
    """Кошик у базі даних.

    Використовується для зареєстрованих користувачів. Після успішної оплати
    кошик позначається `paid_status=True` і більше не використовується —
    користувач отримує новий порожній кошик.
    """

    cart_code = models.CharField('Код кошика', max_length=250, unique=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='carts',
        verbose_name='Користувач',
    )
    paid_status = models.BooleanField('Оплачено', default=False)
    created_at = models.DateTimeField('Створено', auto_now_add=True)
    modified_at = models.DateTimeField('Змінено', auto_now=True)

    class Meta:
        verbose_name = 'Кошик'
        verbose_name_plural = 'Кошики'
        ordering = ['-created_at']

    def __str__(self):
        owner = self.user.username if self.user_id else 'гість'
        return f'Кошик {self.cart_code} ({owner})'

    def save(self, *args, **kwargs):
        if not self.cart_code:
            self.cart_code = uuid.uuid4().hex
        super().save(*args, **kwargs)

    def get_total_items(self):
        """Скільки одиниць товару всього в кошику."""
        return sum(item.quantity for item in self.items.all())

    def get_total_price(self):
        """Загальна сума кошика."""
        return sum(
            (item.get_total_price() for item in self.items.select_related('product')),
            Decimal('0.00'),
        )


class CartItem(models.Model):
    """Один товар у кошику разом із кількістю."""

    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Кошик',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        verbose_name='Товар',
    )
    quantity = models.PositiveIntegerField('Кількість', default=1)
    date_added = models.DateTimeField('Додано', auto_now_add=True)

    class Meta:
        verbose_name = 'Товар у кошику'
        verbose_name_plural = 'Товари у кошику'
        # Один і той самий товар не може двічі потрапити в один кошик —
        # замість другого рядка ми збільшуємо quantity.
        constraints = [
            models.UniqueConstraint(fields=['cart', 'product'], name='unique_cart_product'),
        ]

    def __str__(self):
        return f'{self.quantity} x {self.product.name}'

    def get_total_price(self):
        return self.product.price * self.quantity

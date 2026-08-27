"""Модель транзакції — запис про спробу оплати."""

from django.conf import settings
from django.db import models

from orders.models import Order


class Transaction(models.Model):
    """Одна спроба оплати замовлення через платіжний шлюз.

    Життєвий цикл статусу:
        spending  → створено, користувача відправлено на сторінку шлюзу
        completed → шлюз підтвердив оплату і сума/валюта збіглися
        failed    → шлюз відмовив або перевірка не пройшла
    """

    STATUS_SPENDING = 'spending'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_SPENDING, 'В процесі'),
        (STATUS_COMPLETED, 'Завершено'),
        (STATUS_FAILED, 'Помилка'),
    ]

    reference = models.CharField('Референс (tx_ref)', max_length=255, unique=True)
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='transactions',
        verbose_name='Замовлення',
    )
    amount = models.DecimalField('Сума', max_digits=10, decimal_places=2)
    currency = models.CharField('Валюта', max_length=10)
    status = models.CharField(
        'Статус', max_length=50, choices=STATUS_CHOICES, default=STATUS_SPENDING
    )
    gateway_transaction_id = models.CharField('ID у шлюзі', max_length=255, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='transactions',
        verbose_name='Користувач',
    )
    created_at = models.DateTimeField('Створено', auto_now_add=True)
    updated_at = models.DateTimeField('Змінено', auto_now=True)

    class Meta:
        verbose_name = 'Транзакція'
        verbose_name_plural = 'Транзакції'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.reference} — {self.amount} {self.currency} ({self.get_status_display()})'

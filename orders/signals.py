"""Сигнали застосунку orders: зміна статусу замовлення.

Перехід статусу — це завжди дві дії: запис в історію і лист покупцю. Раніше
кожен, хто міняв статус (адмінка, оплата, скасування), робив їх сам, і будь-хто
новий міг забути одну з них. Тепер джерело істини одне: змінив `order.status`
і зберіг — історія й лист будуть.

**Чому дві половини, а не один `pre_save`.** `pre_save` тут лише *помічає*
перехід: на цей момент нове значення ще не в базі. Писати історію й тим паче
слати лист до коміту не можна — якщо збереження впаде, покупець отримає
повідомлення про статус, якого замовлення так і не набуло. Тому дія — у
`post_save`, коли рядок уже записаний.

Хто змінює статус, може пояснити причину й назватись:

    order.status = Order.STATUS_SHIPPED
    order._status_note = 'Передано в Нову пошту, ТТН 20450...'
    order._status_actor = request.user
    order.save(update_fields=['status', 'updated_at'])
"""

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .emails import (
    send_order_cancelled_email,
    send_order_status_email,
    send_payment_received_email,
)
from .models import Order, OrderStatusHistory

logger = logging.getLogger(__name__)

# Який лист відповідає якому переходу. Статуси, яких тут немає, отримують
# загальний лист «статус змінився».
STATUS_EMAILS = {
    Order.STATUS_PAID: send_payment_received_email,
    Order.STATUS_CANCELLED: send_order_cancelled_email,
}

# Службовий атрибут, у якому pre_save лишає попередній статус для post_save.
PREVIOUS_STATUS = '_previous_status'


@receiver(pre_save, sender=Order)
def remember_previous_status(sender, instance, **kwargs):
    """Запамʼятати статус, який зараз у базі, поки його не перезаписали."""
    if instance.pk is None:
        setattr(instance, PREVIOUS_STATUS, None)
        return

    # Коли зберігають перелік полів і статусу серед них немає, переходу бути
    # не може — зайвий запит до бази на кожен `save(update_fields=...)` теж
    # не потрібен.
    update_fields = kwargs.get('update_fields')
    if update_fields is not None and 'status' not in update_fields:
        setattr(instance, PREVIOUS_STATUS, instance.status)
        return

    previous = Order.objects.filter(pk=instance.pk).values_list('status', flat=True).first()
    setattr(instance, PREVIOUS_STATUS, previous)


@receiver(post_save, sender=Order)
def record_status_change(sender, instance, created, **kwargs):
    """Записати перехід в історію і сповістити покупця."""
    if created:
        # Початковий запис в історії робить `create_order`: там є контекст
        # (спосіб оплати, хто оформив), якого сигнал не знає.
        return

    previous = getattr(instance, PREVIOUS_STATUS, None)
    if previous is None or previous == instance.status:
        return

    note = getattr(instance, '_status_note', '')
    actor = getattr(instance, '_status_actor', None)

    OrderStatusHistory.objects.create(
        order=instance,
        status=instance.status,
        note=note or f'Статус змінено: «{instance.get_status_display()}»',
        created_by=actor,
    )

    # Атрибути одноразові: наступне збереження того самого обʼєкта не має
    # успадкувати чужу примітку.
    instance._status_note = ''
    instance._status_actor = None
    setattr(instance, PREVIOUS_STATUS, instance.status)

    send = STATUS_EMAILS.get(instance.status, send_order_status_email)
    send(instance)

    logger.info(
        'Замовлення %s: %s → %s',
        instance.order_number,
        previous,
        instance.status,
    )

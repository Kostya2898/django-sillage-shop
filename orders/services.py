"""Бізнес-логіка замовлень, яка не має жити у view чи в адмінці."""

import logging

from django.db import transaction
from django.db.models import F

from shop.models import Product

from .models import Order, OrderStatusHistory

logger = logging.getLogger(__name__)


@transaction.atomic
def cancel_order(order, actor=None, note=''):
    """Скасувати замовлення і повернути його позиції на склад.

    Повертає `True`, якщо перехід справді відбувся, і `False`, якщо замовлення
    вже було скасоване раніше.

    Ідемпотентність тримається на самому статусі: перехід у `cancelled` і
    повернення складу відбуваються в одній транзакції під `select_for_update`,
    тому «статус уже cancelled» означає рівно те саме, що «склад уже повернули».
    Окреме поле-прапорець для цього не потрібне.
    """
    locked = Order.objects.select_for_update().get(pk=order.pk)

    if locked.status == Order.STATUS_CANCELLED:
        logger.info('Замовлення %s уже скасоване — склад не чіпаємо', locked.order_number)
        return False

    for item in locked.items.all():
        # OrderItem.product має on_delete=SET_NULL: товар могли прибрати
        # з каталогу вже після покупки, і повертати тоді нема куди.
        if item.product_id is None:
            logger.warning(
                'Позиція «%s» замовлення %s не має товару — склад не повертаємо',
                item.product_name,
                locked.order_number,
            )
            continue

        # F() рахує на боці бази — без гонок «прочитав-змінив-записав».
        Product.objects.filter(pk=item.product_id).update(stock=F('stock') + item.quantity)

    locked.status = Order.STATUS_CANCELLED
    locked.save(update_fields=['status', 'updated_at'])

    OrderStatusHistory.objects.create(
        order=locked,
        status=Order.STATUS_CANCELLED,
        note=note or 'Замовлення скасовано, товари повернуто на склад',
        created_by=actor,
    )

    # Синхронізуємо переданий обʼєкт, щоб той, хто викликав, не працював
    # зі застарілим статусом.
    order.status = Order.STATUS_CANCELLED

    logger.info('Замовлення %s скасовано, склад повернуто', locked.order_number)
    return True

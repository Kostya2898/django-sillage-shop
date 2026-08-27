"""Email-сповіщення про замовлення.

У режимі розробки EMAIL_BACKEND — console, тож усі листи просто друкуються
в термінал, де запущено runserver.

**Жодна функція цього модуля не піднімає виняток назовні.** Лист — це не
частина транзакції покупки: замовлення вже створене й склад уже списаний,
тому недоступний поштовий сервер не має права обвалити сторінку покупцю.
Усі функції повертають True/False, і викликач сам вирішує, що сказати
користувачу.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, mail_admins
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def _send_order_email(order, subject, template_base):
    """Надіслати лист про замовлення у двох форматах: text/plain та text/html.

    `template_base` — спільний префікс шаблонів, наприклад
    'orders/emails/order_confirmation' → .txt та .html.

    Повертає True, якщо лист пішов, і False у будь-якому іншому випадку.
    """
    recipient = order.user.email
    if not recipient:
        logger.warning('У користувача %s немає email — лист не надіслано', order.user)
        return False

    try:
        context = {'order': order, 'items': order.items.all()}
        text_content = render_to_string(f'{template_base}.txt', context)
        html_content = render_to_string(f'{template_base}.html', context)

        message = EmailMultiAlternatives(
            subject,
            text_content,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
        )
        message.attach_alternative(html_content, 'text/html')

        # fail_silently=False свідомо: нам потрібен сам виняток, щоб його
        # залогувати з трейсбеком. Ковтаємо його ми, а не Django.
        message.send(fail_silently=False)
    except Exception:
        # Широкий except тут навмисний. Причин падіння багато — SMTP лежить,
        # DNS не резолвиться, шаблон зламали, BadHeaderError на темі — і жодна
        # з них не варта 500-ї сторінки покупцю, у якого замовлення вже
        # прийнято. logger.exception збереже трейсбек для розбору.
        logger.exception('Не вдалося надіслати лист для замовлення %s', order.order_number)
        return False

    return True


def send_order_confirmation_email(order):
    """Лист покупцю: замовлення прийнято."""
    subject = f'Замовлення #{order.order_number} підтверджено'
    return _send_order_email(order, subject, 'orders/emails/order_confirmation')


def send_payment_received_email(order):
    """Лист покупцю: оплату отримано."""
    subject = f'Оплату за замовлення #{order.order_number} отримано'
    return _send_order_email(order, subject, 'orders/emails/payment_received')


def notify_admins_about_order(order):
    """Коротке сповіщення адміністраторам зі списку ADMINS про нове замовлення."""
    try:
        mail_admins(
            subject=f'Нове замовлення {order.order_number}',
            message=(
                f'Користувач: {order.user.username} ({order.user.email})\n'
                f'Сума: {order.total_amount} грн\n'
                f'Спосіб оплати: {order.get_payment_method_display()}\n'
                f'Позицій: {order.items.count()}\n'
            ),
            fail_silently=True,
        )
    except Exception:
        # fail_silently=True ковтає помилки самої відправки, але не помилки
        # формування листа — наприклад, якщо ADMINS налаштовані криво.
        logger.exception(
            'Не вдалося сповістити адміністраторів про замовлення %s',
            order.order_number,
        )
        return False

    return True

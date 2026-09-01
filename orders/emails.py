"""Email-сповіщення про замовлення.

У режимі розробки EMAIL_BACKEND — console, тож усі листи просто друкуються
в термінал, де запущено runserver.

**Жодна функція цього модуля не піднімає виняток назовні.** Лист — це не
частина транзакції покупки: замовлення вже створене й склад уже списаний,
тому недоступний поштовий сервер не має права обвалити сторінку покупцю.
Усі функції повертають True/False, і викликач сам вирішує, що сказати
користувачу.

Адресат береться з `order.customer_email` — властивість, яка однаково працює
для замовлення з акаунтом і для гостьового.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, mail_admins
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)


def _order_context(order):
    """Спільний контекст усіх листів про замовлення."""
    from .services import order_url

    return {
        'order': order,
        'items': order.items.all(),
        'site_name': 'SILLAGE',
        'order_url': order_url(order),
        'catalogue_url': f'{settings.SITE_URL}{reverse("shop:product_list")}',
    }


def _send_order_email(order, subject, template_base, attachments=()):
    """Надіслати лист про замовлення у двох форматах: text/plain та text/html.

    `template_base` — спільний префікс шаблонів, наприклад
    'orders/emails/order_confirmation' → .txt та .html.

    `attachments` — послідовність `(імʼя, вміст, mime-тип)`.

    Повертає True, якщо лист пішов, і False у будь-якому іншому випадку.
    """
    # Пошук адресата теж під `try`. Раніше він стояв вище, і це було
    # нешкідливо, поки функцію викликали напряму. Тепер вона виконується
    # колбеком `on_commit`, і будь-який виняток звідси пішов би не покупцю в
    # лог, а нагору — у код, який завершує транзакцію. Тіло функції має бути
    # закрите цілком, без «майже».
    try:
        recipient = order.customer_email
        if not recipient:
            logger.warning(
                'Замовлення %s не має адреси покупця — лист не надіслано',
                order.order_number,
            )
            return False

        context = _order_context(order)
        text_content = render_to_string(f'{template_base}.txt', context)
        html_content = render_to_string(f'{template_base}.html', context)

        message = EmailMultiAlternatives(
            subject,
            text_content,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
        )
        message.attach_alternative(html_content, 'text/html')

        for name, content, mimetype in attachments:
            message.attach(name, content, mimetype)

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


def _invoice_attachment(order):
    """Рахунок у PDF для вкладення, або порожньо, якщо його не вдалося зібрати.

    Рахунок — приємне доповнення, а не умова відправки: якщо генератор PDF
    спіткнувся, лист із деталями замовлення покупець усе одно має отримати.
    """
    from .pdf import render_order_invoice

    try:
        content = render_order_invoice(order)
    except Exception:
        logger.exception('Не вдалося зібрати PDF-рахунок для %s', order.order_number)
        return ()

    return ((f'rakhunok-{order.order_number}.pdf', content, 'application/pdf'),)


def send_order_confirmation_email(order):
    """Лист покупцю: замовлення прийнято. З рахунком у вкладенні."""
    subject = f'Замовлення #{order.order_number} підтверджено'
    return _send_order_email(
        order,
        subject,
        'orders/emails/order_confirmation',
        attachments=_invoice_attachment(order),
    )


def send_payment_received_email(order):
    """Лист покупцю: оплату отримано."""
    subject = f'Оплату за замовлення #{order.order_number} отримано'
    return _send_order_email(order, subject, 'orders/emails/payment_received')


def send_order_status_email(order):
    """Лист покупцю: статус замовлення змінився."""
    subject = f'Статус замовлення #{order.order_number}: {order.get_status_display().lower()}'
    return _send_order_email(order, subject, 'orders/emails/status_changed')


def send_order_cancelled_email(order):
    """Лист покупцю: замовлення скасовано."""
    subject = f'Замовлення #{order.order_number} скасовано'
    return _send_order_email(order, subject, 'orders/emails/order_cancelled')


def notify_admins_about_order(order):
    """Коротке сповіщення адміністраторам зі списку ADMINS про нове замовлення."""
    customer = order.user.username if order.user_id else f'гість {order.guest_email}'

    try:
        mail_admins(
            subject=f'Нове замовлення {order.order_number}',
            message=(
                f'Покупець: {customer} ({order.customer_email})\n'
                f'Сума: {order.total_amount} грн\n'
                f'Спосіб оплати: {order.get_payment_method_display()}\n'
                f'Доставка: {order.delivery_name or "—"}\n'
                f'Промокод: {order.coupon_code or "—"}\n'
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

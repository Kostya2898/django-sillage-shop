"""Оплата замовлення через (мок) платіжний шлюз.

Потік такий самий, як у справжніх шлюзів на кшталт Flutterwave чи PayPal:

    1. initiate_payment  — рахуємо суму, створюємо Transaction(status='spending')
                           і віддаємо користувачу посилання на сторінку шлюзу;
    2. mock_gateway      — сторінка «шлюзу», де користувач платить або скасовує
                           (у реальному житті це сайт платіжної системи);
    3. payment_callback  — шлюз повертає користувача до нас із результатом,
                           а ми звіряємо підпис, статус, суму й валюту
                           та закриваємо замовлення.

УВАГА: це навчальний мок, а не інтеграція з платіжним провайдером. Реальних
грошей він не рухає. Підпис нижче робить його чесним у межах демонстрації —
результат не можна підробити, склавши URL руками, — але в production
на його місці має стояти справжній шлюз із власною верифікацією.
"""

import logging
import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from cart.models import Cart
from orders.emails import send_payment_received_email
from orders.models import Order, OrderStatusHistory

from .models import Transaction
from .signing import signature_is_valid, transaction_signature

logger = logging.getLogger(__name__)


def _calculate_total(order):
    """Сума до сплати = сума замовлення + податок зі settings."""
    tax_rate = Decimal(settings.PAYMENT_TAX_RATE)
    tax = (order.total_amount * tax_rate).quantize(Decimal('0.01'))
    return order.total_amount + tax


@login_required
def initiate_payment(request, order_number):
    """Крок 1: створити транзакцію та відправити користувача на шлюз."""
    order = get_object_or_404(Order, order_number=order_number, user=request.user)

    if order.is_paid:
        messages.info(request, 'Це замовлення вже оплачено')
        return redirect('orders:order_detail', order_number=order.order_number)

    tx_ref = uuid.uuid4().hex
    total_amount = _calculate_total(order)

    transaction = Transaction.objects.create(
        reference=tx_ref,
        order=order,
        amount=total_amount,
        currency=settings.PAYMENT_CURRENCY,
        user=request.user,
        status=Transaction.STATUS_SPENDING,
    )

    redirect_url = request.build_absolute_uri(reverse('payments:payment_callback'))

    # Так виглядав би payload для справжнього шлюзу:
    #
    # payload = {
    #     'tx_ref': tx_ref,
    #     'amount': str(total_amount),
    #     'currency': transaction.currency,
    #     'redirect_url': redirect_url,
    #     'customer': {'email': request.user.email, 'name': order.shipping_full_name},
    # }
    # headers = {'Authorization': f'Bearer {settings.PAYMENT_SECRET_KEY}'}
    # response = requests.post(settings.PAYMENT_API_URL, json=payload, headers=headers)
    # hosted_link = response.json()['data']['link']
    # return redirect(hosted_link)
    #
    # Замість мережевого виклику ведемо користувача на власну сторінку-імітацію.
    hosted_link = reverse('payments:mock_gateway', args=[tx_ref])

    return render(
        request,
        'payments/initiate.html',
        {
            'order': order,
            'transaction': transaction,
            'hosted_link': hosted_link,
            'redirect_url': redirect_url,
        },
    )


@login_required
def mock_gateway(request, tx_ref):
    """Крок 2: сторінка-імітація платіжного шлюзу."""
    transaction = get_object_or_404(Transaction, reference=tx_ref, user=request.user)

    if transaction.status != Transaction.STATUS_SPENDING:
        messages.info(request, 'Цю транзакцію вже оброблено')
        return redirect('orders:order_detail', order_number=transaction.order.order_number)

    # Підпис віддаємо в шаблон, щоб кнопки «Оплатити» і «Скасувати» повернулись
    # із ним. У справжньому шлюзі його б поставив сам провайдер.
    signature = transaction_signature(
        transaction.reference, transaction.amount, transaction.currency
    )

    return render(
        request,
        'payments/mock_gateway.html',
        {'transaction': transaction, 'signature': signature},
    )


@login_required
def payment_callback(request):
    """Крок 3: шлюз повернув користувача — перевіряємо результат.

    Параметрам URL не вірить нічого. Порядок перевірок:

        1. підпис HMAC є і сходиться (інакше 400);
        2. транзакція існує і належить цьому користувачу (інакше 404);
        3. транзакція ще в статусі `spending` — повторний callback нічого
           не змінює і другого листа не шле;
        4. сума й валюта транзакції збігаються із замовленням;
        5. і лише тоді дивимось на статус від «шлюзу».

    У справжній інтеграції кроки 1 і 5 замінює verify-запит до API провайдера.
    """
    tx_ref = request.GET.get('tx_ref')
    gateway_status = request.GET.get('status')
    gateway_transaction_id = request.GET.get('transaction_id', '')
    signature = request.GET.get('signature')

    if not tx_ref:
        logger.warning('Callback без tx_ref від користувача %s', request.user)
        return HttpResponseBadRequest('Некоректний запит платіжного шлюзу')

    transaction = get_object_or_404(Transaction, reference=tx_ref, user=request.user)
    order = transaction.order

    # 1. Підпис. Рахуємо від полів транзакції в базі, а не від того, що прийшло
    # в URL, — тому підмінити суму, лишивши старий підпис, не вийде.
    if not signature_is_valid(
        signature, transaction.reference, transaction.amount, transaction.currency
    ):
        logger.warning(
            'Невірний підпис callback для транзакції %s (користувач %s)',
            transaction.reference,
            request.user,
        )
        return HttpResponseBadRequest('Підпис платіжного шлюзу не підтверджено')

    # 2. Ідемпотентність. Транзакція, яку вже обробили, більше нічого не змінює
    # і другого листа не спричиняє.
    if transaction.status != Transaction.STATUS_SPENDING:
        messages.info(request, 'Цю оплату вже оброблено раніше')
        return redirect('orders:order_detail', order_number=order.order_number)

    # 3. Сума й валюта мають збігатися із замовленням.
    expected_amount = _calculate_total(order)
    if transaction.amount != expected_amount or transaction.currency != settings.PAYMENT_CURRENCY:
        logger.error(
            'Транзакція %s розійшлася із замовленням %s: %s %s проти %s %s',
            transaction.reference,
            order.order_number,
            transaction.amount,
            transaction.currency,
            expected_amount,
            settings.PAYMENT_CURRENCY,
        )
        _fail_transaction(transaction, gateway_transaction_id)
        messages.error(
            request,
            'Сума платежу не збігається із замовленням. Оплату скасовано — '
            'спробуйте оформити оплату ще раз зі сторінки замовлення.',
        )
        return redirect('orders:order_detail', order_number=order.order_number)

    # 4. І лише тепер — результат від «шлюзу».
    if gateway_status != 'successful':
        _fail_transaction(transaction, gateway_transaction_id)
        messages.error(
            request,
            'Оплату не підтверджено. Замовлення збережено — оплатити його '
            'можна кнопкою на сторінці замовлення.',
        )
        return redirect('orders:order_detail', order_number=order.order_number)

    _complete_payment(transaction, gateway_transaction_id)

    messages.success(
        request,
        f'Оплату за замовлення #{order.order_number} успішно підтверджено!',
    )
    return redirect('orders:order_detail', order_number=order.order_number)


def _fail_transaction(transaction, gateway_transaction_id):
    """Позначити транзакцію невдалою. Замовлення при цьому не чіпаємо."""
    transaction.status = Transaction.STATUS_FAILED
    transaction.gateway_transaction_id = gateway_transaction_id
    transaction.save(update_fields=['status', 'gateway_transaction_id', 'updated_at'])


@db_transaction.atomic
def _complete_payment(transaction, gateway_transaction_id):
    """Позначити транзакцію, замовлення та кошик оплаченими.

    Блокування рядка транзакції закриває гонку двох одночасних callback-ів:
    другий дочекається першого й побачить уже `completed`.
    """
    locked = Transaction.objects.select_for_update().get(pk=transaction.pk)
    if locked.status == Transaction.STATUS_COMPLETED:
        return False

    transaction.status = Transaction.STATUS_COMPLETED
    transaction.gateway_transaction_id = gateway_transaction_id
    transaction.save(update_fields=['status', 'gateway_transaction_id', 'updated_at'])

    order = transaction.order
    order.status = Order.STATUS_PAID
    order.save(update_fields=['status', 'updated_at'])

    OrderStatusHistory.objects.create(
        order=order,
        status=Order.STATUS_PAID,
        note=f'Оплату підтверджено. Транзакція {transaction.reference}',
        created_by=transaction.user,
    )

    # Закриваємо рівно той кошик, з якого зроблене це замовлення. Фільтр
    # «усі неоплачені кошики користувача» закривав і той, який покупець набрав
    # уже після оформлення, — і товари з нього мовчки зникали.
    if order.cart_id:
        Cart.objects.filter(pk=order.cart_id).update(paid_status=True)

    send_payment_received_email(order)
    return True

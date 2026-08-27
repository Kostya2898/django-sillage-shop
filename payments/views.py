"""Оплата замовлення через (мок) платіжний шлюз.

Потік такий самий, як у справжніх шлюзів на кшталт Flutterwave чи PayPal:

    1. initiate_payment  — рахуємо суму, створюємо Transaction(status='spending')
                           і віддаємо користувачу посилання на сторінку шлюзу;
    2. mock_gateway      — сторінка «шлюзу», де користувач платить або скасовує
                           (у реальному житті це сайт платіжної системи);
    3. payment_callback  — шлюз повертає користувача до нас із результатом,
                           а ми звіряємо статус, суму й валюту та закриваємо
                           замовлення.
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from cart.models import Cart
from orders.emails import send_payment_received_email
from orders.models import Order, OrderStatusHistory

from .models import Transaction


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

    return render(request, 'payments/initiate.html', {
        'order': order,
        'transaction': transaction,
        'hosted_link': hosted_link,
        'redirect_url': redirect_url,
    })


@login_required
def mock_gateway(request, tx_ref):
    """Крок 2: сторінка-імітація платіжного шлюзу."""
    transaction = get_object_or_404(Transaction, reference=tx_ref, user=request.user)

    if transaction.status != Transaction.STATUS_SPENDING:
        messages.info(request, 'Цю транзакцію вже оброблено')
        return redirect('orders:order_detail', order_number=transaction.order.order_number)

    return render(request, 'payments/mock_gateway.html', {'transaction': transaction})


@login_required
def payment_callback(request):
    """Крок 3: шлюз повернув користувача — перевіряємо результат.

    Реальний callback отримує лише `status`, `tx_ref` і `transaction_id`,
    і **обов'язково** сам звертається до API шлюзу за офіційними даними:
    параметрам у URL довіряти не можна, їх легко підробити.
    """
    tx_ref = request.GET.get('tx_ref')
    gateway_status = request.GET.get('status')
    gateway_transaction_id = request.GET.get('transaction_id', '')

    transaction = get_object_or_404(Transaction, reference=tx_ref, user=request.user)

    if transaction.status == Transaction.STATUS_COMPLETED:
        messages.info(request, 'Оплату вже підтверджено раніше')
        return redirect('orders:order_detail', order_number=transaction.order.order_number)

    # Тут був би другий запит до шлюзу — verify endpoint:
    #
    # verification = requests.get(
    #     f'{settings.PAYMENT_API_URL}/{gateway_transaction_id}/verify',
    #     headers={'Authorization': f'Bearer {settings.PAYMENT_SECRET_KEY}'},
    # ).json()['data']
    #
    # Мок повертає ті самі дані, що ми відправили.
    verification = {
        'status': gateway_status,
        'amount': str(transaction.amount),
        'currency': transaction.currency,
    }

    checks_passed = (
        verification['status'] == 'successful'
        and Decimal(verification['amount']) == transaction.amount
        and verification['currency'] == transaction.currency
    )

    if not checks_passed:
        transaction.status = Transaction.STATUS_FAILED
        transaction.gateway_transaction_id = gateway_transaction_id
        transaction.save(update_fields=['status', 'gateway_transaction_id', 'updated_at'])

        messages.error(request, 'Оплату не підтверджено. Спробуйте ще раз.')
        return redirect('orders:order_detail', order_number=transaction.order.order_number)

    _complete_payment(transaction, gateway_transaction_id)

    messages.success(
        request,
        f'Оплату за замовлення #{transaction.order.order_number} успішно підтверджено!',
    )
    return redirect('orders:order_detail', order_number=transaction.order.order_number)


@db_transaction.atomic
def _complete_payment(transaction, gateway_transaction_id):
    """Позначити транзакцію, замовлення та кошик оплаченими."""
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

    # Позначаємо поточний кошик користувача оплаченим — у README історія
    # покупок будується саме за ознакою Cart.paid_status=True.
    Cart.objects.filter(user=transaction.user, paid_status=False).update(paid_status=True)

    send_payment_received_email(order)

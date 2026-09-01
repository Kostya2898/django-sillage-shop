"""Падіння пошти всередині `on_commit` не має обвалювати запит.

Після переходу на `transaction.on_commit` (orders/signals.py) точка відправки
змінилась: виняток вилітає вже не з `order.save()`, а з місця, де база
комітить транзакцію. Якби `try/except` з B1b стояв на рівні **виклику**
(`try: send(order)`), а не всередині `_send_order_email`, то в новій схемі він
би нічого не ловив: колбек виконується пізніше й в іншому місці стека, і
виняток із нього піднявся б до коду, який завершує `atomic`. Покупець
отримав би 500 на скасуванні, яке насправді пройшло.

**Чому `TransactionTestCase`, а не звичайний `TestCase`.** `TestCase` тримає
тест у транзакції й ніколи не комітить, тому колбеки `on_commit` під час
запиту не виконуються взагалі — і тест на «запит не впав» проходив би завжди,
нічого не перевіряючи. Тут потрібні справжні коміти, щоб колбек спрацював
усередині запиту, як на проді.
"""

import logging
from smtplib import SMTPException
from unittest import mock

from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.test import TransactionTestCase
from django.urls import reverse

from orders.models import Order, OrderStatusHistory
from payments.models import Transaction
from payments.signing import transaction_signature
from testing.factories import (
    DEFAULT_PASSWORD,
    OrderFactory,
    OrderItemFactory,
    ProductFactory,
    UserFactory,
)


def broken_mail():
    """Підміна відправки, яка падає так, як падає реальний SMTP."""
    return mock.patch.object(
        EmailMultiAlternatives,
        'send',
        side_effect=SMTPException('поштовий сервер недоступний'),
    )


class MailFailureInsideCommitTests(TransactionTestCase):
    """Справжні коміти: колбек `on_commit` виконується всередині запиту."""

    # Тарифи доставки приїжджають міграцією 0003, а TransactionTestCase
    # очищає таблиці після себе — без цього наступні тести лишились би без них.
    serialized_rollback = True

    def setUp(self):
        # Падіння пошти тут очікуване й перевіряється окремо; у виводі прогону
        # трейсбеки лише заважають читати результат.
        logging.disable(logging.ERROR)
        self.addCleanup(logging.disable, logging.NOTSET)

        self.user = UserFactory()
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)

        self.product = ProductFactory(stock=7)
        self.order = OrderFactory(user=self.user, status=Order.STATUS_PENDING)
        OrderItemFactory(
            order=self.order,
            product=self.product,
            product_name=self.product.name,
            price=self.product.price,
            quantity=3,
        )
        mail.outbox.clear()

    def test_cancelling_survives_a_dead_mail_server(self):
        """Головний тест: замовлення скасоване, склад повернуто, 500 немає."""
        with broken_mail():
            response = self.client.post(
                reverse('orders:order_cancel', args=[self.order.order_number])
            )

        # Запит завершився редіректом, а не помилкою.
        self.assertEqual(response.status_code, 302)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_CANCELLED)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10, 'Склад мав повернутись: 7 + 3')

    def test_history_is_written_even_when_mail_is_down(self):
        with broken_mail():
            self.client.post(reverse('orders:order_cancel', args=[self.order.order_number]))

        self.assertTrue(
            OrderStatusHistory.objects.filter(
                order=self.order, status=Order.STATUS_CANCELLED
            ).exists()
        )

    def test_user_sees_success_not_an_error(self):
        """Покупцю кажуть, що замовлення скасовано, — бо воно справді скасовано."""
        with broken_mail():
            response = self.client.post(
                reverse('orders:order_cancel', args=[self.order.order_number]),
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        texts = [str(m) for m in response.context['messages']]
        self.assertTrue(any('скасовано' in text for text in texts), texts)

    def test_failure_is_logged_with_the_order_number(self):
        """Лист не пішов — про це має лишитись слід, а не тиша."""
        logging.disable(logging.NOTSET)

        with broken_mail(), self.assertLogs('orders.emails', level='ERROR') as logs:
            self.client.post(reverse('orders:order_cancel', args=[self.order.order_number]))

        self.assertTrue(any(self.order.order_number in line for line in logs.output))

    def test_payment_callback_survives_a_dead_mail_server(self):
        """Друга атомарна ділянка: підтвердження оплати."""
        order = OrderFactory(user=self.user, status=Order.STATUS_PENDING)
        payment = Transaction.objects.create(
            reference='txref-mail-down',
            order=order,
            amount=order.total_amount,
            currency='UAH',
            user=self.user,
            status=Transaction.STATUS_SPENDING,
        )

        with broken_mail():
            response = self.client.get(
                reverse('payments:payment_callback'),
                {
                    'status': 'successful',
                    'tx_ref': payment.reference,
                    'transaction_id': 'MOCK-MAIL-DOWN',
                    'signature': transaction_signature(
                        payment.reference, payment.amount, payment.currency
                    ),
                },
            )

        self.assertEqual(response.status_code, 302)

        order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAID, 'Оплата мала зарахуватись')
        self.assertEqual(payment.status, Transaction.STATUS_COMPLETED)

    def test_working_mail_still_delivers(self):
        """Контрольний: коли пошта жива, лист таки йде."""
        self.client.post(reverse('orders:order_cancel', args=[self.order.order_number]))

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('скасовано', mail.outbox[0].subject.lower())

"""Недоступна пошта не має ламати жоден крок покупки.

Баг: `_send_order_email` викликав `send(fail_silently=False)`
і ловив тільки `BadHeaderError`. У dev backend — console, і це не стріляло,
але на проді будь-який `SMTPException` прилітав у view вже ПІСЛЯ того, як
замовлення створене й склад списаний, і ДО `cart.clear()`. Покупець бачив
500, кошик лишався повним — і оформлював те саме вдруге.
"""

import logging
from smtplib import SMTPException
from unittest import mock

from django.core.mail import EmailMultiAlternatives
from django.urls import reverse

from orders.emails import (
    notify_admins_about_order,
    send_order_cancelled_email,
    send_order_confirmation_email,
    send_order_status_email,
    send_payment_received_email,
)
from orders.models import Order
from testing import ShopTestCase
from testing.factories import ProductFactory


def broken_mail():
    """Підміна відправки, яка завжди падає так, як падає реальний SMTP."""
    return mock.patch.object(
        EmailMultiAlternatives,
        'send',
        side_effect=SMTPException('поштовий сервер недоступний'),
    )


class EmailFailureIsContainedTests(ShopTestCase):
    """Самі функції відправки не пропускають виняток назовні."""

    def test_confirmation_email_failure_returns_false(self):
        order = self.create_order()

        with broken_mail():
            result = send_order_confirmation_email(order)

        self.assertFalse(result)

    def test_confirmation_email_failure_is_logged(self):
        order = self.create_order()

        with broken_mail(), self.assertLogs('orders.emails', level='ERROR') as logs:
            send_order_confirmation_email(order)

        self.assertTrue(any(order.order_number in line for line in logs.output))

    def test_admin_notification_failure_does_not_raise(self):
        order = self.create_order()

        with (
            mock.patch('orders.emails.mail_admins', side_effect=SMTPException('лежить')),
            self.assertLogs('orders.emails', level='ERROR'),
        ):
            self.assertFalse(notify_admins_about_order(order))

    def test_no_email_function_lets_an_exception_out(self):
        """Контракт модуля: жодна функція не піднімає виняток назовні.

        Перевіряються всі чотири, а не лише підтвердження: три з них тепер
        викликаються з колбека `on_commit`, де виняток пішов би не в лог, а в
        код, що завершує транзакцію, — і обвалив би запит, який уже вдався.
        """
        order = self.create_order()
        senders = (
            send_order_confirmation_email,
            send_payment_received_email,
            send_order_status_email,
            send_order_cancelled_email,
        )

        for send in senders:
            with self.subTest(sender=send.__name__), broken_mail():
                self.assertFalse(send(order), 'Функція мала повернути False, а не впасти')

    def test_broken_order_object_does_not_raise_either(self):
        """Навіть якщо ламається не пошта, а сам обʼєкт замовлення.

        `customer_email` читає користувача з бази; у колбеку `on_commit` це
        окремий запит, і він теж має бути прикритий.
        """
        order = self.create_order()

        with mock.patch.object(
            type(order),
            'customer_email',
            new_callable=mock.PropertyMock,
            side_effect=RuntimeError('база відвалилась'),
        ):
            self.assertFalse(send_order_status_email(order))

    def test_missing_recipient_email_is_not_an_error(self):
        order = self.create_order()
        order.user.email = ''
        order.user.save(update_fields=['email'])

        self.assertFalse(send_order_confirmation_email(order))


class CheckoutSurvivesMailOutageTests(ShopTestCase):
    """Головне: покупка доходить до кінця навіть коли пошта лежить."""

    def setUp(self):
        # Логи падінь пошти тут очікувані й перевіряються в іншому класі —
        # у виводі прогону вони тільки заважають читати результат.
        logging.disable(logging.ERROR)
        self.addCleanup(logging.disable, logging.NOTSET)

    def _checkout(self, product, quantity=2):
        user = self.login()
        address = self.create_address(user)

        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': quantity})
        self.client.post(
            reverse('orders:checkout'), {'select_address': '1', 'address_id': address.id}
        )

        return self.client.post(
            reverse('orders:checkout_confirm'),
            self.confirm_payload(),
            follow=True,
        )

    def test_order_is_created_when_mail_is_down(self):
        product = ProductFactory(stock=10)

        with broken_mail():
            response = self._checkout(product)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Order.objects.count(), 1)

    def test_stock_is_still_deducted_when_mail_is_down(self):
        product = ProductFactory(stock=10)

        with broken_mail():
            self._checkout(product, quantity=3)

        self.assertStock(product, 7)

    def test_cart_is_emptied_when_mail_is_down(self):
        product = ProductFactory(stock=10)

        with broken_mail():
            self._checkout(product)

        # Перевіряємо стан кошика, а не текст на сторінці: копія змінюється,
        # а вимога «після замовлення кошик порожній» — ні.
        response = self.client.get(reverse('cart:cart_detail'))
        self.assertEqual(len(response.context['cart']), 0)

    def test_success_page_opens_when_mail_is_down(self):
        product = ProductFactory(stock=10)

        with broken_mail():
            response = self._checkout(product)

        order = Order.objects.get()
        self.assertContains(response, order.order_number)

    def test_user_is_told_the_letter_is_delayed(self):
        product = ProductFactory(stock=10)

        with broken_mail():
            response = self._checkout(product)

        texts = [str(message) for message in response.context['messages']]
        self.assertTrue(
            any('надішлемо' in text for text in texts),
            f'Очікували повідомлення про відкладений лист, отримали: {texts}',
        )

    def test_normal_checkout_still_sends_the_letter(self):
        """Контрольний: коли пошта жива, лист іде і повідомлення звичайне."""
        product = ProductFactory(stock=10)

        response = self._checkout(product)

        texts = [str(message) for message in response.context['messages']]
        self.assertTrue(any('успішно створено' in text for text in texts))

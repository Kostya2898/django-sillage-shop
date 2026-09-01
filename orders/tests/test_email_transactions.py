"""Лист не має йти раніше, ніж транзакція закомічена.

`post_save` спрацьовує **всередині** відкритої транзакції, а не після неї.
Обидва місця, звідки статус міняється автоматично — `cancel_order` і
`_complete_payment` — обгорнуті в `atomic`, тож пряма відправка з сигналу
означала б таке: лист «замовлення скасовано» пішов, склад повернувся, потім
транзакція відкотилась — і в пошті покупця лежить повідомлення про подію,
якої не сталося. Рядок у базі відкотити можна, лист — ні.

Тому відправка загорнута в `transaction.on_commit`, а ці тести стежать за
обома боками угоди: після коміту лист є, після відкоту — немає.
"""

from decimal import Decimal

from django.core import mail
from django.db import IntegrityError, transaction
from django.urls import reverse

from orders.models import Order, OrderStatusHistory
from orders.services import cancel_order
from testing import ShopTestCase
from testing.factories import ProductFactory


class RollbackSendsNothingTests(ShopTestCase):
    """Головна вимога: відкат — і жодного листа."""

    def setUp(self):
        self.order = self.create_order()
        mail.outbox.clear()

    def test_rolled_back_status_change_sends_no_letter(self):
        try:
            with transaction.atomic():
                self.order.status = Order.STATUS_SHIPPED
                self.order.save(update_fields=['status', 'updated_at'])
                raise RuntimeError('щось пішло не так уже після зміни статусу')
        except RuntimeError:
            pass

        self.assertEqual(mail.outbox, [], 'Лист пішов про статус, який відкотився')

    def test_rolled_back_status_change_leaves_no_history(self):
        """Контрольна половина: разом із листом має відкотитись і запис."""
        try:
            with transaction.atomic():
                self.order.status = Order.STATUS_SHIPPED
                self.order.save(update_fields=['status', 'updated_at'])
                raise RuntimeError('відкат')
        except RuntimeError:
            pass

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PENDING)
        self.assertFalse(
            OrderStatusHistory.objects.filter(
                order=self.order, status=Order.STATUS_SHIPPED
            ).exists()
        )

    def test_rolled_back_cancellation_sends_no_letter(self):
        """`cancel_order` сам по собі `atomic` — перевіряємо його у вкладеному."""
        product = ProductFactory(stock=7)
        order = self.create_order(items=[(product, 3)])
        mail.outbox.clear()

        try:
            with transaction.atomic():
                cancel_order(order, note='Скасовано, але транзакція впаде')
                raise RuntimeError('відкат уже після скасування')
        except RuntimeError:
            pass

        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PENDING)
        self.assertStock(product, 7)
        self.assertEqual(mail.outbox, [], 'Лист про скасування, якого не було')

    def test_letter_is_queued_until_the_commit_happens(self):
        """До коміту лист лежить у черзі `on_commit`, а не в пошті."""
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.order.status = Order.STATUS_SHIPPED
            self.order.save(update_fields=['status', 'updated_at'])

            self.assertEqual(mail.outbox, [], 'Лист пішов ще до коміту')

        self.assertEqual(len(callbacks), 1, 'Відправка мала стати відкладеним колбеком')

    def test_committed_status_change_does_send(self):
        """Друга половина угоди: після коміту лист таки йде."""
        with self.commits():
            self.order.status = Order.STATUS_SHIPPED
            self.order.save(update_fields=['status', 'updated_at'])

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.order.order_number, mail.outbox[0].subject)


class ConfirmationLetterIsSentAfterCommitTests(ShopTestCase):
    """Лист-підтвердження шлеться поза `create_order`, і це має лишитись так.

    `create_order` обгорнутий в `atomic`; відправка стоїть у view **після**
    нього, коли транзакція вже закомічена. Тест фіксує саме цю межу: якщо
    хтось перенесе відправку всередину сервісу, впаде перший із тестів.
    """

    def test_create_order_itself_sends_nothing(self):
        from orders.views import create_order

        product = ProductFactory(price=Decimal('1000.00'), stock=5)
        user = self.login()
        address = self.create_address(user)
        # Кошик у базі — його підхопить DatabaseCart нижче за користувачем.
        self.create_cart_with_items(user=user, items=[(product, 2)])

        from cart.cart import DatabaseCart

        class FakeRequest:
            pass

        request = FakeRequest()
        request.user = user
        mail.outbox.clear()

        create_order(
            user=user,
            cart=DatabaseCart(request),
            address=address,
            payment_method='cash',
        )

        self.assertEqual(
            mail.outbox,
            [],
            'create_order працює в транзакції — листи має слати той, хто його викликав',
        )
        self.assertEqual(Order.objects.count(), 1)

    def test_checkout_sends_the_confirmation(self):
        """А через checkout лист приходить — бо транзакція вже закомічена."""
        product = ProductFactory(price=Decimal('1000.00'), stock=5)
        user = self.login()
        address = self.create_address(user)

        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 1})
        self.client.post(
            reverse('orders:checkout'), {'select_address': '1', 'address_id': address.id}
        )
        mail.outbox.clear()
        self.client.post(reverse('orders:checkout_confirm'), self.confirm_payload())

        # Підтвердження покупцю і сповіщення адміністраторам.
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, [user.email])

    def test_failed_order_sends_nothing(self):
        """Товар скінчився → відкат → жодного листа."""
        scarce = ProductFactory(stock=1)
        user = self.login()
        address = self.create_address(user)

        self.client.post(reverse('cart:cart_add', args=[scarce.id]), {'quantity': 1})
        scarce.stock = 0
        scarce.save(update_fields=['stock'])

        self.client.post(
            reverse('orders:checkout'), {'select_address': '1', 'address_id': address.id}
        )
        mail.outbox.clear()
        self.client.post(reverse('orders:checkout_confirm'), self.confirm_payload())

        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(mail.outbox, [])


class DatabaseErrorRollsBackTheLetterTests(ShopTestCase):
    """Не тільки виняток у коді, а й помилка самої бази.

    Найнеприємніший випадок — коли транзакція падає вже після того, як усе
    «спрацювало»: код винятків не кидав, а коміт не пройшов.
    """

    def test_integrity_error_after_status_change_sends_nothing(self):
        order = self.create_order()
        mail.outbox.clear()

        try:
            with transaction.atomic():
                order.status = Order.STATUS_SHIPPED
                order.save(update_fields=['status', 'updated_at'])

                # Номер замовлення унікальний — це гарантована помилка бази.
                duplicate = self.create_order()
                Order.objects.filter(pk=duplicate.pk).update(order_number=order.order_number)
        except IntegrityError:
            pass

        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PENDING)
        self.assertEqual(mail.outbox, [])

"""Зміна статусу: запис в історію і лист покупцю.

Раніше кожен, хто міняв статус (адмінка, оплата, скасування), сам створював
запис в історії й сам вирішував, слати листа чи ні. Тепер це робить сигнал
`record_status_change` — і ці тести стежать, щоб він спрацьовував рівно один
раз на перехід і не дублював те, що роблять інші.
"""

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import mail
from django.test import RequestFactory

from orders.admin import OrderAdmin
from orders.models import Order, OrderStatusHistory
from testing import ShopTestCase
from testing.factories import ProductFactory, UserFactory


class StatusChangeCreatesHistoryTests(ShopTestCase):
    def setUp(self):
        self.order = self.create_order()
        mail.outbox.clear()

    def _history(self):
        return OrderStatusHistory.objects.filter(order=self.order)

    def test_status_change_records_history(self):
        before = self._history().count()

        self.order.status = Order.STATUS_SHIPPED
        self.order.save(update_fields=['status', 'updated_at'])

        self.assertEqual(self._history().count(), before + 1)
        self.assertEqual(self._history().last().status, Order.STATUS_SHIPPED)

    def test_saving_without_changing_status_records_nothing(self):
        before = self._history().count()

        self.order.notes = 'Подзвонити за годину'
        self.order.save(update_fields=['notes', 'updated_at'])

        self.assertEqual(self._history().count(), before)

    def test_note_and_actor_reach_the_history(self):
        staff = UserFactory(is_staff=True)

        self.order.status = Order.STATUS_SHIPPED
        self.order._status_note = 'ТТН 20450123456789'
        self.order._status_actor = staff
        self.order.save(update_fields=['status', 'updated_at'])

        entry = self._history().last()
        self.assertEqual(entry.note, 'ТТН 20450123456789')
        self.assertEqual(entry.created_by, staff)

    def test_note_is_not_inherited_by_the_next_change(self):
        """Одноразові атрибути: чужа примітка не має переїхати на інший перехід."""
        self.order.status = Order.STATUS_SHIPPED
        self.order._status_note = 'ТТН 20450123456789'
        self.order.save(update_fields=['status', 'updated_at'])

        self.order.status = Order.STATUS_DELIVERED
        self.order.save(update_fields=['status', 'updated_at'])

        self.assertNotIn('20450123456789', self._history().last().note)

    def test_creating_an_order_does_not_double_the_first_entry(self):
        """Початковий запис робить `create_order`; сигнал не має його дублювати."""
        order = self.create_order()

        self.assertEqual(OrderStatusHistory.objects.filter(order=order).count(), 1)


class StatusChangeSendsLetterTests(ShopTestCase):
    def setUp(self):
        self.order = self.create_order()
        mail.outbox.clear()

    def move_to(self, status, order=None):
        """Перевести замовлення в статус так, щоб відкладений лист таки пішов.

        Без `commits()` лист лишився б у чергі `on_commit` до кінця тесту:
        саме так і має бути, поки транзакція не закомічена.
        """
        order = order or self.order
        with self.commits():
            order.status = status
            order.save(update_fields=['status', 'updated_at'])
        return order

    def test_letter_is_sent_on_status_change(self):
        self.move_to(Order.STATUS_SHIPPED)

        self.assertEqual(len(mail.outbox), 1)
        letter = mail.outbox[0]
        self.assertEqual(letter.to, [self.order.customer_email])
        self.assertIn(self.order.order_number, letter.subject)
        self.assertIn('відправлено', letter.subject.lower())

    def test_letter_has_both_formats(self):
        """Вимога курсу: текстова версія обовʼязкова, HTML — альтернативою."""
        self.move_to(Order.STATUS_DELIVERED)

        letter = mail.outbox[0]
        self.assertIn('SILLAGE', letter.body)
        self.assertEqual(len(letter.alternatives), 1)
        html, mimetype = letter.alternatives[0]
        self.assertEqual(mimetype, 'text/html')
        self.assertIn('<table', html)

    def test_html_letter_carries_only_inline_css(self):
        """Поштові клієнти вирізають <style> — лист має жити без нього."""
        self.move_to(Order.STATUS_SHIPPED)

        html = mail.outbox[0].alternatives[0][0]
        self.assertNotIn('<style', html)
        self.assertIn('style="', html)

    def test_html_letter_has_no_external_resources(self):
        self.move_to(Order.STATUS_SHIPPED)

        html = mail.outbox[0].alternatives[0][0]
        self.assertNotIn('fonts.googleapis', html)
        self.assertNotIn('<link', html)
        self.assertNotIn('<script', html)

    def test_cancellation_sends_its_own_letter(self):
        with self.commits():
            self.order.cancel(note='Передумав')

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('скасовано', mail.outbox[0].subject.lower())

    def test_payment_sends_the_payment_letter_not_a_generic_one(self):
        self.move_to(Order.STATUS_PAID)

        self.assertEqual(len(mail.outbox), 1, 'Двох листів про одну подію бути не має')
        self.assertIn('Оплату', mail.outbox[0].subject)

    def test_guest_receives_status_letters_too(self):
        order = self.create_order(guest_email='hostia@example.com')
        mail.outbox.clear()

        self.move_to(Order.STATUS_SHIPPED, order=order)

        self.assertEqual(mail.outbox[0].to, ['hostia@example.com'])

    def test_broken_mail_does_not_break_the_status_change(self):
        """Лежача пошта не має відкотити зміну статусу в базі."""
        import logging
        from smtplib import SMTPException
        from unittest import mock

        from django.core.mail import EmailMultiAlternatives

        logging.disable(logging.ERROR)
        self.addCleanup(logging.disable, logging.NOTSET)

        with mock.patch.object(EmailMultiAlternatives, 'send', side_effect=SMTPException('лежить')):
            self.order.status = Order.STATUS_SHIPPED
            self.order.save(update_fields=['status', 'updated_at'])

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_SHIPPED)
        self.assertEqual(
            OrderStatusHistory.objects.filter(
                order=self.order, status=Order.STATUS_SHIPPED
            ).count(),
            1,
        )


class AdminBulkStatusTests(ShopTestCase):
    """Масова зміна статусу з адмінки теж пише історію й шле листи."""

    def setUp(self):
        self.admin = OrderAdmin(Order, AdminSite())
        self.staff = UserFactory(is_staff=True, is_superuser=True)

    def _request(self):
        request = RequestFactory().post('/admin/orders/order/')
        request.user = self.staff
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        return request

    def test_bulk_shipping_writes_history_for_each_order(self):
        orders = [self.create_order() for _ in range(3)]
        mail.outbox.clear()

        with self.commits():
            self.admin.mark_shipped(
                self._request(), Order.objects.filter(pk__in=[o.pk for o in orders])
            )

        for order in orders:
            order.refresh_from_db()
            self.assertEqual(order.status, Order.STATUS_SHIPPED)
            self.assertTrue(
                OrderStatusHistory.objects.filter(
                    order=order, status=Order.STATUS_SHIPPED, created_by=self.staff
                ).exists()
            )

    def test_bulk_shipping_sends_one_letter_per_order(self):
        orders = [self.create_order() for _ in range(3)]
        mail.outbox.clear()

        with self.commits():
            self.admin.mark_shipped(
                self._request(), Order.objects.filter(pk__in=[o.pk for o in orders])
            )

        self.assertEqual(len(mail.outbox), 3)

    def test_orders_already_in_that_status_are_skipped(self):
        already = self.create_order(status=Order.STATUS_SHIPPED)
        mail.outbox.clear()

        with self.commits():
            self.admin.mark_shipped(self._request(), Order.objects.filter(pk=already.pk))

        self.assertEqual(len(mail.outbox), 0)

    def test_bulk_cancel_returns_stock_and_sends_letters(self):
        product = ProductFactory(stock=10)
        order = self.create_order(items=[(product, 3)])
        product.stock = 7
        product.save(update_fields=['stock'])
        mail.outbox.clear()

        with self.commits():
            self.admin.mark_cancelled(self._request(), Order.objects.filter(pk=order.pk))

        self.assertStock(product, 10)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('скасовано', mail.outbox[0].subject.lower())

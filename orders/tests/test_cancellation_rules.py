"""Правила самостійного скасування: тільки `pending` і тільки першу добу.

Повернення складу як таке перевіряє `test_order_cancellation.py` — там про
адмінку й про баг AUDIT #5. Тут — про те, коли покупцю **дозволено** тиснути
кнопку, і що станеться, якщо він спробує тиснути її пізніше.
"""

from datetime import timedelta

from django.core import mail
from django.urls import reverse
from django.utils import timezone

from orders.models import Order
from testing import ShopTestCase
from testing.factories import ProductFactory


def age(order, hours):
    """Зробити замовлення старшим на задану кількість годин.

    `created_at` — `auto_now_add`, тож змінити його звичайним `save()` не можна:
    Django перезапише поле поточним часом. Тому оновлення йде через queryset.
    """
    Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(hours=hours))
    order.refresh_from_db()
    return order


class CancellationWindowTests(ShopTestCase):
    def test_fresh_pending_order_can_be_cancelled(self):
        order = self.create_order()

        self.assertTrue(order.can_be_cancelled())

    def test_order_at_twenty_three_hours_can_still_be_cancelled(self):
        order = age(self.create_order(), hours=23)

        self.assertTrue(order.can_be_cancelled())

    def test_order_after_twenty_five_hours_cannot_be_cancelled(self):
        order = age(self.create_order(), hours=25)

        self.assertFalse(order.can_be_cancelled())

    def test_paid_order_cannot_be_cancelled_by_the_buyer(self):
        order = self.create_order(status=Order.STATUS_PAID)

        self.assertFalse(order.can_be_cancelled())

    def test_shipped_order_cannot_be_cancelled_by_the_buyer(self):
        order = self.create_order(status=Order.STATUS_SHIPPED)

        self.assertFalse(order.can_be_cancelled())

    def test_already_cancelled_order_cannot_be_cancelled_again(self):
        order = self.create_order(status=Order.STATUS_CANCELLED)

        self.assertFalse(order.can_be_cancelled())

    def test_deadline_is_created_at_plus_twenty_four_hours(self):
        order = self.create_order()

        self.assertEqual(order.cancellation_deadline(), order.created_at + timedelta(hours=24))


class CancellationViewTests(ShopTestCase):
    def setUp(self):
        self.product = ProductFactory(stock=10)
        self.user = self.login()
        self.order = self.create_order(user=self.user, items=[(self.product, 3)])
        # Склад уже списаний під час оформлення.
        self.product.stock = 7
        self.product.save(update_fields=['stock'])
        mail.outbox.clear()

    def _cancel(self):
        return self.client.post(reverse('orders:order_cancel', args=[self.order.order_number]))

    def test_cancelling_returns_stock(self):
        self._cancel()

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_CANCELLED)
        self.assertStock(self.product, 10)

    def test_cancelling_sends_the_letter(self):
        with self.commits():
            self._cancel()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('скасовано', mail.outbox[0].subject.lower())

    def test_cancelling_after_twenty_five_hours_is_refused(self):
        age(self.order, hours=25)

        response = self._cancel()

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PENDING)
        self.assertStock(self.product, 7)
        self.assertEqual(response.status_code, 302)

    def test_refusal_explains_what_to_do(self):
        age(self.order, hours=25)

        response = self._cancel()
        messages = [str(m) for m in self.client.get(response['Location']).context['messages']]

        self.assertTrue(any('Напишіть нам' in text for text in messages), messages)

    def test_cancelling_is_post_only(self):
        """Незворотна дія не може висіти на GET-посиланні."""
        response = self.client.get(reverse('orders:order_cancel', args=[self.order.order_number]))

        self.assertEqual(response.status_code, 405)

    def test_stranger_cannot_cancel_someone_elses_order(self):
        theirs = self.create_order()

        response = self.client.post(reverse('orders:order_cancel', args=[theirs.order_number]))

        theirs.refresh_from_db()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(theirs.status, Order.STATUS_PENDING)

    def test_button_is_hidden_when_the_window_has_closed(self):
        age(self.order, hours=25)

        response = self.client.get(reverse('orders:order_detail', args=[self.order.order_number]))

        self.assertNotContains(response, 'Скасувати замовлення')
        self.assertContains(response, 'вже в роботі')

    def test_button_is_shown_inside_the_window(self):
        response = self.client.get(reverse('orders:order_detail', args=[self.order.order_number]))

        self.assertContains(response, 'Скасувати замовлення')


class StockRollbackTests(ShopTestCase):
    """Замовлення або створюється цілком, або не створюється зовсім.

    Найдорожча помилка тут — часткове списання: перший товар зі складу зняли,
    на другому забракло, а транзакція не відкотилась. Каталог після цього
    показує менше, ніж лежить на полиці.
    """

    def test_shortage_creates_no_order_and_changes_no_stock(self):
        plenty = ProductFactory(stock=10, name='Є вдосталь')
        scarce = ProductFactory(stock=1, name='Лишився один')

        user = self.login()
        address = self.create_address(user)

        self.client.post(reverse('cart:cart_add', args=[plenty.id]), {'quantity': 2})
        self.client.post(reverse('cart:cart_add', args=[scarce.id]), {'quantity': 1})

        # Хтось інший забрав останній екземпляр, поки покупець заповнював адресу.
        scarce.stock = 0
        scarce.save(update_fields=['stock'])

        self.client.post(
            reverse('orders:checkout'), {'select_address': '1', 'address_id': address.id}
        )
        self.client.post(reverse('orders:checkout_confirm'), self.confirm_payload())

        self.assertEqual(Order.objects.count(), 0, 'Замовлення не мало створитись')
        self.assertStock(plenty, 10)
        self.assertStock(scarce, 0)

    def test_buyer_is_told_what_went_wrong(self):
        scarce = ProductFactory(stock=1, name='Лишився один')
        user = self.login()
        address = self.create_address(user)

        self.client.post(reverse('cart:cart_add', args=[scarce.id]), {'quantity': 1})
        scarce.stock = 0
        scarce.save(update_fields=['stock'])

        self.client.post(
            reverse('orders:checkout'), {'select_address': '1', 'address_id': address.id}
        )
        response = self.client.post(
            reverse('orders:checkout_confirm'), self.confirm_payload(), follow=True
        )

        texts = [str(m) for m in response.context['messages']]
        self.assertTrue(any('Лишився один' in text for text in texts), texts)

    def test_coupon_is_not_consumed_by_a_failed_order(self):
        """Відкат транзакції має повернути й лічильник промокоду."""
        from testing.factories import CouponFactory

        coupon = CouponFactory(code='OSIN')
        scarce = ProductFactory(stock=1)
        user = self.login()
        address = self.create_address(user)

        self.client.post(reverse('cart:cart_add', args=[scarce.id]), {'quantity': 1})
        self.client.post(reverse('orders:coupon_apply'), {'code': 'OSIN'})
        scarce.stock = 0
        scarce.save(update_fields=['stock'])

        self.client.post(
            reverse('orders:checkout'), {'select_address': '1', 'address_id': address.id}
        )
        self.client.post(reverse('orders:checkout_confirm'), self.confirm_payload())

        coupon.refresh_from_db()
        self.assertEqual(coupon.used_count, 0)

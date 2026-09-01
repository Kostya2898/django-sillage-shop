"""Промокоди: перевірка умов, застосування, лічильник використань.

Головна вимога до відмов — вони мають бути зрозумілі людині. «Промокод
недійсний» змушує набирати той самий код ще раз; «Промокод діяв до 1 серпня»
закриває питання одразу.
"""

from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from orders.models import Coupon, Order
from orders.services import COUPON_SESSION_KEY, apply_coupon, calculate_totals
from testing import ShopTestCase
from testing.factories import CouponFactory, DeliveryMethodFactory, ProductFactory


class CouponValidityTests(ShopTestCase):
    """`is_valid_for` повертає причину відмови, а не просто False."""

    def test_active_coupon_is_valid(self):
        coupon = CouponFactory()

        is_valid, reason = coupon.is_valid_for(Decimal('1000.00'))

        self.assertTrue(is_valid)
        self.assertEqual(reason, '')

    def test_expired_coupon_names_the_date(self):
        coupon = CouponFactory(
            valid_from=timezone.now() - timedelta(days=40),
            valid_to=timezone.make_aware(timezone.datetime(2026, 8, 1, 12, 0)),
        )

        is_valid, reason = coupon.is_valid_for(Decimal('1000.00'))

        self.assertFalse(is_valid)
        self.assertIn('діяв до', reason)
        self.assertIn('серпня', reason)

    def test_future_coupon_says_when_it_starts(self):
        coupon = CouponFactory(
            valid_from=timezone.now() + timedelta(days=3),
            valid_to=timezone.now() + timedelta(days=30),
        )

        is_valid, reason = coupon.is_valid_for(Decimal('1000.00'))

        self.assertFalse(is_valid)
        self.assertIn('почне діяти', reason)

    def test_inactive_coupon_is_rejected(self):
        coupon = CouponFactory(is_active=False)

        is_valid, reason = coupon.is_valid_for(Decimal('1000.00'))

        self.assertFalse(is_valid)
        self.assertIn(coupon.code, reason)

    def test_minimum_amount_names_the_sum(self):
        coupon = CouponFactory(min_order_amount=Decimal('2000.00'))

        is_valid, reason = coupon.is_valid_for(Decimal('1500.00'))

        self.assertFalse(is_valid)
        self.assertEqual(reason, 'Мінімальна сума замовлення — 2000 ₴')

    def test_minimum_amount_is_inclusive(self):
        coupon = CouponFactory(min_order_amount=Decimal('2000.00'))

        is_valid, _ = coupon.is_valid_for(Decimal('2000.00'))

        self.assertTrue(is_valid)

    def test_exhausted_coupon_is_rejected(self):
        coupon = CouponFactory(max_uses=5, used_count=5)

        is_valid, reason = coupon.is_valid_for(Decimal('1000.00'))

        self.assertFalse(is_valid)
        self.assertIn('ліміт', reason)

    def test_zero_max_uses_means_unlimited(self):
        coupon = CouponFactory(max_uses=0, used_count=999)

        is_valid, _ = coupon.is_valid_for(Decimal('1000.00'))

        self.assertTrue(is_valid)


class CouponMathTests(ShopTestCase):
    def test_percent_discount(self):
        coupon = CouponFactory(discount_type=Coupon.TYPE_PERCENT, discount_value=Decimal('10'))

        self.assertEqual(coupon.discount_for(Decimal('4200.00')), Decimal('420.00'))

    def test_fixed_discount(self):
        coupon = CouponFactory(discount_type=Coupon.TYPE_FIXED, discount_value=Decimal('500'))

        self.assertEqual(coupon.discount_for(Decimal('4200.00')), Decimal('500.00'))

    def test_discount_never_exceeds_the_sum(self):
        """Фіксована знижка, більша за кошик, не має робити суму відʼємною."""
        coupon = CouponFactory(discount_type=Coupon.TYPE_FIXED, discount_value=Decimal('9000'))

        self.assertEqual(coupon.discount_for(Decimal('1200.00')), Decimal('1200.00'))

    def test_code_is_stored_uppercase(self):
        """«sillage» і «SILLAGE» — це один промокод, а не два."""
        coupon = CouponFactory(code='  osinnii-slid  ')

        self.assertEqual(coupon.code, 'OSINNII-SLID')

    def test_totals_are_items_minus_discount_plus_delivery(self):
        coupon = CouponFactory(discount_value=Decimal('10'))
        delivery = DeliveryMethodFactory(price=Decimal('80.00'), free_from=None)

        totals = calculate_totals(Decimal('1000.00'), coupon=coupon, delivery=delivery)

        self.assertEqual(totals.items_total, Decimal('1000.00'))
        self.assertEqual(totals.discount, Decimal('100.00'))
        self.assertEqual(totals.delivery, Decimal('80.00'))
        self.assertEqual(totals.total, Decimal('980.00'))


class CouponInSessionTests(ShopTestCase):
    def setUp(self):
        self.product = ProductFactory(price=Decimal('2000.00'), stock=10)
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 1})

    def test_applying_a_coupon_stores_it_in_the_session(self):
        coupon = CouponFactory(code='OSIN')

        self.client.post(
            reverse('orders:coupon_apply'),
            {'code': 'osin', 'next': reverse('orders:checkout_identity')},
        )

        self.assertEqual(self.client.session.get(COUPON_SESSION_KEY), coupon.pk)

    def test_unknown_code_is_reported(self):
        response = self.client.post(
            reverse('orders:coupon_apply'),
            {'code': 'NEMAJE', 'next': reverse('orders:checkout_identity')},
            follow=True,
        )

        texts = [str(m) for m in response.context['messages']]
        self.assertTrue(any('не знайдено' in text for text in texts), texts)

    def test_removing_a_coupon_clears_the_session(self):
        CouponFactory(code='OSIN')
        self.client.post(reverse('orders:coupon_apply'), {'code': 'OSIN'})

        self.client.post(reverse('orders:coupon_remove'))

        self.assertIsNone(self.client.session.get(COUPON_SESSION_KEY))

    def test_coupon_deactivated_mid_checkout_is_forgotten(self):
        """Показувати знижку, якої вже немає, гірше, ніж не показувати жодної."""
        coupon = CouponFactory(code='OSIN')
        self.client.post(reverse('orders:coupon_apply'), {'code': 'OSIN'})

        coupon.is_active = False
        coupon.save(update_fields=['is_active'])

        response = self.client.get(reverse('orders:checkout_identity'))
        self.assertIsNone(response.context['coupon'])
        self.assertEqual(response.context['totals'].discount, Decimal('0.00'))


class CouponOnOrderTests(ShopTestCase):
    """Купон доходить до замовлення й списує використання."""

    def setUp(self):
        self.product = ProductFactory(price=Decimal('2000.00'), stock=10)
        self.coupon = CouponFactory(code='OSIN', discount_value=Decimal('10'), max_uses=3)

    def _checkout_with_coupon(self, code='OSIN'):
        user = self.login()
        address = self.create_address(user)

        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 2})
        if code:
            self.client.post(reverse('orders:coupon_apply'), {'code': code})
        self.client.post(
            reverse('orders:checkout'), {'select_address': '1', 'address_id': address.id}
        )
        self.client.post(reverse('orders:checkout_confirm'), self.confirm_payload())
        return Order.objects.get()

    def test_order_stores_the_discount(self):
        order = self._checkout_with_coupon()

        self.assertEqual(order.items_total, Decimal('4000.00'))
        self.assertEqual(order.discount_amount, Decimal('400.00'))
        self.assertEqual(order.coupon, self.coupon)
        self.assertEqual(order.coupon_code, 'OSIN')

    def test_total_includes_discount_and_delivery(self):
        order = self._checkout_with_coupon()

        expected = order.items_total - order.discount_amount + order.delivery_price
        self.assertEqual(order.total_amount, expected)

    def test_used_count_grows(self):
        self._checkout_with_coupon()

        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.used_count, 1)

    def test_used_count_does_not_grow_without_a_coupon(self):
        self._checkout_with_coupon(code=None)

        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.used_count, 0)

    def test_coupon_code_survives_deleting_the_coupon(self):
        """Знімок коду лишається в замовленні, навіть коли купон прибрали."""
        order = self._checkout_with_coupon()

        self.coupon.delete()

        order.refresh_from_db()
        self.assertIsNone(order.coupon)
        self.assertEqual(order.coupon_code, 'OSIN')

    def test_exhausted_coupon_does_not_reach_the_order(self):
        self.coupon.used_count = self.coupon.max_uses
        self.coupon.save(update_fields=['used_count'])

        order = self._checkout_with_coupon()

        self.assertEqual(order.discount_amount, Decimal('0.00'))
        self.assertEqual(order.coupon_code, '')

    def test_discount_appears_in_the_letter(self):
        from django.core import mail

        self._checkout_with_coupon()

        body = mail.outbox[0].body
        self.assertIn('OSIN', body)
        self.assertIn('Знижка', body)

    def test_coupon_is_not_reused_by_the_next_order(self):
        """Забутий у сесії промокод застосувався б мовчки й без відома покупця."""
        self._checkout_with_coupon()

        self.assertIsNone(self.client.session.get(COUPON_SESSION_KEY))

    def test_apply_returns_reason_when_invalid(self):
        request = self.client.request().wsgi_request
        request.session = self.client.session
        coupon = CouponFactory(min_order_amount=Decimal('5000.00'))

        result, error = apply_coupon(request, coupon.code, Decimal('1000.00'))

        self.assertIsNone(result)
        self.assertIn('Мінімальна сума', error)

"""Вартість доставки, поріг безкоштовності та знімок у замовленні."""

from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from orders.models import Order
from orders.services import calculate_totals
from testing import ShopTestCase
from testing.factories import CouponFactory, DeliveryMethodFactory, ProductFactory


class DeliveryPriceTests(ShopTestCase):
    def test_price_is_charged_below_the_threshold(self):
        method = DeliveryMethodFactory(price=Decimal('80.00'), free_from=Decimal('2500.00'))

        self.assertEqual(method.price_for(Decimal('2000.00')), Decimal('80.00'))

    def test_delivery_is_free_at_the_threshold(self):
        method = DeliveryMethodFactory(price=Decimal('80.00'), free_from=Decimal('2500.00'))

        self.assertEqual(method.price_for(Decimal('2500.00')), Decimal('0.00'))
        self.assertTrue(method.is_free_for(Decimal('2500.00')))

    def test_without_a_threshold_delivery_is_always_paid(self):
        method = DeliveryMethodFactory(price=Decimal('130.00'), free_from=None)

        self.assertEqual(method.price_for(Decimal('99999.00')), Decimal('130.00'))

    def test_missing_for_free_helps_the_upsell(self):
        method = DeliveryMethodFactory(price=Decimal('80.00'), free_from=Decimal('2500.00'))

        self.assertEqual(method.missing_for_free(Decimal('2200.00')), Decimal('300.00'))
        self.assertIsNone(method.missing_for_free(Decimal('2500.00')))

    def test_estimated_date_counts_from_today(self):
        method = DeliveryMethodFactory(estimated_days=3)

        self.assertEqual(method.estimated_date(), timezone.localdate() + timedelta(days=3))


class FreeShippingIsMeasuredAfterDiscountTests(ShopTestCase):
    """Поріг звіряється з сумою, яку покупець справді платить за товар.

    Інакше стовідсотковий промокод давав би безкоштовну доставку нульового
    замовлення — магазин возив би коробки задарма.
    """

    def test_discount_can_drop_the_order_below_the_threshold(self):
        coupon = CouponFactory(discount_value=Decimal('20'))
        method = DeliveryMethodFactory(price=Decimal('80.00'), free_from=Decimal('2500.00'))

        totals = calculate_totals(Decimal('2600.00'), coupon=coupon, delivery=method)

        self.assertEqual(totals.discount, Decimal('520.00'))
        self.assertEqual(totals.delivery, Decimal('80.00'))
        self.assertEqual(totals.total, Decimal('2160.00'))

    def test_without_a_coupon_the_threshold_works_as_expected(self):
        method = DeliveryMethodFactory(price=Decimal('80.00'), free_from=Decimal('2500.00'))

        totals = calculate_totals(Decimal('2600.00'), delivery=method)

        self.assertEqual(totals.delivery, Decimal('0.00'))
        self.assertEqual(totals.total, Decimal('2600.00'))


class DeliverySnapshotTests(ShopTestCase):
    """Тариф може змінитись завтра — замовлення має лишитись тим самим."""

    def setUp(self):
        self.product = ProductFactory(price=Decimal('1000.00'), stock=10)
        self.method = DeliveryMethodFactory(
            name='Курʼєр по місту', price=Decimal('120.00'), free_from=None, estimated_days=2
        )

    def _order(self):
        user = self.login()
        address = self.create_address(user)
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 1})
        self.client.post(
            reverse('orders:checkout'), {'select_address': '1', 'address_id': address.id}
        )
        self.client.post(
            reverse('orders:checkout_confirm'),
            self.confirm_payload(delivery_method=self.method.pk),
        )
        return Order.objects.get()

    def test_name_and_price_are_snapshotted(self):
        order = self._order()

        self.assertEqual(order.delivery_method, self.method)
        self.assertEqual(order.delivery_name, 'Курʼєр по місту')
        self.assertEqual(order.delivery_price, Decimal('120.00'))

    def test_raising_the_tariff_does_not_change_past_orders(self):
        order = self._order()

        self.method.price = Decimal('300.00')
        self.method.name = 'Курʼєр по місту (новий тариф)'
        self.method.save(update_fields=['price', 'name'])

        order.refresh_from_db()
        self.assertEqual(order.delivery_price, Decimal('120.00'))
        self.assertEqual(order.delivery_name, 'Курʼєр по місту')

    def test_total_includes_delivery(self):
        order = self._order()

        self.assertEqual(order.items_total, Decimal('1000.00'))
        self.assertEqual(order.total_amount, Decimal('1120.00'))

    def test_estimated_delivery_date_is_set(self):
        order = self._order()

        self.assertEqual(order.estimated_delivery_date, timezone.localdate() + timedelta(days=2))

    def test_deleting_the_method_keeps_the_snapshot(self):
        order = self._order()

        self.method.delete()

        order.refresh_from_db()
        self.assertIsNone(order.delivery_method)
        self.assertEqual(order.delivery_name, 'Курʼєр по місту')
        self.assertEqual(order.delivery_price, Decimal('120.00'))

    def test_delivery_choice_is_required(self):
        """Мовчки нарахувати доставку, якої покупець не бачив, не можна."""
        user = self.login()
        address = self.create_address(user)
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 1})
        self.client.post(
            reverse('orders:checkout'), {'select_address': '1', 'address_id': address.id}
        )

        response = self.client.post(
            reverse('orders:checkout_confirm'),
            {'payment_method': 'cash', 'notes': '', 'agree_terms': 'on'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Order.objects.count(), 0)
        self.assertIn('delivery_method', response.context['form'].errors)

    def test_inactive_method_is_not_offered(self):
        self.method.is_active = False
        self.method.save(update_fields=['is_active'])

        user = self.login()
        address = self.create_address(user)
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 1})
        self.client.post(
            reverse('orders:checkout'), {'select_address': '1', 'address_id': address.id}
        )
        response = self.client.get(reverse('orders:checkout_confirm'))

        offered = list(response.context['delivery_methods'])
        self.assertNotIn(self.method, offered)

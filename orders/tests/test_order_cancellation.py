"""Скасування замовлення має повертати товар на склад — рівно один раз.

Баг: `orders/admin.py` міняв лише статус, а склад, списаний
при створенні замовлення (`orders/views.py`), не повертався ніколи. Після
кількох скасувань каталог показував менше, ніж є фізично, аж до «немає
в наявності» на повній полиці.

Тести навмисно йдуть через admin-екшен, а не через сервіс: саме там баг
і живе, і саме цим шляхом користується адміністратор.
"""

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from orders.admin import OrderAdmin
from orders.models import Order, OrderStatusHistory
from testing import ShopTestCase
from testing.factories import ProductFactory, UserFactory


class OrderCancellationTests(ShopTestCase):
    def setUp(self):
        self.admin = OrderAdmin(Order, AdminSite())
        self.staff = UserFactory(is_staff=True, is_superuser=True)

    def _request(self):
        """Запит із підключеними повідомленнями — їх пише message_user."""
        request = RequestFactory().post('/admin/orders/order/')
        request.user = self.staff
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        return request

    def _cancel(self, order):
        queryset = Order.objects.filter(pk=order.pk)
        self.admin.mark_cancelled(self._request(), queryset)

    def test_cancellation_returns_stock(self):
        # Товару було 10, замовлення на 3 — склад уже списаний до 7.
        product = ProductFactory(stock=10)
        order = self.create_order(items=[(product, 3)])
        product.stock = 7
        product.save(update_fields=['stock'])

        self._cancel(order)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_CANCELLED)
        self.assertStock(product, 10)

    def test_cancellation_returns_stock_exactly_once(self):
        """Повторне скасування вже скасованого замовлення нічого не додає."""
        product = ProductFactory(stock=10)
        order = self.create_order(items=[(product, 3)])
        product.stock = 7
        product.save(update_fields=['stock'])

        self._cancel(order)
        self.assertStock(product, 10)

        self._cancel(order)
        self.assertStock(product, 10)

        self._cancel(order)
        self.assertStock(product, 10)

    def test_cancellation_returns_stock_for_every_item(self):
        first = ProductFactory(stock=2)
        second = ProductFactory(stock=0)
        order = self.create_order(items=[(first, 3), (second, 5)])

        self._cancel(order)

        self.assertStock(first, 5)
        self.assertStock(second, 5)

    def test_cancellation_writes_status_history(self):
        product = ProductFactory(stock=7)
        order = self.create_order(items=[(product, 3)])

        self._cancel(order)

        history = OrderStatusHistory.objects.filter(order=order, status=Order.STATUS_CANCELLED)
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().created_by, self.staff)

    def test_repeated_cancellation_does_not_duplicate_history(self):
        product = ProductFactory(stock=7)
        order = self.create_order(items=[(product, 3)])

        self._cancel(order)
        self._cancel(order)

        self.assertEqual(
            OrderStatusHistory.objects.filter(order=order, status=Order.STATUS_CANCELLED).count(),
            1,
        )

    def test_other_status_changes_do_not_touch_stock(self):
        """Відправлення й доставка складу не чіпають — товар уже поїхав."""
        product = ProductFactory(stock=7)
        order = self.create_order(items=[(product, 3)])

        self.admin.mark_shipped(self._request(), Order.objects.filter(pk=order.pk))
        self.assertStock(product, 7)

        self.admin.mark_delivered(self._request(), Order.objects.filter(pk=order.pk))
        self.assertStock(product, 7)

    def test_deleted_product_does_not_break_cancellation(self):
        """OrderItem.product — SET_NULL: товар могли прибрати з каталогу."""
        product = ProductFactory(stock=7)
        order = self.create_order(items=[(product, 3)])
        order.items.update(product=None)

        self._cancel(order)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_CANCELLED)

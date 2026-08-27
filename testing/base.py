"""Базовий TestCase з хелперами, які потрібні майже кожному тесту покупки."""

from decimal import Decimal

from django.test import TestCase

from orders.models import Order, OrderItem, OrderStatusHistory

from .factories import (
    DEFAULT_PASSWORD,
    CartFactory,
    CartItemFactory,
    OrderFactory,
    OrderItemFactory,
    ProductFactory,
    ShippingAddressFactory,
    UserFactory,
)


class ShopTestCase(TestCase):
    """Спільні дії: залогінити користувача, зібрати кошик, зібрати замовлення."""

    def login(self, user=None, password=DEFAULT_PASSWORD):
        """Створити (за потреби) користувача й залогінити тест-клієнт."""
        user = user or UserFactory()
        logged_in = self.client.login(username=user.username, password=password)
        self.assertTrue(logged_in, 'Не вдалося залогінити тестового користувача')
        return user

    def create_cart_with_items(self, user=None, items=None, paid_status=False):
        """Кошик у базі з позиціями.

        `items` — послідовність `(product, quantity)`. Якщо не передати нічого,
        створюється один товар кількістю 1.
        """
        cart = CartFactory(user=user or UserFactory(), paid_status=paid_status)

        if items is None:
            items = [(ProductFactory(), 1)]

        for product, quantity in items:
            CartItemFactory(cart=cart, product=product, quantity=quantity)

        return cart

    def create_order(self, user=None, items=None, status=Order.STATUS_PENDING, **kwargs):
        """Замовлення з позиціями і початковим записом в історії статусів.

        `items` — послідовність `(product, quantity)`. Склад **не** списується:
        тести, яким це важливо, або йдуть через `create_order` з `orders.services`,
        або виставляють `stock` руками.
        """
        user = user or UserFactory()

        if items is None:
            items = [(ProductFactory(), 1)]

        total = sum(
            (product.price * quantity for product, quantity in items),
            Decimal('0.00'),
        )
        order = OrderFactory(user=user, status=status, total_amount=total, **kwargs)

        for product, quantity in items:
            OrderItemFactory(
                order=order,
                product=product,
                product_name=product.name,
                price=product.price,
                quantity=quantity,
            )

        OrderStatusHistory.objects.create(order=order, status=status, created_by=user)
        return order

    def create_address(self, user):
        """Адреса доставки для checkout-сценаріїв."""
        return ShippingAddressFactory(user=user)

    def assertStock(self, product, expected):
        """Перезчитати товар із бази і перевірити залишок.

        Окремий хелпер, бо склад майже завжди змінюється через `F()` —
        обʼєкт у памʼяті тесту після цього застарілий.
        """
        product.refresh_from_db()
        self.assertEqual(
            product.stock,
            expected,
            f'Залишок «{product.name}»: очікували {expected}, у базі {product.stock}',
        )

    def assertOrderItems(self, order, expected_count):
        self.assertEqual(OrderItem.objects.filter(order=order).count(), expected_count)

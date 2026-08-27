"""Кількість треба звіряти зі складом як «скільки стане в кошику», а не «скільки просять».

Баг з AUDIT.md #7: `_clamp_quantity` порівнювала зі складом лише щойно надіслану
кількість. На складі 6, покупець двічі тисне «додати 5» — обидва рази проходить,
у кошику 10. Помилка вилазила аж на checkout як ValueError і викидала користувача
назад у кошик — найгірший момент, щоб дізнатися про брак товару.

Обидва типи кошика перевіряються окремо: у гостя SessionCart, у залогіненого
DatabaseCart, і поводитись вони мають однаково.
"""

from django.urls import reverse

from cart.cart import get_cart
from cart.views import MAX_QUANTITY_PER_PRODUCT
from testing import ShopTestCase
from testing.factories import ProductFactory


class CartQuantityValidationMixin:
    """Сценарії, однакові для гостя й залогіненого покупця."""

    def setup_buyer(self):
        raise NotImplementedError

    def setUp(self):
        self.setup_buyer()

    def add(self, product, quantity):
        return self.client.post(
            reverse('cart:cart_add', args=[product.id]), {'quantity': quantity}, follow=True
        )

    def update(self, product, quantity):
        return self.client.post(
            reverse('cart:cart_update', args=[product.id]), {'quantity': quantity}, follow=True
        )

    def cart_quantity(self, product):
        response = self.client.get(reverse('cart:cart_detail'))
        cart = response.context['cart']
        for item in cart:
            if item['product'].pk == product.pk:
                return item['quantity']
        return 0

    def message_texts(self, response):
        return [str(message) for message in response.context['messages']]

    # --- сам баг --------------------------------------------------------

    def test_second_add_over_stock_is_rejected(self):
        product = ProductFactory(stock=6)

        self.add(product, 5)
        response = self.add(product, 5)

        self.assertEqual(self.cart_quantity(product), 5, 'Друге додавання не мало пройти')
        self.assertTrue(
            any('6' in text for text in self.message_texts(response)),
            f'Очікували повідомлення про залишок, отримали: {self.message_texts(response)}',
        )

    def test_message_says_how_much_can_still_be_added(self):
        """Помилка має вести до дії, а не просто констатувати відмову."""
        product = ProductFactory(stock=6, name='Кедрова тиша')

        self.add(product, 5)
        response = self.add(product, 5)

        joined = ' '.join(self.message_texts(response))
        self.assertIn('Кедрова тиша', joined)
        self.assertIn('ще 1', joined)

    def test_adding_exactly_up_to_stock_is_allowed(self):
        product = ProductFactory(stock=6)

        self.add(product, 4)
        self.add(product, 2)

        self.assertEqual(self.cart_quantity(product), 6)

    def test_first_add_over_stock_is_still_rejected(self):
        product = ProductFactory(stock=3)

        self.add(product, 5)

        self.assertEqual(self.cart_quantity(product), 0)

    # --- оновлення кількості --------------------------------------------

    def test_update_over_stock_is_rejected(self):
        product = ProductFactory(stock=6)
        self.add(product, 2)

        self.update(product, 9)

        self.assertEqual(self.cart_quantity(product), 2)

    def test_update_is_absolute_not_cumulative(self):
        """«Оновити 6» при 5 у кошику — це рівно 6, а не 11."""
        product = ProductFactory(stock=6)
        self.add(product, 5)

        self.update(product, 6)

        self.assertEqual(self.cart_quantity(product), 6)

    def test_update_to_zero_removes_item(self):
        product = ProductFactory(stock=6)
        self.add(product, 2)

        self.update(product, 0)

        self.assertEqual(self.cart_quantity(product), 0)

    # --- межа в 99 штук --------------------------------------------------

    def test_cumulative_limit_of_99_is_enforced(self):
        product = ProductFactory(stock=500)

        self.add(product, 60)
        self.add(product, 60)

        self.assertEqual(self.cart_quantity(product), 60)

    def test_can_fill_up_to_99(self):
        product = ProductFactory(stock=500)

        self.add(product, 60)
        self.add(product, MAX_QUANTITY_PER_PRODUCT - 60)

        self.assertEqual(self.cart_quantity(product), MAX_QUANTITY_PER_PRODUCT)

    # --- інтерфейс кошиків ------------------------------------------------

    def test_get_quantity_is_available_on_both_cart_types(self):
        """Правило проєкту: новий метод зʼявляється в обох класах одночасно."""
        product = ProductFactory(stock=6)
        self.add(product, 3)

        request = self.client.get(reverse('cart:cart_detail')).wsgi_request
        self.assertEqual(get_cart(request).get_quantity(product), 3)

    def test_get_quantity_is_zero_for_absent_product(self):
        request = self.client.get(reverse('cart:cart_detail')).wsgi_request

        self.assertEqual(get_cart(request).get_quantity(ProductFactory()), 0)


class GuestCartQuantityTests(CartQuantityValidationMixin, ShopTestCase):
    """Гість — SessionCart."""

    def setup_buyer(self):
        pass


class AuthenticatedCartQuantityTests(CartQuantityValidationMixin, ShopTestCase):
    """Залогінений покупець — DatabaseCart."""

    def setup_buyer(self):
        self.login()

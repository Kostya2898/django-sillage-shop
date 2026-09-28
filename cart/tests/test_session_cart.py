"""Дрібні борги кошика, які легко перетворюються на справжні баги."""

from django.urls import reverse

from cart.cart import SessionCart
from testing import ShopTestCase
from testing.factories import ProductFactory


class SessionCartClearTests(ShopTestCase):
    """Після clear() кошик відвʼязувався від сесії.

    `clear()` робив `session.pop(...)`, а потім клав у `self.cart` новий dict,
    якого в сесії немає. Наступний `add()` на тому самому обʼєкті писав у нікуди.
    Сьогодні це не стріляло лише тому, що після clear() кошик більше не чіпали —
    тобто міна, а не баг. Тест фіксує правильну поведінку.
    """

    def test_add_after_clear_is_persisted(self):
        product = ProductFactory(stock=5)
        request = self.client.get(reverse('cart:cart_detail')).wsgi_request
        cart = SessionCart(request)
        cart.add(product, quantity=2)

        cart.clear()
        cart.add(product, quantity=3)

        self.assertEqual(cart.get_quantity(product), 3)
        # І головне — воно справді лежить у сесії, а не в осиротілому словнику.
        self.assertEqual(SessionCart(request).get_quantity(product), 3)

    def test_clear_empties_the_cart(self):
        product = ProductFactory(stock=5)
        request = self.client.get(reverse('cart:cart_detail')).wsgi_request
        cart = SessionCart(request)
        cart.add(product, quantity=2)

        cart.clear()

        self.assertEqual(len(cart), 0)
        self.assertEqual(SessionCart(request).get_quantity(product), 0)

    def test_clear_through_the_view_survives_next_add(self):
        product = ProductFactory(stock=5)
        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 2})

        self.client.post(reverse('cart:cart_clear'))
        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 3})

        response = self.client.get(reverse('cart:cart_detail'))
        self.assertEqual(len(response.context['cart']), 3)


class AnonymousVisitorCostsNothingTests(ShopTestCase):
    """Перегляд сторінки не має створювати сесію анонімові.

    Раніше `SessionCart.__init__` писав ключ у сесію, а конструктор викликає
    context processor на кожному рендері. Наслідок: кожен випадковий
    відвідувач отримував cookie і рядок у django_session уже на головній —
    чотири зайві запити на показ і неможливість кешувати сторінку.
    """

    def test_browsing_does_not_create_a_session(self):
        from django.contrib.sessions.models import Session

        ProductFactory()

        self.client.get(reverse('shop:home'))
        self.client.get(reverse('shop:product_list'))

        self.assertEqual(Session.objects.count(), 0)

    def test_browsing_sets_no_cookie(self):
        response = self.client.get(reverse('shop:product_list'))

        self.assertNotIn('sessionid', response.cookies)

    def test_adding_to_cart_does_create_a_session(self):
        """А от коли щось поклали — сесія має зʼявитись."""
        from django.contrib.sessions.models import Session

        product = ProductFactory(stock=5)

        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 1})

        self.assertEqual(Session.objects.count(), 1)

    def test_cart_survives_between_requests(self):
        product = ProductFactory(stock=5)

        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 2})
        response = self.client.get(reverse('cart:cart_detail'))

        self.assertEqual(len(response.context['cart']), 2)

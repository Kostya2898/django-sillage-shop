"""JSON API кошика і ліниве створення.

Ключова ідея, яку тут перевіряють: JSON — це прогресивне покращення, а не
другий магазин. Ті самі URL, та сама валідація, той самий результат; різниця
лише у форматі відповіді.
"""

from decimal import Decimal

from django.contrib.sessions.models import Session
from django.test import override_settings
from django.urls import reverse

from cart.models import Cart, CartItem
from cart.services import NBSP, format_price
from testing import ShopTestCase
from testing.factories import DEFAULT_PASSWORD, ProductFactory, UserFactory

AJAX = {'headers': {'X-Requested-With': 'XMLHttpRequest'}}


class JsonNegotiationTests(ShopTestCase):
    """Формат відповіді обирає клієнт, а не сервер."""

    def setUp(self):
        self.product = ProductFactory(stock=10)
        self.url = reverse('cart:cart_add', args=[self.product.id])

    def test_plain_post_still_redirects(self):
        """Без JavaScript магазин працює як раніше."""
        response = self.client.post(self.url, {'quantity': 1})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('cart:cart_detail'))

    def test_xhr_header_returns_json(self):
        response = self.client.post(self.url, {'quantity': 1}, **AJAX)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_accept_header_returns_json(self):
        response = self.client.post(
            self.url, {'quantity': 1}, headers={'Accept': 'application/json'}
        )

        self.assertEqual(response['Content-Type'], 'application/json')

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_unknown_product_is_404(self):
        response = self.client.post(reverse('cart:cart_add', args=[999999]), {}, **AJAX)

        self.assertEqual(response.status_code, 404)


class AddPayloadTests(ShopTestCase):
    def setUp(self):
        self.product = ProductFactory(name='Кедрова тиша', price=Decimal('4200.00'), stock=10)

    def add(self, quantity=1):
        return self.client.post(
            reverse('cart:cart_add', args=[self.product.id]), {'quantity': quantity}, **AJAX
        ).json()

    def test_payload_has_every_documented_field(self):
        payload = self.add()

        for key in ('ok', 'count', 'total_display', 'item', 'cart_html', 'message'):
            with self.subTest(key=key):
                self.assertIn(key, payload)

    def test_count_and_total_reflect_the_cart(self):
        payload = self.add(quantity=2)

        self.assertTrue(payload['ok'])
        self.assertEqual(payload['count'], 2)
        self.assertEqual(payload['total_display'], f'8{NBSP}400{NBSP}₴')

    def test_item_carries_what_the_animation_needs(self):
        """Анімація «полетів у кошик» не має робити другого запиту."""
        item = self.add()['item']

        for key in ('id', 'name', 'brand', 'url', 'image', 'quantity', 'total_display'):
            with self.subTest(key=key):
                self.assertIn(key, item)
        self.assertEqual(item['name'], 'Кедрова тиша')

    def test_cart_html_is_the_drawer_fragment(self):
        payload = self.add()

        self.assertIn('cart-drawer', payload['cart_html'])
        self.assertIn('Кедрова тиша', payload['cart_html'])
        # Саме фрагмент, без шапки й <html>.
        self.assertNotIn('<html', payload['cart_html'])

    def test_message_is_human(self):
        self.assertIn('Кедрова тиша', self.add()['message'])


class BusinessErrorsTests(ShopTestCase):
    """Брак товару — очікуваний стан системи, а не збій: статус лишається 200."""

    def test_over_stock_is_rejected_with_ok_false(self):
        product = ProductFactory(stock=2)

        response = self.client.post(
            reverse('cart:cart_add', args=[product.id]), {'quantity': 5}, **AJAX
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload['ok'])
        self.assertIn('2', payload['error'])

    def test_second_add_over_stock_is_rejected(self):
        product = ProductFactory(stock=6)
        url = reverse('cart:cart_add', args=[product.id])

        self.client.post(url, {'quantity': 5}, **AJAX)
        payload = self.client.post(url, {'quantity': 5}, **AJAX).json()

        self.assertFalse(payload['ok'])

    def test_unavailable_product_is_rejected(self):
        product = ProductFactory(stock=5, is_available=False)

        payload = self.client.post(
            reverse('cart:cart_add', args=[product.id]), {'quantity': 1}, **AJAX
        ).json()

        self.assertFalse(payload['ok'])

    @override_settings(CART_MAX_QUANTITY_PER_PRODUCT=99)
    def test_limit_of_ninety_nine_is_enforced(self):
        product = ProductFactory(stock=500)

        payload = self.client.post(
            reverse('cart:cart_add', args=[product.id]), {'quantity': 100}, **AJAX
        ).json()

        self.assertFalse(payload['ok'])
        self.assertIn('99', payload['error'])

    def test_error_payload_has_no_cart_fields(self):
        product = ProductFactory(stock=1)

        payload = self.client.post(
            reverse('cart:cart_add', args=[product.id]), {'quantity': 9}, **AJAX
        ).json()

        self.assertEqual(set(payload), {'ok', 'error'})


class UpdateRemoveClearTests(ShopTestCase):
    def setUp(self):
        self.product = ProductFactory(price=Decimal('1000.00'), stock=10)
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 3}, **AJAX)

    def test_update_sets_absolute_quantity(self):
        payload = self.client.post(
            reverse('cart:cart_update', args=[self.product.id]), {'quantity': 5}, **AJAX
        ).json()

        self.assertEqual(payload['count'], 5)
        self.assertEqual(payload['item']['quantity'], 5)

    def test_update_to_zero_removes_the_item(self):
        payload = self.client.post(
            reverse('cart:cart_update', args=[self.product.id]), {'quantity': 0}, **AJAX
        ).json()

        self.assertEqual(payload['count'], 0)
        self.assertIsNone(payload['item'])

    def test_remove_empties_the_cart(self):
        payload = self.client.post(
            reverse('cart:cart_remove', args=[self.product.id]), {}, **AJAX
        ).json()

        self.assertEqual(payload['count'], 0)
        self.assertEqual(payload['total_display'], f'0{NBSP}₴')

    def test_clear_empties_the_cart(self):
        payload = self.client.post(reverse('cart:cart_clear'), {}, **AJAX).json()

        self.assertTrue(payload['ok'])
        self.assertEqual(payload['count'], 0)

    def test_empty_drawer_offers_a_way_out(self):
        payload = self.client.post(reverse('cart:cart_clear'), {}, **AJAX).json()

        self.assertIn('порожньо', payload['cart_html'])
        self.assertIn('До каталогу', payload['cart_html'])


class LazyCartTests(ShopTestCase):
    """Читання кошика не має створювати рядків ані в базі, ані в сесії."""

    def test_authenticated_browsing_creates_no_cart_row(self):
        user = self.login()
        ProductFactory()

        self.client.get(reverse('shop:home'))
        self.client.get(reverse('shop:product_list'))

        self.assertEqual(Cart.objects.filter(user=user).count(), 0)

    def test_adding_creates_the_cart_row(self):
        user = self.login()
        product = ProductFactory(stock=5)

        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 1})

        self.assertEqual(Cart.objects.filter(user=user, paid_status=False).count(), 1)

    def test_anonymous_browsing_creates_no_session(self):
        ProductFactory()

        self.client.get(reverse('shop:product_list'))

        self.assertEqual(Session.objects.count(), 0)

    def test_admin_pages_do_not_touch_the_cart(self):
        """Кошик в адмінці не потрібен взагалі — і не має її сповільнювати."""
        staff = UserFactory(is_staff=True, is_superuser=True)
        self.client.force_login(staff)

        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('cart', response.context[-1])
        self.assertEqual(Cart.objects.count(), 0)

    def test_counter_costs_one_query_for_a_full_cart(self):
        user = self.login()
        product = ProductFactory(stock=5)
        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 2})

        from cart.cart import DatabaseCart

        class FakeRequest:
            pass

        request = FakeRequest()
        request.user = user
        cart = DatabaseCart(request)
        # Прогріваємо читання самого рядка кошика, щоб заміряти саме лічильник.
        assert cart.cart is not None

        with self.assertNumQueries(1):
            self.assertEqual(cart.count(), 2)


class MergeOnLoginTests(ShopTestCase):
    """Гостьовий кошик зливається з базовим і не дублює позиції."""

    def test_guest_cart_moves_into_the_database(self):
        product = ProductFactory(stock=10)
        user = UserFactory()

        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 2})
        self.client.post(
            reverse('accounts:login'),
            {'username': user.username, 'password': DEFAULT_PASSWORD},
        )

        item = CartItem.objects.get(cart__user=user, product=product)
        self.assertEqual(item.quantity, 2)

    def test_merge_adds_to_an_existing_row_instead_of_duplicating(self):
        product = ProductFactory(stock=10)
        user = UserFactory()

        # Спершу користувач набирає кошик залогіненим...
        self.client.force_login(user)
        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 1})
        self.client.logout()

        # ...потім, уже гостем, кладе той самий товар і заходить знову.
        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 2})
        self.client.post(
            reverse('accounts:login'),
            {'username': user.username, 'password': DEFAULT_PASSWORD},
        )

        items = CartItem.objects.filter(cart__user=user, product=product)
        self.assertEqual(items.count(), 1, 'позиція не має дублюватись')
        self.assertEqual(items.get().quantity, 3)

    def test_merge_leaves_one_unpaid_cart(self):
        product = ProductFactory(stock=10)
        user = UserFactory()

        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 1})
        self.client.post(
            reverse('accounts:login'),
            {'username': user.username, 'password': DEFAULT_PASSWORD},
        )

        self.assertEqual(Cart.objects.filter(user=user, paid_status=False).count(), 1)


class MoneyFormatTests(ShopTestCase):
    """Формат грошей — на бекенді, щоб фронтенд не винаходив локалізацію.

    Пробіли саме нерозривні: інакше «4 850 ₴» розірветься переносом рядка
    посеред числа. У тестах вони підставляються через NBSP з cart.services,
    щоб очікування не залежало від невидимого символу в тексті тесту.
    """

    def test_thousands_are_separated(self):
        self.assertEqual(format_price(Decimal('4850.00')), f'4{NBSP}850{NBSP}₴')

    def test_small_numbers(self):
        self.assertEqual(format_price(Decimal('0.00')), f'0{NBSP}₴')

    def test_millions(self):
        self.assertEqual(format_price(Decimal('1234567.00')), f'1{NBSP}234{NBSP}567{NBSP}₴')

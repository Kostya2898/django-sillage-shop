"""Тести профілю користувача та злиття кошиків при вході."""

from django.urls import reverse

from accounts.models import UserProfile
from cart.models import Cart, CartItem
from testing import ShopTestCase
from testing.factories import DEFAULT_PASSWORD, ProductFactory, UserFactory


class UserProfileTests(ShopTestCase):
    def test_profile_created_by_signal(self):
        user = UserFactory()

        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_profile_page_requires_login(self):
        response = self.client.get(reverse('accounts:profile'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_profile_page_opens_for_owner(self):
        self.login()

        self.assertEqual(self.client.get(reverse('accounts:profile')).status_code, 200)


class CartMergeOnLoginTests(ShopTestCase):
    def test_guest_cart_moves_into_database_on_login(self):
        product = ProductFactory(stock=5)
        user = UserFactory()

        # Гість кладе товар у сесійний кошик.
        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 2})

        self.client.post(
            reverse('accounts:login'),
            {'username': user.username, 'password': DEFAULT_PASSWORD},
        )

        cart = Cart.objects.get(user=user, paid_status=False)
        item = CartItem.objects.get(cart=cart, product=product)
        self.assertEqual(item.quantity, 2)

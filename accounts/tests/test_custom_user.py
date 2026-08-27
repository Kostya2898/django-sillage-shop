"""Кастомна модель користувача та її звʼязок із профілем.

Вимога уроку 2: `CustomUser(AbstractUser)` + `AUTH_USER_MODEL`, а решта полів —
в окремому `UserProfile`, який створюється сигналом.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse

from accounts.models import UserProfile
from testing import ShopTestCase
from testing.factories import DEFAULT_PASSWORD, UserFactory

User = get_user_model()


class CustomUserModelTests(ShopTestCase):
    def test_project_uses_custom_user_model(self):
        self.assertEqual(settings.AUTH_USER_MODEL, 'accounts.CustomUser')
        self.assertEqual(User._meta.label, 'accounts.CustomUser')

    def test_username_stays_the_login_field(self):
        """На email-логін навмисно не переходимо — форми лишаються ті самі."""
        self.assertEqual(User.USERNAME_FIELD, 'username')

    def test_email_is_unique(self):
        UserFactory(email='same@example.com')

        with self.assertRaises(IntegrityError), transaction.atomic():
            UserFactory(email='same@example.com')

    def test_shop_fields_exist(self):
        user = UserFactory(phone='+380670000000', is_subscribed=True)

        user.refresh_from_db()
        self.assertEqual(user.phone, '+380670000000')
        self.assertTrue(user.is_subscribed)
        self.assertIsNotNone(user.created_at)

    def test_subscription_is_off_by_default(self):
        """Згода на розсилку — тільки явна."""
        self.assertFalse(UserFactory().is_subscribed)

    def test_display_name_falls_back_to_username(self):
        self.assertEqual(UserFactory(username='olena').get_display_name(), 'olena')

    def test_display_name_prefers_real_name(self):
        user = UserFactory(first_name='Олена', last_name='Гриценко')

        self.assertEqual(user.get_display_name(), 'Олена Гриценко')


class ProfileSignalTests(ShopTestCase):
    def test_profile_is_created_for_every_new_user(self):
        user = UserFactory()

        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_profile_is_created_only_once(self):
        user = UserFactory()
        user.phone = '+380670000001'
        user.save()

        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)

    def test_profile_is_reachable_as_user_profile(self):
        user = UserFactory()

        self.assertIsInstance(user.profile, UserProfile)

    def test_deleting_user_removes_profile(self):
        user = UserFactory()

        user.delete()

        self.assertEqual(UserProfile.objects.count(), 0)


class SignUpCreatesBothTests(ShopTestCase):
    """ТЗ: реєстрація має дати і CustomUser, і UserProfile."""

    def signup(self, **overrides):
        data = {
            'username': 'newbuyer',
            'email': 'newbuyer@example.com',
            'phone': '+380670000002',
            'password1': 'Sillage-2026-pass',
            'password2': 'Sillage-2026-pass',
        }
        data.update(overrides)
        return self.client.post(reverse('accounts:signup'), data, follow=True)

    def test_signup_creates_user_and_profile(self):
        self.signup()

        user = User.objects.get(username='newbuyer')
        self.assertEqual(user.email, 'newbuyer@example.com')
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_signup_saves_phone(self):
        self.signup()

        self.assertEqual(User.objects.get(username='newbuyer').phone, '+380670000002')

    def test_signup_logs_the_user_in(self):
        response = self.signup()

        self.assertTrue(response.context['user'].is_authenticated)

    def test_duplicate_email_is_refused_with_a_readable_message(self):
        UserFactory(email='taken@example.com')

        response = self.signup(email='taken@example.com')

        self.assertFalse(User.objects.filter(username='newbuyer').exists())
        self.assertContains(response, 'вже зареєстрований')


class ProfilePageTests(ShopTestCase):
    def setUp(self):
        self.user = self.login()

    def test_profile_page_shows_both_forms(self):
        response = self.client.get(reverse('accounts:profile'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('account_form', response.context)
        self.assertIn('profile_form', response.context)

    def test_saving_updates_user_and_profile_together(self):
        response = self.client.post(
            reverse('accounts:profile'),
            {
                'first_name': 'Олена',
                'last_name': 'Гриценко',
                'email': 'olena@example.com',
                'phone': '+380670000003',
                'is_subscribed': 'on',
                'date_of_birth': '1994-05-17',
                'favourite_family': UserProfile.FAMILY_WOODY,
                'default_shipping_address': '',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Олена')
        self.assertEqual(self.user.phone, '+380670000003')
        self.assertTrue(self.user.is_subscribed)

        profile = self.user.profile
        self.assertEqual(str(profile.date_of_birth), '1994-05-17')
        self.assertEqual(profile.favourite_family, UserProfile.FAMILY_WOODY)

    def test_cannot_take_someone_elses_email(self):
        UserFactory(email='occupied@example.com')

        self.client.post(
            reverse('accounts:profile'),
            {
                'first_name': '',
                'last_name': '',
                'email': 'occupied@example.com',
                'phone': '',
                'date_of_birth': '',
                'favourite_family': '',
                'default_shipping_address': '',
            },
        )

        self.user.refresh_from_db()
        self.assertNotEqual(self.user.email, 'occupied@example.com')

    def test_address_choices_are_limited_to_own_addresses(self):
        """Чужа адреса не має потрапити у випадаючий список — це був би IDOR."""
        mine = self.create_address(self.user)
        stranger = self.create_address(UserFactory())

        response = self.client.get(reverse('accounts:profile'))
        queryset = response.context['profile_form'].fields['default_shipping_address'].queryset

        self.assertIn(mine, queryset)
        self.assertNotIn(stranger, queryset)


class LoginStillWorksTests(ShopTestCase):
    def test_login_by_username(self):
        user = UserFactory()

        response = self.client.post(
            reverse('accounts:login'),
            {'username': user.username, 'password': DEFAULT_PASSWORD},
            follow=True,
        )

        self.assertTrue(response.context['user'].is_authenticated)

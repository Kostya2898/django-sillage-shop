"""Покупка без реєстрації.

Вимога зареєструватись — найпоширеніша причина, з якої зібраний кошик так і
лишається незібраним. Тому гостьовий шлях тут перевіряється не як додаткова
опція, а як основний: він має доходити до кінця так само, як шлях власника
акаунта, включно з листом, рахунком і доступом до замовлення.
"""

from django.core import mail
from django.urls import reverse

from orders.models import Order
from orders.services import GUEST_ORDERS_SESSION_KEY, guest_access_token
from testing import ShopTestCase
from testing.factories import DEFAULT_PASSWORD, ProductFactory, UserFactory

GUEST_ADDRESS = {
    'email': 'hostia@example.com',
    'full_name': 'Гостьовий Покупець',
    'phone': '+380671112233',
    'country': 'Україна',
    'city': 'Київ',
    'postal_code': '01034',
    'address_line1': 'вул. Ярославів Вал, 15',
    'address_line2': '',
}


class GuestCheckoutFlowTests(ShopTestCase):
    """Каталог → кошик → checkout → успіх, жодного разу не логінячись."""

    def setUp(self):
        self.product = ProductFactory(stock=10, name='Кедрова тиша')

    def _fill_cart(self, quantity=2):
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': quantity})

    def _go_guest(self):
        """Пройти роздоріжжя, обравши «продовжити як гість»."""
        return self.client.post(reverse('orders:checkout_identity'))

    def _submit_address(self, **overrides):
        return self.client.post(reverse('orders:checkout'), {**GUEST_ADDRESS, **overrides})

    def checkout_as_guest(self, quantity=2, payment_method='cash'):
        self._fill_cart(quantity)
        self._go_guest()
        self._submit_address()
        return self.client.post(
            reverse('orders:checkout_confirm'),
            self.confirm_payload(payment_method=payment_method),
        )

    def test_anonymous_checkout_offers_a_crossroads(self):
        """Незалогінений не впирається у форму входу, а бачить три виходи."""
        self._fill_cart()

        response = self.client.get(reverse('orders:checkout'), follow=True)

        self.assertContains(response, 'Продовжити як гість')
        self.assertContains(response, 'Увійти')
        self.assertContains(response, 'Зареєструватися')

    def test_anonymous_is_not_redirected_to_login(self):
        """Головне: checkout не веде на сторінку входу."""
        self._fill_cart()

        response = self.client.get(reverse('orders:checkout'))

        self.assertNotIn(reverse('accounts:login'), response['Location'])
        self.assertEqual(response['Location'], reverse('orders:checkout_identity'))

    def test_guest_completes_the_order(self):
        self.checkout_as_guest()

        order = Order.objects.get()
        self.assertIsNone(order.user, 'Гостьове замовлення не має мати користувача')
        self.assertEqual(order.guest_email, 'hostia@example.com')
        self.assertEqual(order.shipping_city, 'Київ')
        self.assertEqual(order.items.get().product_name, 'Кедрова тиша')

    def test_guest_order_deducts_stock(self):
        self.checkout_as_guest(quantity=3)

        self.assertStock(self.product, 7)

    def test_guest_receives_the_letter(self):
        self.checkout_as_guest()

        order = Order.objects.get()
        # Лист покупцю + сповіщення адміністраторам.
        self.assertEqual(len(mail.outbox), 2)
        letter = mail.outbox[0]
        self.assertEqual(letter.to, ['hostia@example.com'])
        self.assertIn(order.order_number, letter.subject)

    def test_letter_carries_the_invoice(self):
        self.checkout_as_guest()

        attachments = mail.outbox[0].attachments
        self.assertEqual(len(attachments), 1, 'До підтвердження має бути прикріплений рахунок')
        name, content, mimetype = attachments[0]
        self.assertTrue(name.endswith('.pdf'))
        self.assertEqual(mimetype, 'application/pdf')
        self.assertTrue(content.startswith(b'%PDF'))

    def test_guest_address_is_not_saved_to_the_address_book(self):
        """Адреса гостя живе тільки знімком у замовленні."""
        from orders.models import ShippingAddress

        self.checkout_as_guest()

        self.assertEqual(ShippingAddress.objects.count(), 0)

    def test_success_page_opens_for_the_guest(self):
        self.checkout_as_guest()
        order = Order.objects.get()

        response = self.client.get(reverse('orders:order_success', args=[order.order_number]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, order.order_number)

    def test_guest_can_open_own_order_detail(self):
        self.checkout_as_guest()
        order = Order.objects.get()

        response = self.client.get(reverse('orders:order_detail', args=[order.order_number]))

        self.assertEqual(response.status_code, 200)

    def test_email_is_required(self):
        """Без пошти гість втратив би доступ до власного замовлення."""
        self._fill_cart()
        self._go_guest()

        response = self._submit_address(email='')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Order.objects.count(), 0)
        self.assertIn('email', response.context['form'].errors)

    def test_guest_can_pay_by_card(self):
        """Оплата карткою не має впиратись у форму входу."""
        response = self.checkout_as_guest(payment_method='card')

        order = Order.objects.get()
        self.assertEqual(
            response['Location'],
            reverse('payments:initiate_payment', args=[order.order_number]),
        )

        gateway = self.client.get(reverse('payments:initiate_payment', args=[order.order_number]))
        self.assertEqual(gateway.status_code, 200)


class GuestOrderIsolationTests(ShopTestCase):
    """Гостьове замовлення видно тільки тому, хто його оформив."""

    def setUp(self):
        self.product = ProductFactory(stock=10)
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 1})
        self.client.post(reverse('orders:checkout_identity'))
        self.client.post(reverse('orders:checkout'), GUEST_ADDRESS)
        self.client.post(reverse('orders:checkout_confirm'), self.confirm_payload())
        self.order = Order.objects.get()

    def test_order_number_is_remembered_in_the_session(self):
        self.assertIn(
            self.order.order_number,
            self.client.session.get(GUEST_ORDERS_SESSION_KEY, []),
        )

    def test_another_visitor_gets_404(self):
        """Інша сесія — інший відвідувач, і замовлення для нього не існує."""
        self.client.logout()
        self.client.cookies.clear()

        response = self.client.get(reverse('orders:order_detail', args=[self.order.order_number]))

        self.assertEqual(response.status_code, 404)

    def test_logged_in_stranger_gets_404(self):
        self.client.cookies.clear()
        self.login()

        response = self.client.get(reverse('orders:order_detail', args=[self.order.order_number]))

        self.assertEqual(response.status_code, 404)

    def test_signed_link_from_the_letter_opens_the_order(self):
        """Посилання з листа працює і в іншому браузері."""
        token = guest_access_token(self.order)
        self.client.cookies.clear()

        response = self.client.get(
            reverse('orders:order_detail', args=[self.order.order_number]),
            {'token': token},
        )

        self.assertEqual(response.status_code, 200)

    def test_token_of_another_order_does_not_open_this_one(self):
        other = self.create_order()
        self.client.cookies.clear()

        response = self.client.get(
            reverse('orders:order_detail', args=[self.order.order_number]),
            {'token': guest_access_token(other)},
        )

        self.assertEqual(response.status_code, 404)

    def test_forged_token_is_rejected(self):
        self.client.cookies.clear()

        response = self.client.get(
            reverse('orders:order_detail', args=[self.order.order_number]),
            {'token': 'not-a-real-signature'},
        )

        self.assertEqual(response.status_code, 404)

    def test_guest_cannot_open_a_registered_users_order(self):
        """Стара гарантія ізоляції не має ослабнути через гостьовий доступ."""
        theirs = self.create_order()
        self.client.cookies.clear()

        response = self.client.get(reverse('orders:order_detail', args=[theirs.order_number]))

        self.assertEqual(response.status_code, 404)


class GuestOrdersBecomeYoursOnSignupTests(ShopTestCase):
    """Купував гостем, потім зареєструвався — замовлення знаходяться."""

    def _guest_order(self, email):
        product = ProductFactory(stock=5)
        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 1})
        self.client.post(reverse('orders:checkout_identity'))
        self.client.post(reverse('orders:checkout'), {**GUEST_ADDRESS, 'email': email})
        self.client.post(reverse('orders:checkout_confirm'), self.confirm_payload())
        return Order.objects.latest('created_at')

    def test_registration_with_the_same_email_claims_the_order(self):
        order = self._guest_order('kupets@example.com')

        user = UserFactory(email='kupets@example.com')

        order.refresh_from_db()
        self.assertEqual(order.user, user)
        self.assertEqual(order.guest_email, 'kupets@example.com', 'Знімок пошти лишається')

    def test_matching_ignores_letter_case(self):
        order = self._guest_order('Kupets@Example.com')

        user = UserFactory(email='kupets@example.com')

        order.refresh_from_db()
        self.assertEqual(order.user, user)

    def test_another_email_claims_nothing(self):
        order = self._guest_order('kupets@example.com')

        UserFactory(email='hto-inshyi@example.com')

        order.refresh_from_db()
        self.assertIsNone(order.user)

    def test_claimed_order_appears_in_the_account(self):
        order = self._guest_order('kupets@example.com')
        user = UserFactory(email='kupets@example.com')

        self.client.cookies.clear()
        self.client.login(username=user.username, password=DEFAULT_PASSWORD)
        response = self.client.get(reverse('orders:order_list'))

        self.assertContains(response, order.order_number)

    def test_existing_users_orders_are_left_alone(self):
        """Прив'язка стосується лише щойно створених акаунтів."""
        mine = self.create_order()
        owner = mine.user

        UserFactory(email=owner.email.replace('@', '+other@'))

        mine.refresh_from_db()
        self.assertEqual(mine.user, owner)

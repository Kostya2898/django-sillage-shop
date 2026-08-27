"""Наскрізний сценарій покупки на кастомній моделі користувача.

Перевіряє те, що ТЗ називає «працює end-to-end»: гість набирає кошик,
реєструється або логіниться, кошик переживає вхід, замовлення створюється,
склад списується, лист іде, оплата закривається.
"""

from django.core import mail
from django.urls import reverse

from cart.models import Cart
from orders.models import Order
from payments.models import Transaction
from payments.signing import transaction_signature
from testing import ShopTestCase
from testing.factories import DEFAULT_PASSWORD, ProductFactory, UserFactory


class GuestToPaidOrderTests(ShopTestCase):
    def test_full_purchase_from_guest_cart_to_paid_order(self):
        product = ProductFactory(stock=10, name='Кедрова тиша')
        user = UserFactory()

        # 1. Гість кладе товар у сесійний кошик.
        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 2})
        self.assertEqual(len(self.client.get(reverse('cart:cart_detail')).context['cart']), 2)

        # 2. Логіниться — сигнал user_logged_in переносить кошик у базу.
        self.client.post(
            reverse('accounts:login'),
            {'username': user.username, 'password': DEFAULT_PASSWORD},
        )
        db_cart = Cart.objects.get(user=user, paid_status=False)
        self.assertEqual(db_cart.items.get().quantity, 2, 'Кошик не пережив вхід')

        # 3. Адреса доставки.
        address = self.create_address(user)
        self.client.post(
            reverse('orders:checkout'),
            {'select_address': '1', 'address_id': address.id},
        )

        # 4. Підтвердження замовлення з онлайн-оплатою.
        self.client.post(
            reverse('orders:checkout_confirm'),
            {'payment_method': 'card', 'notes': 'Лишити у консьєржа', 'agree_terms': 'on'},
        )

        order = Order.objects.get()
        self.assertEqual(order.user, user)
        self.assertEqual(order.cart, db_cart, 'Замовлення має памʼятати свій кошик')
        self.assertEqual(order.items.get().product_name, 'Кедрова тиша')
        self.assertStock(product, 8)
        # Два листи: підтвердження покупцю і сповіщення адміністраторам.
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn(order.order_number, mail.outbox[0].subject)

        # 5. Оплата через мок-шлюз із коректним підписом.
        self.client.get(reverse('payments:initiate_payment', args=[order.order_number]))
        payment = Transaction.objects.get(order=order)
        self.client.get(
            reverse('payments:payment_callback'),
            {
                'status': 'successful',
                'tx_ref': payment.reference,
                'transaction_id': 'MOCK-E2E',
                'signature': transaction_signature(
                    payment.reference, payment.amount, payment.currency
                ),
            },
        )

        order.refresh_from_db()
        db_cart.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAID)
        self.assertTrue(db_cart.paid_status, 'Кошик замовлення мав закритися')
        self.assertEqual(len(mail.outbox), 3, 'Додався ще лист про отриману оплату')
        self.assertIn('Оплату', mail.outbox[-1].subject)

    def test_signup_mid_purchase_keeps_the_cart(self):
        """Той самий шлях, але користувач реєструється просто в процесі."""
        product = ProductFactory(stock=5)

        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 1})
        self.client.post(
            reverse('accounts:signup'),
            {
                'username': 'freshbuyer',
                'email': 'freshbuyer@example.com',
                'phone': '+380670000004',
                'password1': 'Sillage-2026-pass',
                'password2': 'Sillage-2026-pass',
            },
        )

        response = self.client.get(reverse('cart:cart_detail'))
        self.assertEqual(len(response.context['cart']), 1)

    def test_cash_order_skips_payment_and_stays_pending(self):
        product = ProductFactory(stock=5)
        user = self.login()
        address = self.create_address(user)

        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 1})
        self.client.post(
            reverse('orders:checkout'), {'select_address': '1', 'address_id': address.id}
        )
        response = self.client.post(
            reverse('orders:checkout_confirm'),
            {'payment_method': 'cash', 'notes': '', 'agree_terms': 'on'},
            follow=True,
        )

        order = Order.objects.get()
        self.assertEqual(order.status, Order.STATUS_PENDING)
        self.assertFalse(order.requires_online_payment)
        self.assertContains(response, order.order_number)

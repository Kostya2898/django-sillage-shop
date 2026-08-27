"""Callback мок-шлюзу не має вірити параметрам з URL.

Баг з AUDIT.md #3: `payment_callback` збирав словник `verification`
з `request.GET['status']` і полів самої транзакції, після чого сам себе
перевіряв. Тобто будь-хто, маючи власну транзакцію, міг відкрити
`/payments/callback/?status=successful&tx_ref=<свій>` і зробити замовлення
оплаченим, не заплативши.

Підпис у цих тестах рахується **незалежно** від реалізації — власним
hmac прямо тут. Якщо колись зміниться формула, тест це помітить, а не
підіграє коду.
"""

import hashlib
import hmac

from django.conf import settings
from django.urls import reverse

from orders.models import Order
from payments.models import Transaction
from testing import ShopTestCase
from testing.factories import ProductFactory, TransactionFactory, UserFactory


def expected_signature(tx_ref, amount, currency):
    """Те саме, що має рахувати застосунок: HMAC-SHA256 від трійки полів."""
    payload = f'{tx_ref}:{amount:.2f}:{currency}'
    return hmac.new(
        settings.PAYMENT_SECRET_KEY.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


class PaymentCallbackSecurityTests(ShopTestCase):
    def setUp(self):
        self.user = self.login()
        self.cart = self.create_cart_with_items(user=self.user, items=[(ProductFactory(), 1)])
        self.order = self.create_order(user=self.user, cart=self.cart, payment_method='card')
        self.transaction = TransactionFactory(order=self.order, user=self.user)
        self.url = reverse('payments:payment_callback')

    def params(self, **overrides):
        data = {
            'status': 'successful',
            'tx_ref': self.transaction.reference,
            'transaction_id': 'MOCK-1',
            'signature': expected_signature(
                self.transaction.reference,
                self.transaction.amount,
                self.transaction.currency,
            ),
        }
        data.update(overrides)
        return data

    def assertOrderNotPaid(self):
        self.order.refresh_from_db()
        self.transaction.refresh_from_db()
        self.assertNotEqual(self.order.status, Order.STATUS_PAID)
        self.assertNotEqual(self.transaction.status, Transaction.STATUS_COMPLETED)

    # --- сам баг ---------------------------------------------------------

    def test_forged_signature_is_rejected(self):
        response = self.client.get(self.url, self.params(signature='deadbeef' * 8))

        self.assertEqual(response.status_code, 400)
        self.assertOrderNotPaid()

    def test_callback_without_signature_is_rejected(self):
        params = self.params()
        del params['signature']

        response = self.client.get(self.url, params)

        self.assertEqual(response.status_code, 400)
        self.assertOrderNotPaid()

    def test_signature_from_another_transaction_is_rejected(self):
        other = TransactionFactory(order=self.order, user=self.user)

        response = self.client.get(
            self.url,
            self.params(
                signature=expected_signature(other.reference, other.amount, other.currency)
            ),
        )

        self.assertEqual(response.status_code, 400)
        self.assertOrderNotPaid()

    def test_tampered_amount_invalidates_signature(self):
        """Підпис прибитий до суми: змінити її, не переписавши підпис, не вийде."""
        params = self.params()  # підпис над ПОЧАТКОВОЮ сумою

        self.transaction.amount += 1
        self.transaction.save(update_fields=['amount'])

        response = self.client.get(self.url, params)

        self.assertEqual(response.status_code, 400)
        self.assertOrderNotPaid()

    # --- належність транзакції -------------------------------------------

    def test_someone_elses_transaction_is_not_found(self):
        stranger = UserFactory()
        stranger_order = self.create_order(user=stranger, payment_method='card')
        stranger_tx = TransactionFactory(order=stranger_order, user=stranger)

        response = self.client.get(
            self.url,
            {
                'status': 'successful',
                'tx_ref': stranger_tx.reference,
                'transaction_id': 'MOCK-X',
                'signature': expected_signature(
                    stranger_tx.reference, stranger_tx.amount, stranger_tx.currency
                ),
            },
        )

        self.assertEqual(response.status_code, 404)
        stranger_order.refresh_from_db()
        self.assertNotEqual(stranger_order.status, Order.STATUS_PAID)

    def test_unknown_tx_ref_is_not_found(self):
        response = self.client.get(
            self.url,
            {
                'status': 'successful',
                'tx_ref': 'nope',
                'transaction_id': 'X',
                'signature': expected_signature('nope', self.transaction.amount, 'UAH'),
            },
        )

        self.assertEqual(response.status_code, 404)

    def test_amount_must_match_the_order(self):
        """Транзакція, що розійшлася із сумою замовлення, не проходить."""
        self.order.total_amount += 500
        self.order.save(update_fields=['total_amount'])

        response = self.client.get(self.url, self.params(), follow=True)

        self.assertOrderNotPaid()
        self.assertEqual(response.status_code, 200)

    # --- успішний шлях ----------------------------------------------------

    def test_valid_callback_pays_the_order(self):
        response = self.client.get(self.url, self.params(), follow=True)

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.transaction.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PAID)
        self.assertEqual(self.transaction.status, Transaction.STATUS_COMPLETED)
        self.assertEqual(self.transaction.gateway_transaction_id, 'MOCK-1')

    def test_cancelled_payment_marks_transaction_failed(self):
        self.client.get(self.url, self.params(status='cancelled'), follow=True)

        self.order.refresh_from_db()
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, Transaction.STATUS_FAILED)
        self.assertNotEqual(self.order.status, Order.STATUS_PAID)

    # --- ідемпотентність --------------------------------------------------

    def test_repeated_callback_changes_nothing(self):
        self.client.get(self.url, self.params(), follow=True)
        first = Order.objects.get(pk=self.order.pk).updated_at

        self.client.get(self.url, self.params(transaction_id='MOCK-2'), follow=True)

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.gateway_transaction_id, 'MOCK-1')
        self.assertEqual(Order.objects.get(pk=self.order.pk).updated_at, first)

    def test_repeated_callback_does_not_send_second_email(self):
        from django.core import mail

        self.client.get(self.url, self.params(), follow=True)
        self.assertEqual(len(mail.outbox), 1)

        self.client.get(self.url, self.params(), follow=True)
        self.assertEqual(len(mail.outbox), 1, 'Другий лист про оплату надсилати не можна')

    def test_repeated_callback_does_not_duplicate_status_history(self):
        self.client.get(self.url, self.params(), follow=True)
        self.client.get(self.url, self.params(), follow=True)

        self.assertEqual(
            self.order.status_history.filter(status=Order.STATUS_PAID).count(),
            1,
        )

    def test_failed_transaction_cannot_be_retried_through_callback(self):
        self.client.get(self.url, self.params(status='cancelled'), follow=True)

        self.client.get(self.url, self.params(status='successful'), follow=True)

        self.assertOrderNotPaid()

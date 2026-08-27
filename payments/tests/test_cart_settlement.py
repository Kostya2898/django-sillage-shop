"""Оплата має закривати саме той кошик, з якого зроблене замовлення.

Баг з AUDIT.md #6: `_complete_payment` робив
`Cart.objects.filter(user=..., paid_status=False).update(paid_status=True)`,
тобто позначав оплаченими **всі** неоплачені кошики користувача. Якщо між
створенням замовлення й оплатою покупець поклав щось нове, ці товари мовчки
зникали з його активного кошика.
"""

from cart.models import Cart
from payments.views import _complete_payment
from testing import ShopTestCase
from testing.factories import ProductFactory, TransactionFactory, UserFactory


class CartSettlementTests(ShopTestCase):
    def test_payment_never_closes_more_than_one_cart(self):
        """Найпростіше формулювання бага: один платіж — щонайбільше один кошик.

        Тест навмисно не спирається на новий звʼязок Order→Cart, щоб падати
        саме на псуванні даних, а не на відсутності поля.
        """
        user = UserFactory()
        self.create_cart_with_items(user=user)
        self.create_cart_with_items(user=user)
        order = self.create_order(user=user)

        _complete_payment(TransactionFactory(order=order, user=user), 'MOCK-0')

        closed = Cart.objects.filter(user=user, paid_status=True).count()
        self.assertLessEqual(closed, 1, f'Один платіж закрив {closed} кошики')

    def test_only_the_order_cart_is_closed(self):
        """Класичний сценарій бага: два неоплачені кошики в одного покупця."""
        user = UserFactory()
        order_cart = self.create_cart_with_items(user=user, items=[(ProductFactory(), 2)])
        # Другий кошик — той, який покупець набрав уже після оформлення.
        later_cart = self.create_cart_with_items(user=user, items=[(ProductFactory(), 1)])

        order = self.create_order(user=user, cart=order_cart)
        transaction = TransactionFactory(order=order, user=user)

        _complete_payment(transaction, 'MOCK-1')

        order_cart.refresh_from_db()
        later_cart.refresh_from_db()
        self.assertTrue(order_cart.paid_status, 'Кошик замовлення мав закритися')
        self.assertFalse(later_cart.paid_status, 'Пізніший кошик чіпати не можна')

    def test_later_cart_keeps_its_items(self):
        user = UserFactory()
        order_cart = self.create_cart_with_items(user=user, items=[(ProductFactory(), 2)])
        later_product = ProductFactory()
        later_cart = self.create_cart_with_items(user=user, items=[(later_product, 4)])

        order = self.create_order(user=user, cart=order_cart)
        _complete_payment(TransactionFactory(order=order, user=user), 'MOCK-2')

        later_cart.refresh_from_db()
        self.assertEqual(later_cart.items.count(), 1)
        self.assertEqual(later_cart.items.get().product, later_product)

    def test_other_users_carts_are_untouched(self):
        buyer = UserFactory()
        stranger = UserFactory()
        buyer_cart = self.create_cart_with_items(user=buyer)
        stranger_cart = self.create_cart_with_items(user=stranger)

        order = self.create_order(user=buyer, cart=buyer_cart)
        _complete_payment(TransactionFactory(order=order, user=buyer), 'MOCK-3')

        stranger_cart.refresh_from_db()
        self.assertFalse(stranger_cart.paid_status)

    def test_order_without_cart_does_not_break_payment(self):
        """Замовлення можуть існувати без звʼязку з кошиком (напр. створені в адмінці)."""
        user = UserFactory()
        loose_cart = self.create_cart_with_items(user=user)
        order = self.create_order(user=user)  # cart не заданий

        _complete_payment(TransactionFactory(order=order, user=user), 'MOCK-4')

        order.refresh_from_db()
        loose_cart.refresh_from_db()
        self.assertEqual(order.status, order.STATUS_PAID)
        self.assertFalse(loose_cart.paid_status, 'Без явного звʼязку кошик чіпати не можна')

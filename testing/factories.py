"""Фабрики factory_boy для всіх моделей проєкту.

Мета — щоб тест описував тільки те, що для нього важливо: якщо тесту байдуже,
як зветься товар, він не має цього писати. Усі обовʼязкові поля мають дефолти,
унікальні (slug, order_number) генеруються послідовністю.
"""

from decimal import Decimal

import factory
from django.contrib.auth import get_user_model

from cart.models import Cart, CartItem
from orders.models import Order, OrderItem, OrderStatusHistory, ShippingAddress
from payments.models import Transaction
from shop.models import Category, Product

User = get_user_model()

DEFAULT_PASSWORD = 'test-pass-12345'


class UserFactory(factory.django.DjangoModelFactory):
    """Користувач із заповненим email — без нього не піде жоден лист."""

    class Meta:
        model = User
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f'user{n}')
    email = factory.LazyAttribute(lambda obj: f'{obj.username}@example.com')

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        if not create:
            return
        obj.set_password(extracted or DEFAULT_PASSWORD)
        obj.save(update_fields=['password'])


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f'Категорія {n}')
    slug = factory.Sequence(lambda n: f'category-{n}')
    is_active = True


class ProductFactory(factory.django.DjangoModelFactory):
    """Товар у наявності. Кількість на складі задається в тесті явно."""

    class Meta:
        model = Product

    category = factory.SubFactory(CategoryFactory)
    name = factory.Sequence(lambda n: f'Аромат {n}')
    slug = factory.Sequence(lambda n: f'product-{n}')
    description = 'Опис для тесту.'
    price = Decimal('1000.00')
    stock = 10
    is_available = True


class CartFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Cart

    user = factory.SubFactory(UserFactory)
    paid_status = False


class CartItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CartItem

    cart = factory.SubFactory(CartFactory)
    product = factory.SubFactory(ProductFactory)
    quantity = 1


class ShippingAddressFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ShippingAddress

    user = factory.SubFactory(UserFactory)
    full_name = 'Тестовий Покупець'
    phone = '+380670000000'
    country = 'Україна'
    city = 'Київ'
    postal_code = '01001'
    address_line1 = 'вул. Тестова, 1'


class OrderFactory(factory.django.DjangoModelFactory):
    """Замовлення зі знімком адреси. `order_number` генерує сама модель."""

    class Meta:
        model = Order

    user = factory.SubFactory(UserFactory)
    shipping_full_name = 'Тестовий Покупець'
    shipping_phone = '+380670000000'
    shipping_country = 'Україна'
    shipping_city = 'Київ'
    shipping_postal_code = '01001'
    shipping_address_line1 = 'вул. Тестова, 1'
    total_amount = Decimal('1000.00')
    payment_method = 'card'
    status = Order.STATUS_PENDING


class OrderItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrderItem

    order = factory.SubFactory(OrderFactory)
    product = factory.SubFactory(ProductFactory)
    product_name = factory.LazyAttribute(lambda obj: obj.product.name)
    price = factory.LazyAttribute(lambda obj: obj.product.price)
    quantity = 1


class OrderStatusHistoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrderStatusHistory

    order = factory.SubFactory(OrderFactory)
    status = Order.STATUS_PENDING
    note = ''


class TransactionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Transaction

    reference = factory.Sequence(lambda n: f'txref{n:032d}')
    order = factory.SubFactory(OrderFactory)
    user = factory.LazyAttribute(lambda obj: obj.order.user)
    amount = factory.LazyAttribute(lambda obj: obj.order.total_amount)
    currency = 'UAH'
    status = Transaction.STATUS_SPENDING

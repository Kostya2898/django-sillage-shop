"""Гібридний кошик: session-based для гостей, database-based для користувачів.

Обидва класи мають однаковий інтерфейс (`add`, `remove`, `clear`, `__iter__`,
`__len__`, `get_total_price`), тому views і шаблони не знають, з яким саме
кошиком працюють. Потрібний тип повертає фабрика `get_cart(request)`.
"""

from decimal import Decimal

from django.conf import settings
from django.db import transaction

from shop.models import Product

from .models import Cart, CartItem


class SessionCart:
    """Кошик анонімного користувача, що живе у сесії Django.

    Структура даних у сесії:
        {'12': {'quantity': 2, 'price': '750.00'}, ...}
    Ключ — id товару у вигляді рядка (сесія серіалізується в JSON,
    де ключі словника можуть бути тільки рядками).
    """

    def __init__(self, request):
        self.session = request.session
        cart = self.session.get(settings.CART_SESSION_ID)

        if cart is None:
            cart = self.session[settings.CART_SESSION_ID] = {}

        self.cart = cart

    def add(self, product, quantity=1, update_quantity=False):
        """Додати товар у кошик або змінити його кількість."""
        product_id = str(product.id)

        if product_id not in self.cart:
            self.cart[product_id] = {'quantity': 0, 'price': str(product.price)}

        if update_quantity:
            self.cart[product_id]['quantity'] = quantity
        else:
            self.cart[product_id]['quantity'] += quantity

        # Ціна могла змінитися відтоді, як товар поклали в кошик.
        self.cart[product_id]['price'] = str(product.price)
        self.save()

    def remove(self, product):
        """Видалити товар з кошика."""
        product_id = str(product.id)
        if product_id in self.cart:
            del self.cart[product_id]
            self.save()

    def save(self):
        """Позначити сесію зміненою, щоб Django записав її."""
        self.session.modified = True

    def __iter__(self):
        """Пройтися по товарах кошика, підвантаживши об'єкти Product з бази."""
        product_ids = list(self.cart.keys())
        products = Product.objects.filter(id__in=product_ids)
        cart = {str(pk): dict(data) for pk, data in self.cart.items()}

        for product in products:
            cart[str(product.id)]['product'] = product

        for item in cart.values():
            # Товар могли видалити з каталогу вже після додавання в кошик.
            if 'product' not in item:
                continue
            item['price'] = Decimal(item['price'])
            item['total_price'] = item['price'] * item['quantity']
            yield item

    def __len__(self):
        """Загальна кількість одиниць товару в кошику."""
        return sum(item['quantity'] for item in self.cart.values())

    def get_total_price(self):
        """Загальна сума кошика."""
        return sum(
            (Decimal(item['price']) * item['quantity'] for item in self.cart.values()),
            Decimal('0.00'),
        )

    def clear(self):
        """Очистити кошик."""
        self.session.pop(settings.CART_SESSION_ID, None)
        self.cart = {}
        self.save()


class DatabaseCart:
    """Кошик зареєстрованого користувача, що зберігається в базі даних."""

    def __init__(self, request, user=None):
        # `user` передається явно там, де request ще не має атрибута user —
        # наприклад, з обробника сигналу user_logged_in.
        self.request = request
        self.user = user or request.user
        # Беремо саме неоплачений кошик: оплачені лишаються в базі як історія.
        self.cart, _ = Cart.objects.get_or_create(user=self.user, paid_status=False)

    def add(self, product, quantity=1, update_quantity=False):
        """Додати товар у кошик або змінити його кількість."""
        cart_item, created = CartItem.objects.get_or_create(
            cart=self.cart,
            product=product,
            defaults={'quantity': quantity},
        )

        if not created:
            if update_quantity:
                cart_item.quantity = quantity
            else:
                cart_item.quantity += quantity
            cart_item.save()

    def remove(self, product):
        """Видалити товар з кошика."""
        CartItem.objects.filter(cart=self.cart, product=product).delete()

    def __iter__(self):
        """Пройтися по товарах кошика у тому ж форматі, що й SessionCart."""
        for item in self.cart.items.select_related('product'):
            yield {
                'product': item.product,
                'quantity': item.quantity,
                'price': item.product.price,
                'total_price': item.get_total_price(),
            }

    def __len__(self):
        return self.cart.get_total_items()

    def get_total_price(self):
        return self.cart.get_total_price()

    def clear(self):
        """Очистити кошик."""
        self.cart.items.all().delete()


def get_cart(request):
    """Фабрика: повертає потрібний тип кошика залежно від того, хто зайшов."""
    if request.user.is_authenticated:
        return DatabaseCart(request)
    return SessionCart(request)


@transaction.atomic
def merge_carts(request, user=None):
    """Перенести товари з session-кошика в кошик у базі при вході користувача."""
    user = user or getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return

    session_data = request.session.get(settings.CART_SESSION_ID)
    if not session_data:
        # Гостьового кошика не було — нічого переносити (і нічого створювати).
        return

    session_cart = SessionCart(request)
    db_cart = DatabaseCart(request, user=user)

    for item in session_cart:
        db_cart.add(
            product=item['product'],
            quantity=item['quantity'],
            update_quantity=False,
        )

    session_cart.clear()

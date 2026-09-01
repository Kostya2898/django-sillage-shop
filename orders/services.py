"""Бізнес-логіка замовлень, яка не має жити у view чи в адмінці.

Тут три групи функцій:

* скасування замовлення (`cancel_order`) — транзакція з поверненням складу;
* стан checkout у сесії — промокод, спосіб доставки, адреса гостя;
* доступ до замовлення (`get_order_for_request`) — єдине місце, яке вирішує,
  чи має цей запит право бачити це замовлення.
"""

import logging
from decimal import Decimal
from typing import NamedTuple

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import F
from django.http import Http404

from shop.models import Product

from .models import Coupon, DeliveryMethod, Order

logger = logging.getLogger(__name__)

# Ключі сесії. Зібрані разом, щоб `checkout_reset` нічого не забув почистити.
COUPON_SESSION_KEY = 'checkout_coupon_id'
DELIVERY_SESSION_KEY = 'checkout_delivery_id'
GUEST_ADDRESS_SESSION_KEY = 'checkout_guest_address'
GUEST_MODE_SESSION_KEY = 'checkout_as_guest'
ADDRESS_SESSION_KEY = 'shipping_address_id'

# Номери гостьових замовлень цієї сесії. Для гостя це єдиний спосіб довести,
# що замовлення його: акаунта, з яким можна звірити, не існує.
GUEST_ORDERS_SESSION_KEY = 'guest_orders'


@transaction.atomic
def cancel_order(order, actor=None, note=''):
    """Скасувати замовлення і повернути його позиції на склад.

    Повертає `True`, якщо перехід справді відбувся, і `False`, якщо замовлення
    вже було скасоване раніше.

    Ідемпотентність тримається на самому статусі: перехід у `cancelled` і
    повернення складу відбуваються в одній транзакції під `select_for_update`,
    тому «статус уже cancelled» означає рівно те саме, що «склад уже повернули».
    Окреме поле-прапорець для цього не потрібне.
    """
    locked = Order.objects.select_for_update().get(pk=order.pk)

    if locked.status == Order.STATUS_CANCELLED:
        logger.info('Замовлення %s уже скасоване — склад не чіпаємо', locked.order_number)
        return False

    for item in locked.items.all():
        # OrderItem.product має on_delete=SET_NULL: товар могли прибрати
        # з каталогу вже після покупки, і повертати тоді нема куди.
        if item.product_id is None:
            logger.warning(
                'Позиція «%s» замовлення %s не має товару — склад не повертаємо',
                item.product_name,
                locked.order_number,
            )
            continue

        # F() рахує на боці бази — без гонок «прочитав-змінив-записав».
        Product.objects.filter(pk=item.product_id).update(stock=F('stock') + item.quantity)

    # Запис в історію і лист покупцю робить сигнал `record_status_change`
    # (orders/signals.py) — тут лише пояснюємо йому, хто і чому скасував.
    locked.status = Order.STATUS_CANCELLED
    locked._status_note = note or 'Замовлення скасовано, товари повернуто на склад'
    locked._status_actor = actor
    locked.save(update_fields=['status', 'updated_at'])

    # Синхронізуємо переданий обʼєкт, щоб той, хто викликав, не працював
    # зі застарілим статусом.
    order.status = Order.STATUS_CANCELLED

    logger.info('Замовлення %s скасовано, склад повернуто', locked.order_number)
    return True


# ---------------------------------------------------------------------------
# Підсумок замовлення
# ---------------------------------------------------------------------------


class OrderTotals(NamedTuple):
    """Підсумок, розкладений на складові: товари − знижка + доставка."""

    items_total: Decimal
    discount: Decimal
    delivery: Decimal
    total: Decimal


def calculate_totals(items_total, coupon=None, delivery=None):
    """Порахувати підсумок замовлення.

    Поріг безкоштовної доставки звіряємо з сумою **після знижки** — з тією,
    яку покупець справді платить за товар. Інакше стовідсотковий промокод
    давав би безкоштовну доставку нульового замовлення.
    """
    items_total = Decimal(items_total).quantize(Decimal('0.01'))

    discount = coupon.discount_for(items_total) if coupon else Decimal('0.00')
    goods = items_total - discount

    delivery_price = delivery.price_for(goods) if delivery else Decimal('0.00')

    return OrderTotals(
        items_total=items_total,
        discount=discount,
        delivery=delivery_price,
        total=goods + delivery_price,
    )


# ---------------------------------------------------------------------------
# Промокод у сесії
# ---------------------------------------------------------------------------


def apply_coupon(request, code, items_total):
    """Спробувати застосувати промокод. Повертає (купон_або_None, помилка).

    Купон зберігаємо в сесії за id, а не цілим обʼєктом: між кроками checkout
    його можуть вимкнути в адмінці, і на створенні замовлення ми маємо
    побачити свіжий стан, а не той, що був хвилину тому.
    """
    code = (code or '').strip().upper()
    if not code:
        return None, 'Введіть промокод'

    try:
        coupon = Coupon.objects.get(code=code)
    except Coupon.DoesNotExist:
        return None, f'Промокод «{code}» не знайдено'

    is_valid, reason = coupon.is_valid_for(items_total)
    if not is_valid:
        return None, reason

    request.session[COUPON_SESSION_KEY] = coupon.pk
    return coupon, ''


def get_applied_coupon(request, items_total):
    """Купон із сесії, якщо він досі дійсний.

    Мовчки забуваємо купон, який перестав діяти: показувати знижку, якої вже
    немає, гірше, ніж не показувати жодної, — покупець побачив би одну суму
    в кошику й іншу в листі.
    """
    coupon_id = request.session.get(COUPON_SESSION_KEY)
    if not coupon_id:
        return None

    coupon = Coupon.objects.filter(pk=coupon_id).first()
    if coupon is None:
        request.session.pop(COUPON_SESSION_KEY, None)
        return None

    is_valid, _ = coupon.is_valid_for(items_total)
    if not is_valid:
        return None

    return coupon


def clear_coupon(request):
    request.session.pop(COUPON_SESSION_KEY, None)


# ---------------------------------------------------------------------------
# Спосіб доставки
# ---------------------------------------------------------------------------


def available_delivery_methods():
    return DeliveryMethod.objects.filter(is_active=True)


def get_selected_delivery(request):
    """Обраний спосіб доставки або найдешевший активний як розумний дефолт."""
    methods = list(available_delivery_methods())
    if not methods:
        return None

    selected_id = request.session.get(DELIVERY_SESSION_KEY)
    for method in methods:
        if method.pk == selected_id:
            return method

    return methods[0]


def select_delivery(request, method):
    request.session[DELIVERY_SESSION_KEY] = method.pk


# ---------------------------------------------------------------------------
# Доступ до замовлення
# ---------------------------------------------------------------------------


# Сіль підпису. Своя на кожне призначення токена: підпис, зроблений для
# одного, не має підходити до іншого.
GUEST_TOKEN_SALT = 'orders.guest-order-access'


def guest_access_token(order):
    """Підписаний токен, який дає доступ до гостьового замовлення.

    Гість не має акаунта, а сесія живе в одному браузері — без токена
    посилання з листа відкривалося б лише там, де замовлення й оформили,
    і то до першого очищення cookies.
    """
    return signing.dumps(order.order_number, salt=GUEST_TOKEN_SALT)


def order_url(order, absolute=True):
    """Посилання на замовлення. Для гостьового — з токеном доступу."""
    path = order.get_absolute_url()

    if order.user_id is None:
        path = f'{path}?token={guest_access_token(order)}'

    return f'{settings.SITE_URL}{path}' if absolute else path


def _token_matches(token, order_number):
    """Чи це дійсний підпис саме цього номера замовлення."""
    if not token:
        return False

    try:
        signed_number = signing.loads(
            token,
            salt=GUEST_TOKEN_SALT,
            max_age=settings.GUEST_ORDER_LINK_DAYS * 24 * 3600,
        )
    except signing.BadSignature:
        return False

    return signed_number == order_number


def remember_guest_order(request, order):
    """Запамʼятати в сесії, що це замовлення оформив саме цей відвідувач."""
    numbers = request.session.get(GUEST_ORDERS_SESSION_KEY, [])
    if order.order_number not in numbers:
        numbers.append(order.order_number)
        request.session[GUEST_ORDERS_SESSION_KEY] = numbers


def get_order_for_request(request, order_number, queryset=None):
    """Замовлення, яке цьому запиту дозволено бачити. Інакше — 404.

    Єдина точка перевірки для всіх сторінок замовлення: успіх, деталі,
    скасування, рахунок і оплата. Правил рівно два:

    1. залогінений бачить свої замовлення (`user=request.user`);
    2. гість бачить ті, номери яких лежать у **його** сесії, або ті, до яких
       він прийшов із підписаним токеном із власного листа.

    Гостьове замовлення не стає доступним нікому іншому: сесія чужа, а перебір
    номерів не працює — у номері вісім шістнадцяткових символів від uuid4.
    """
    queryset = Order.objects.all() if queryset is None else queryset
    order = queryset.filter(order_number=order_number).first()

    if order is None:
        raise Http404('Замовлення не знайдено')

    if order.user_id is not None:
        if request.user.is_authenticated and order.user_id == request.user.pk:
            return order
        raise Http404('Замовлення не знайдено')

    if order_number in request.session.get(GUEST_ORDERS_SESSION_KEY, []):
        return order

    # Посилання з листа. Токен підписаний ключем проєкту й прив'язаний до
    # конкретного номера, тому підійде тільки до свого замовлення.
    if _token_matches(request.GET.get('token'), order_number):
        remember_guest_order(request, order)
        return order

    raise Http404('Замовлення не знайдено')


def attach_guest_orders(user):
    """Прив'язати попередні гостьові замовлення до щойно створеного акаунта.

    Ключ звʼязку — email: людина оформила покупку гостем, потім зареєструвалась
    тією самою поштою, і замовлення має знайтись у «Моїх замовленнях», а не
    лишитись висіти нічиїм.

    `iexact` навмисно: пошта регістронезалежна, а покупець набирає як завгодно.
    """
    if not user.email:
        return 0

    attached = Order.objects.filter(user__isnull=True, guest_email__iexact=user.email).update(
        user=user
    )

    if attached:
        logger.info('До акаунта %s прив\u02bcязано гостьових замовлень: %s', user, attached)

    return attached


def checkout_reset(request):
    """Прибрати весь стан checkout після успішного оформлення.

    Зібрано в одному місці навмисно: забутий у сесії промокод застосувався б
    до наступного замовлення мовчки й без відома покупця.
    """
    for key in (
        COUPON_SESSION_KEY,
        DELIVERY_SESSION_KEY,
        GUEST_ADDRESS_SESSION_KEY,
        GUEST_MODE_SESSION_KEY,
        ADDRESS_SESSION_KEY,
    ):
        request.session.pop(key, None)

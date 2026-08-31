"""Логіка кошика поза views: валідація кількості та формат JSON-відповіді.

Формат відповіді описаний у `docs/frontend-api.md` — цим документом
користується фронтенд, тож будь-яка зміна тут має йти разом зі зміною там.
"""

from django.conf import settings
from django.template.loader import render_to_string

# Ліміт живе в налаштуваннях, щоб його можна було змінити без правки коду.
MAX_QUANTITY_PER_PRODUCT = getattr(settings, 'CART_MAX_QUANTITY_PER_PRODUCT', 99)

# Нерозривний пробіл. Записаний через chr(), а не літералом: у тексті він
# невідрізненний від звичайного пробілу, і при редагуванні його легко
# втратити — тоді «4 850 ₴» розірветься переносом рядка посеред числа.
NBSP = chr(0xA0)


def format_price(value):
    """Гроші у вигляді «4 850 ₴» з нерозривними пробілами.

    Форматуємо на бекенді свідомо: інакше кожен фронтенд заново винаходив би
    розділювач тисяч і позицію символу валюти, і вони б розʼїхались між
    сторінкою кошика, drawer-ом і checkout-ом.
    """
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return f'{value}{NBSP}₴'
    return f'{number:,}'.replace(',', NBSP) + NBSP + '₴'


def quoted(name):
    """Назва в лапках — але без подвоєння, якщо вона вже в лапках.

    У каталозі є «Discovery-сет «Вісім слідів»», і без цієї перевірки
    повідомлення виходило з двома рівнями лапок поспіль.
    """
    if '«' in name or '»' in name:
        return name
    return f'«{name}»'


def wants_json(request):
    """Чи очікує клієнт JSON.

    Два способи, бо їх шлють різні клієнти: `X-Requested-With` — класика
    fetch/jQuery, `Accept` — те, чим користуються сучасні клієнти й curl.
    Без жодного з них view поводиться як раніше: POST і редірект.
    """
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    return 'application/json' in request.headers.get('Accept', '')


def validate_quantity(cart, product, quantity, absolute=False):
    """Перевірити кількість. Повертає (кількість, помилка_чи_None).

    Звіряємо зі складом **підсумок у кошику після дії**, а не число із
    запиту: інакше «додати 5» двічі при залишку 6 проходить обидва рази,
    і брак товару виявляється аж на checkout.

    `absolute=True` — це «встановити кількість» (оновлення позиції),
    `absolute=False` — «додати до наявного».
    """
    if quantity < 1:
        return None, 'Кількість має бути більшою за 0'

    if not product.is_available:
        return None, f'Товар {quoted(product.name)} зараз недоступний'

    in_cart = cart.get_quantity(product)
    resulting = quantity if absolute else in_cart + quantity

    if resulting > MAX_QUANTITY_PER_PRODUCT:
        reason = f'Максимальна кількість одного товару — {MAX_QUANTITY_PER_PRODUCT} шт.'
        return None, reason if absolute else _headroom(in_cart, MAX_QUANTITY_PER_PRODUCT, reason)

    if resulting > product.stock:
        reason = f'На складі лишилось {product.stock} од. товару {quoted(product.name)}.'
        return None, reason if absolute else _headroom(in_cart, product.stock, reason)

    return quantity, None


def _headroom(in_cart, limit, reason):
    """Повідомлення про відмову, яке одразу каже, що можна зробити далі."""
    available = max(limit - in_cart, 0)
    if available:
        return f'{reason} У кошику вже {in_cart} — можна додати ще {available}.'
    return f'{reason} У кошику вже {in_cart}, більше додати не можна.'


def item_payload(cart, product):
    """Одна позиція кошика для JSON.

    Містить рівно те, що потрібно анімації «товар полетів у кошик»: назву,
    бренд, фото й кількість. Другий запит по ці дані фронтенду не потрібен.
    """
    quantity = cart.get_quantity(product)
    if not quantity:
        return None

    image = product.main_image
    return {
        'id': product.id,
        'slug': product.slug,
        'name': product.name,
        'brand': product.brand.name,
        'url': product.get_absolute_url(),
        'image': image.url if image else '',
        'quantity': quantity,
        'price_display': format_price(product.price),
        'total_display': format_price(product.price * quantity),
    }


def cart_payload(request, cart, message='', item=None):
    """Повна успішна відповідь API кошика."""
    return {
        'ok': True,
        'count': cart.count(),
        'total_display': format_price(cart.get_total_price()),
        'item': item,
        'cart_html': render_to_string('cart/_drawer.html', {'cart': cart}, request=request),
        'message': message,
    }


def error_payload(message):
    """Очікуваний бізнес-стан, а не збій: статус лишається 200.

    Бракує двох одиниць на складі — це нормальна відповідь системи, і
    фронтенду простіше показати її як повідомлення, ніж ловити 4xx.
    """
    return {'ok': False, 'error': message}

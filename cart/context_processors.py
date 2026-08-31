"""Робить кошик доступним у кожному шаблоні — для лічильника в шапці сайту."""

from django.conf import settings
from django.utils.functional import SimpleLazyObject

from .cart import get_cart

# Префікси, на яких кошик не потрібен узагалі: адмінка має власну шапку,
# а медіа й статику віддає сервер без участі шаблонів.
IGNORED_PREFIXES = ('/admin/', settings.STATIC_URL, settings.MEDIA_URL)


def cart(request):
    """Кошик у контекст — але ліниво.

    `SimpleLazyObject` відкладає створення до першого звертання з шаблону.
    Сторінки, які кошика не показують (адмінка, JSON-ендпоінти, 404),
    не роблять через нього жодного запиту: раніше кожен рендер будь-якої
    сторінки коштував SELECT, а першого разу ще й INSERT у `cart_cart`.
    """
    if any(request.path.startswith(prefix) for prefix in IGNORED_PREFIXES if prefix):
        return {}

    return {'cart': SimpleLazyObject(lambda: get_cart(request))}

"""Views кошика: перегляд, додавання, оновлення кількості та видалення.

Кожен ендпоінт працює у двох режимах. Звичайний POST з форми — як і раніше:
дія, повідомлення, редірект. POST із `X-Requested-With: XMLHttpRequest` або
`Accept: application/json` — той самий результат у JSON.

Це прогресивне покращення, а не два різні API: без JavaScript магазин
лишається повністю робочим, включно з оформленням замовлення.
"""

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from shop.models import Product

from .cart import get_cart
from .services import (
    MAX_QUANTITY_PER_PRODUCT,
    cart_payload,
    error_payload,
    item_payload,
    quoted,
    validate_quantity,
    wants_json,
)


def _parse_quantity(request, default=1):
    """Дістати кількість з POST-запиту, не впавши на сміттєвих даних."""
    try:
        return int(request.POST.get('quantity', default))
    except (TypeError, ValueError):
        return default


def _respond(request, cart, message, item=None, redirect_to='cart:cart_detail', **kwargs):
    """Успішна відповідь у форматі, якого чекає клієнт."""
    if wants_json(request):
        return JsonResponse(cart_payload(request, cart, message=message, item=item))

    messages.success(request, message)
    return redirect(redirect_to, **kwargs)


def _reject(request, cart, error, redirect_to='cart:cart_detail', **kwargs):
    """Відмова: для JSON — ok=false зі статусом 200, для форми — повідомлення."""
    if wants_json(request):
        return JsonResponse(error_payload(error))

    messages.error(request, error)
    return redirect(redirect_to, **kwargs)


def cart_detail(request):
    """Сторінка кошика."""
    cart = get_cart(request)
    return render(
        request,
        'cart/detail.html',
        {'cart': cart, 'max_quantity': MAX_QUANTITY_PER_PRODUCT},
    )


@require_POST
def cart_add(request, product_id):
    """Додати товар у кошик."""
    cart = get_cart(request)
    product = get_object_or_404(Product, id=product_id)

    if not product.is_in_stock:
        return _reject(
            request,
            cart,
            f'Товару {quoted(product.name)} немає в наявності',
            redirect_to='shop:product_detail',
            slug=product.slug,
        )

    quantity, error = validate_quantity(cart, product, _parse_quantity(request))
    if error:
        return _reject(request, cart, error, redirect_to='shop:product_detail', slug=product.slug)

    cart.add(product=product, quantity=quantity)

    return _respond(
        request,
        cart,
        f'Товар {quoted(product.name)} додано до кошика',
        item=item_payload(cart, product),
    )


@require_POST
def cart_update(request, product_id):
    """Оновити кількість товару в кошику; кількість 0 означає видалення."""
    cart = get_cart(request)
    product = get_object_or_404(Product, id=product_id)
    quantity = _parse_quantity(request)

    if quantity <= 0:
        cart.remove(product)
        return _respond(request, cart, f'Товар {quoted(product.name)} видалено з кошика')

    # Оновлення задає кількість, а не додає до неї.
    quantity, error = validate_quantity(cart, product, quantity, absolute=True)
    if error:
        return _reject(request, cart, error)

    cart.add(product=product, quantity=quantity, update_quantity=True)
    return _respond(request, cart, 'Кошик оновлено', item=item_payload(cart, product))


@require_POST
def cart_remove(request, product_id):
    """Видалити товар з кошика."""
    cart = get_cart(request)
    product = get_object_or_404(Product, id=product_id)
    cart.remove(product)

    return _respond(request, cart, f'Товар {quoted(product.name)} видалено з кошика')


@require_POST
def cart_clear(request):
    """Повністю очистити кошик."""
    cart = get_cart(request)
    cart.clear()

    return _respond(request, cart, 'Кошик очищено')

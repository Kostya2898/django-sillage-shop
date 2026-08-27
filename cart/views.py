"""Views кошика: перегляд, додавання, оновлення кількості та видалення."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from shop.models import Product

from .cart import get_cart

# Максимальна кількість одного товару в кошику (вимога практичного завдання).
MAX_QUANTITY_PER_PRODUCT = 99


def _parse_quantity(request, default=1):
    """Дістати кількість з POST-запиту, не впавши на сміттєвих даних."""
    try:
        return int(request.POST.get('quantity', default))
    except (TypeError, ValueError):
        return default


def _headroom_message(product, in_cart, limit, reason):
    """Повідомлення про відмову, яке одразу каже, що можна зробити далі."""
    available = max(limit - in_cart, 0)

    if available:
        return f'{reason} У кошику вже {in_cart} — можна додати ще {available}.'
    return f'{reason} У кошику вже {in_cart}, більше додати не можна.'


def _validate_quantity(cart, product, quantity, absolute=False):
    """Перевірити кількість. Повертає (кількість, помилка_чи_None).

    Ключове: звіряємо зі складом **підсумок у кошику після дії**, а не число
    із запиту. Інакше «додати 5» двічі при залишку 6 проходить обидва рази,
    і брак товару виявляється аж на checkout.

    `absolute=True` — це «встановити кількість» (cart_update), тобто підсумком
    є саме передане число. `absolute=False` — «додати до наявного».
    """
    if quantity < 1:
        return None, 'Кількість має бути більшою за 0'

    in_cart = cart.get_quantity(product)
    resulting = quantity if absolute else in_cart + quantity

    if resulting > MAX_QUANTITY_PER_PRODUCT:
        reason = f'Максимальна кількість одного товару — {MAX_QUANTITY_PER_PRODUCT} шт.'
        if absolute:
            return None, reason
        return None, _headroom_message(product, in_cart, MAX_QUANTITY_PER_PRODUCT, reason)

    if resulting > product.stock:
        reason = f'На складі лишилось {product.stock} од. товару «{product.name}».'
        if absolute:
            return None, reason
        return None, _headroom_message(product, in_cart, product.stock, reason)

    return quantity, None


def cart_detail(request):
    """Сторінка кошика."""
    cart = get_cart(request)
    return render(
        request,
        'cart/detail.html',
        {
            'cart': cart,
            'max_quantity': MAX_QUANTITY_PER_PRODUCT,
        },
    )


@require_POST
def cart_add(request, product_id):
    """Додати товар у кошик."""
    cart = get_cart(request)
    product = get_object_or_404(Product, id=product_id)

    if not product.is_in_stock:
        messages.error(request, f'Товару «{product.name}» немає в наявності')
        return redirect('shop:product_detail', slug=product.slug)

    quantity = _parse_quantity(request)
    quantity, error = _validate_quantity(cart, product, quantity)
    if error:
        messages.error(request, error)
        return redirect('shop:product_detail', slug=product.slug)

    cart.add(product=product, quantity=quantity)
    messages.success(request, f'Товар «{product.name}» додано до кошика')
    return redirect('cart:cart_detail')


@require_POST
def cart_update(request, product_id):
    """Оновити кількість товару в кошику; кількість 0 означає видалення."""
    cart = get_cart(request)
    product = get_object_or_404(Product, id=product_id)
    quantity = _parse_quantity(request)

    if quantity <= 0:
        cart.remove(product)
        messages.success(request, f'Товар «{product.name}» видалено з кошика')
        return redirect('cart:cart_detail')

    # Оновлення задає кількість, а не додає до неї.
    quantity, error = _validate_quantity(cart, product, quantity, absolute=True)
    if error:
        messages.error(request, error)
        return redirect('cart:cart_detail')

    cart.add(product=product, quantity=quantity, update_quantity=True)
    messages.success(request, 'Кошик оновлено')
    return redirect('cart:cart_detail')


@require_POST
def cart_remove(request, product_id):
    """Видалити товар з кошика."""
    cart = get_cart(request)
    product = get_object_or_404(Product, id=product_id)
    cart.remove(product)

    messages.success(request, f'Товар «{product.name}» видалено з кошика')
    return redirect('cart:cart_detail')


@require_POST
def cart_clear(request):
    """Повністю очистити кошик."""
    get_cart(request).clear()
    messages.success(request, 'Кошик очищено')
    return redirect('cart:cart_detail')

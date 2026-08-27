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


def _clamp_quantity(request, product, quantity):
    """Перевірити кількість. Повертає (кількість, помилка_чи_None)."""
    if quantity < 1:
        return None, 'Кількість має бути більшою за 0'

    if quantity > MAX_QUANTITY_PER_PRODUCT:
        return None, f'Максимальна кількість одного товару — {MAX_QUANTITY_PER_PRODUCT} шт.'

    if quantity > product.stock:
        return None, f'Доступно тільки {product.stock} од. товару «{product.name}»'

    return quantity, None


def cart_detail(request):
    """Сторінка кошика."""
    cart = get_cart(request)
    return render(request, 'cart/detail.html', {
        'cart': cart,
        'max_quantity': MAX_QUANTITY_PER_PRODUCT,
    })


@require_POST
def cart_add(request, product_id):
    """Додати товар у кошик."""
    cart = get_cart(request)
    product = get_object_or_404(Product, id=product_id)

    if not product.is_in_stock:
        messages.error(request, f'Товару «{product.name}» немає в наявності')
        return redirect('shop:product_detail', slug=product.slug)

    quantity = _parse_quantity(request)
    quantity, error = _clamp_quantity(request, product, quantity)
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

    quantity, error = _clamp_quantity(request, product, quantity)
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

"""Checkout-процес та історія замовлень.

Потік:
    /orders/checkout/          → вибір або створення адреси доставки
    /orders/checkout/confirm/  → підсумок, спосіб оплати, підтвердження
    /orders/success/<номер>/   → сторінка успіху
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render

from cart.cart import get_cart
from shop.models import Product

from .emails import notify_admins_about_order, send_order_confirmation_email
from .forms import OrderCheckoutForm, ShippingAddressForm
from .models import Order, OrderItem, OrderStatusHistory, ShippingAddress

SESSION_ADDRESS_KEY = 'shipping_address_id'


@login_required
def checkout(request):
    """Крок 1: вибір існуючої або додавання нової адреси доставки."""
    cart = get_cart(request)

    if len(cart) == 0:
        messages.warning(request, 'Ваш кошик порожній')
        return redirect('shop:product_list')

    addresses = ShippingAddress.objects.filter(user=request.user)
    form = ShippingAddressForm()

    if request.method == 'POST':
        if 'select_address' in request.POST:
            address = get_object_or_404(
                ShippingAddress,
                id=request.POST.get('address_id'),
                user=request.user,
            )
            request.session[SESSION_ADDRESS_KEY] = address.id
            return redirect('orders:checkout_confirm')

        form = ShippingAddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.user = request.user
            address.save()

            request.session[SESSION_ADDRESS_KEY] = address.id
            messages.success(request, 'Адресу додано успішно')
            return redirect('orders:checkout_confirm')

        messages.error(request, 'Перевірте, будь ласка, поля форми')

    return render(request, 'orders/checkout.html', {
        'cart': cart,
        'addresses': addresses,
        'form': form,
    })


@login_required
def checkout_confirm(request):
    """Крок 2: підсумок замовлення та його створення."""
    cart = get_cart(request)

    if len(cart) == 0:
        messages.warning(request, 'Ваш кошик порожній')
        return redirect('shop:product_list')

    address_id = request.session.get(SESSION_ADDRESS_KEY)
    if not address_id:
        messages.warning(request, 'Будь ласка, оберіть адресу доставки')
        return redirect('orders:checkout')

    address = get_object_or_404(ShippingAddress, id=address_id, user=request.user)
    form = OrderCheckoutForm()

    if request.method == 'POST':
        form = OrderCheckoutForm(request.POST)
        if form.is_valid():
            try:
                order = create_order(
                    user=request.user,
                    cart=cart,
                    address=address,
                    payment_method=form.cleaned_data['payment_method'],
                    notes=form.cleaned_data['notes'],
                )
            except ValueError as exc:
                # Транзакція вже відкотилася: ані замовлення, ані списання складу.
                messages.error(request, f'Не вдалося створити замовлення: {exc}')
                return redirect('cart:cart_detail')

            send_order_confirmation_email(order)
            notify_admins_about_order(order)

            cart.clear()
            request.session.pop(SESSION_ADDRESS_KEY, None)

            messages.success(request, f'Замовлення #{order.order_number} успішно створено!')

            if order.requires_online_payment:
                return redirect('payments:initiate_payment', order_number=order.order_number)
            return redirect('orders:order_success', order_number=order.order_number)

    return render(request, 'orders/checkout_confirm.html', {
        'cart': cart,
        'address': address,
        'form': form,
    })


@transaction.atomic
def create_order(user, cart, address, payment_method, notes=''):
    """Створити замовлення з вмісту кошика.

    Уся функція виконується в одній транзакції: якщо на будь-якому товарі
    забракне залишку, база відкотиться до стану «замовлення не було».
    Саме тому ми не ковтаємо виняток тут, а прокидаємо його у view —
    `except` всередині `atomic` не скасував би транзакцію.
    """
    items = list(cart)
    if not items:
        raise ValueError('кошик порожній')

    order = Order.objects.create(
        user=user,
        shipping_full_name=address.full_name,
        shipping_phone=address.phone,
        shipping_country=address.country,
        shipping_city=address.city,
        shipping_postal_code=address.postal_code,
        shipping_address_line1=address.address_line1,
        shipping_address_line2=address.address_line2,
        total_amount=cart.get_total_price(),
        payment_method=payment_method,
        notes=notes,
    )

    for item in items:
        # select_for_update блокує рядок товару до кінця транзакції,
        # щоб двоє покупців не «купили» один і той самий останній екземпляр.
        product = Product.objects.select_for_update().get(pk=item['product'].pk)

        if product.stock < item['quantity']:
            raise ValueError(f'недостатньо товару «{product.name}» на складі')

        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            price=product.price,
            quantity=item['quantity'],
        )

        # F() рахує нове значення на боці бази — без гонок «прочитав-змінив-записав».
        Product.objects.filter(pk=product.pk).update(stock=F('stock') - item['quantity'])

    OrderStatusHistory.objects.create(
        order=order,
        status=Order.STATUS_PENDING,
        note=f'Замовлення створено. Спосіб оплати: {order.get_payment_method_display()}',
        created_by=user,
    )

    return order


@login_required
def order_success(request, order_number):
    """Сторінка «дякуємо за замовлення»."""
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    return render(request, 'orders/order_success.html', {'order': order})


@login_required
def order_list(request):
    """Історія замовлень користувача."""
    orders = (
        Order.objects.filter(user=request.user)
        .prefetch_related('items')
        .order_by('-created_at')
    )
    return render(request, 'orders/order_list.html', {'orders': orders})


@login_required
def order_detail(request, order_number):
    """Деталі одного замовлення."""
    order = get_object_or_404(
        Order.objects.select_related('user').prefetch_related('items', 'status_history'),
        order_number=order_number,
        user=request.user,
    )
    return render(request, 'orders/order_detail.html', {'order': order})

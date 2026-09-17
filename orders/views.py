"""Checkout-процес та історія замовлень.

Потік:
    /orders/checkout/          → роздоріжжя для гостя, далі адреса доставки
    /orders/checkout/confirm/  → доставка, промокод, оплата, підтвердження
    /orders/success/<номер>/   → сторінка успіху

Реєстрація на шляху до оплати не потрібна. Це не «фіча заради фічі»: вимога
створити акаунт — найпоширеніша причина покинутого кошика, і кожен зайвий
екран між «хочу» і «купив» коштує магазину частини виторгу. Тому гість
проходить той самий шлях, а акаунт йому пропонують після, а не замість.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from cart.cart import get_cart
from cart.models import Cart
from shop.models import Product
from shop_project.ratelimit import LIMITS

from .emails import notify_admins_about_order, send_order_confirmation_email
from .forms import (
    ADDRESS_FIELDS,
    CouponForm,
    GuestCheckoutForm,
    OrderCheckoutForm,
    ShippingAddressForm,
)
from .models import Coupon, Order, OrderItem, OrderStatusHistory, ShippingAddress
from .pdf import InvoiceRenderError, invoice_filename, render_order_invoice
from .services import (
    ADDRESS_SESSION_KEY,
    GUEST_ADDRESS_SESSION_KEY,
    GUEST_MODE_SESSION_KEY,
    apply_coupon,
    available_delivery_methods,
    calculate_totals,
    checkout_reset,
    clear_coupon,
    get_applied_coupon,
    get_order_for_request,
    get_selected_delivery,
    remember_guest_order,
    select_delivery,
)

SESSION_ADDRESS_KEY = ADDRESS_SESSION_KEY


# ---------------------------------------------------------------------------
# Спільне для кроків checkout
# ---------------------------------------------------------------------------


def _cart_or_redirect(request):
    """Кошик, якщо в ньому щось є. Інакше — редірект у каталог.

    Порожній кошик на checkout — це або подвійне відправлення форми, або
    повернення «назад» після покупки. В обох випадках правильна відповідь —
    відправити людину туди, де є що покласти.
    """
    cart = get_cart(request)
    if len(cart) == 0:
        messages.warning(request, 'У кошику поки порожньо — почніть із каталогу')
        return None, redirect('shop:product_list')
    return cart, None


def _is_guest_checkout(request):
    return not request.user.is_authenticated and request.session.get(GUEST_MODE_SESSION_KEY)


def _guest_address(request):
    """Незбережена `ShippingAddress` з даних гостя в сесії.

    Обʼєкт навмисно не пишеться в базу: `create_order` читає з нього ті самі
    атрибути, що й зі справжньої адреси, а в адресну книгу гостя не заводимо.
    """
    data = request.session.get(GUEST_ADDRESS_SESSION_KEY)
    if not data:
        return None
    return ShippingAddress(**{name: data.get(name, '') for name in ADDRESS_FIELDS})


def _checkout_context(request, cart, **extra):
    """Підсумок із урахуванням промокоду й доставки — однаковий на всіх кроках."""
    items_total = cart.get_total_price()
    coupon = get_applied_coupon(request, items_total)
    delivery = get_selected_delivery(request)
    totals = calculate_totals(items_total, coupon, delivery)

    context = {
        'cart': cart,
        'coupon': coupon,
        'coupon_form': CouponForm(),
        'delivery': delivery,
        'totals': totals,
        'is_guest': _is_guest_checkout(request),
    }
    context.update(extra)
    return context


# ---------------------------------------------------------------------------
# Крок 0: хто ви
# ---------------------------------------------------------------------------


def checkout_identity(request):
    """Роздоріжжя для незалогіненого покупця: увійти, зареєструватись, гостем.

    Три рівноправні виходи на одному екрані. «Продовжити як гість» тут —
    не дрібний посилання внизу, а така сама кнопка, як решта: сховати її
    означає повернути той самий бар'єр, заради зняття якого все це й робиться.
    """
    if request.user.is_authenticated:
        return redirect('orders:checkout')

    cart, bail = _cart_or_redirect(request)
    if bail:
        return bail

    if request.method == 'POST':
        request.session[GUEST_MODE_SESSION_KEY] = True
        return redirect('orders:checkout')

    return render(request, 'orders/checkout_identity.html', _checkout_context(request, cart))


# ---------------------------------------------------------------------------
# Крок 1: адреса
# ---------------------------------------------------------------------------


def checkout(request):
    """Крок 1: вибір існуючої або введення нової адреси доставки."""
    cart, bail = _cart_or_redirect(request)
    if bail:
        return bail

    if not request.user.is_authenticated and not _is_guest_checkout(request):
        return redirect('orders:checkout_identity')

    if _is_guest_checkout(request):
        return _checkout_guest_address(request, cart)

    return _checkout_user_address(request, cart)


def _checkout_guest_address(request, cart):
    """Адреса гостя: одна форма, нічого не зберігається в адресну книгу."""
    initial = request.session.get(GUEST_ADDRESS_SESSION_KEY) or {}
    form = GuestCheckoutForm(initial=initial)

    if request.method == 'POST':
        form = GuestCheckoutForm(request.POST)
        if form.is_valid():
            # У сесію кладемо і email — на кроці підтвердження він знадобиться
            # знову, а повторно питати те, що людина вже ввела, не можна.
            request.session[GUEST_ADDRESS_SESSION_KEY] = {
                **form.address_data(),
                'email': form.cleaned_data['email'],
            }
            return redirect('orders:checkout_confirm')

        messages.error(request, 'Перевірте, будь ласка, підсвічені поля')

    return render(
        request,
        'orders/checkout_guest.html',
        _checkout_context(request, cart, form=form, step=2, steps_total=3),
    )


def _checkout_user_address(request, cart):
    """Адреса залогіненого покупця: адресна книга або нова адреса."""
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

    return render(
        request,
        'orders/checkout.html',
        _checkout_context(request, cart, addresses=addresses, form=form, step=1, steps_total=2),
    )


# ---------------------------------------------------------------------------
# Крок 2: підтвердження
# ---------------------------------------------------------------------------


def checkout_confirm(request):
    """Крок 2: доставка, оплата, підсумок і створення замовлення."""
    cart, bail = _cart_or_redirect(request)
    if bail:
        return bail

    guest = _is_guest_checkout(request)

    if guest:
        address = _guest_address(request)
        guest_email = (request.session.get(GUEST_ADDRESS_SESSION_KEY) or {}).get('email', '')
    else:
        if not request.user.is_authenticated:
            return redirect('orders:checkout_identity')
        address_id = request.session.get(SESSION_ADDRESS_KEY)
        address = (
            get_object_or_404(ShippingAddress, id=address_id, user=request.user)
            if address_id
            else None
        )
        guest_email = ''

    if address is None:
        messages.warning(request, 'Будь ласка, вкажіть адресу доставки')
        return redirect('orders:checkout')

    methods = available_delivery_methods()
    form = OrderCheckoutForm(
        delivery_methods=methods,
        initial={'delivery_method': get_selected_delivery(request)},
    )

    if request.method == 'POST':
        form = OrderCheckoutForm(request.POST, delivery_methods=methods)
        if form.is_valid():
            delivery = form.cleaned_data.get('delivery_method')
            if delivery:
                select_delivery(request, delivery)

            coupon = get_applied_coupon(request, cart.get_total_price())

            try:
                order = create_order(
                    user=request.user if request.user.is_authenticated else None,
                    cart=cart,
                    address=address,
                    payment_method=form.cleaned_data['payment_method'],
                    notes=form.cleaned_data['notes'],
                    coupon=coupon,
                    delivery=delivery,
                    guest_email=guest_email,
                    guest_phone=address.phone if guest else '',
                )
            except ValueError as exc:
                # Транзакція вже відкотилася: ані замовлення, ані списання складу.
                messages.error(request, f'Не вдалося створити замовлення: {exc}')
                return redirect('cart:cart_detail')

            if order.is_guest_order:
                # Єдиний спосіб для гостя повернутись до замовлення в цьому
                # ж браузері: у листі буде ще й підписане посилання.
                remember_guest_order(request, order)

            # Обидві функції ковтають власні помилки й повертають булеве —
            # недоступна пошта не має обвалювати вже оформлену покупку.
            #
            # Викликаються вони **після** `create_order`, тобто поза його
            # `atomic`: транзакція вже закомічена, замовлення справді існує.
            # Заносити ці рядки всередину `create_order` не можна — при відкоті
            # лист уже пішов би, а замовлення не було б. З тієї ж причини
            # `ATOMIC_REQUESTS` має лишатись вимкненим: він обгорнув би весь
            # view в одну транзакцію і зламав би цю гарантію.
            letter_sent = send_order_confirmation_email(order)
            notify_admins_about_order(order)

            cart.clear()
            checkout_reset(request)

            if letter_sent:
                messages.success(request, f'Замовлення #{order.order_number} успішно створено!')
            else:
                # Кажемо, що сталося, і одразу — куди йти далі.
                messages.warning(
                    request,
                    f'Замовлення #{order.order_number} прийнято. Лист із деталями '
                    f'надішлемо трохи згодом — саме замовлення вже збережено, '
                    f'воно є в розділі «Мої замовлення».',
                )

            if order.requires_online_payment:
                return redirect('payments:initiate_payment', order_number=order.order_number)
            return redirect('orders:order_success', order_number=order.order_number)

    return render(
        request,
        'orders/checkout_confirm.html',
        _checkout_context(
            request,
            cart,
            address=address,
            form=form,
            delivery_methods=methods,
            step=3 if guest else 2,
            steps_total=3 if guest else 2,
        ),
    )


@transaction.atomic
def create_order(
    user,
    cart,
    address,
    payment_method,
    notes='',
    coupon=None,
    delivery=None,
    guest_email='',
    guest_phone='',
):
    """Створити замовлення з вмісту кошика.

    Уся функція виконується в одній транзакції: якщо на будь-якому товарі
    забракне залишку, база відкотиться до стану «замовлення не було».
    Саме тому ми не ковтаємо виняток тут, а прокидаємо його у view —
    `except` всередині `atomic` не скасував би транзакцію.

    `user=None` означає гостьову покупку: тоді обовʼязковий `guest_email`,
    інакше замовлення нікому буде показати й нікуди надіслати.
    """
    items = list(cart)
    if not items:
        raise ValueError('кошик порожній')

    if user is None and not guest_email:
        raise ValueError('для гостьового замовлення потрібен email')

    # Записуємо рядок кошика в замовлення, щоб оплата потім закрила саме його.
    #
    # Перевірка типу тут обовʼязкова, а не «про всяк випадок»: атрибут `cart`
    # є в обох класів кошика, але в `SessionCart` це звичайний dict із сесії,
    # а не рядок таблиці. Поки checkout був лише для залогінених, сюди
    # потрапляв тільки `DatabaseCart`, і різниця не стріляла.
    cart_instance = getattr(cart, 'cart', None)
    if not isinstance(cart_instance, Cart):
        cart_instance = None

    totals = calculate_totals(cart.get_total_price(), coupon=coupon, delivery=delivery)

    order = Order.objects.create(
        user=user,
        guest_email=guest_email,
        guest_phone=guest_phone,
        cart=cart_instance,
        shipping_full_name=address.full_name,
        shipping_phone=address.phone,
        shipping_country=address.country,
        shipping_city=address.city,
        shipping_postal_code=address.postal_code,
        shipping_address_line1=address.address_line1,
        shipping_address_line2=address.address_line2,
        items_total=totals.items_total,
        coupon=coupon,
        coupon_code=coupon.code if coupon else '',
        discount_amount=totals.discount,
        delivery_method=delivery,
        delivery_name=delivery.name if delivery else '',
        delivery_price=totals.delivery,
        estimated_delivery_date=delivery.estimated_date() if delivery else None,
        total_amount=totals.total,
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

    if coupon is not None:
        _consume_coupon(coupon)

    OrderStatusHistory.objects.create(
        order=order,
        status=Order.STATUS_PENDING,
        note=f'Замовлення створено. Спосіб оплати: {order.get_payment_method_display()}',
        created_by=user,
    )

    return order


def _consume_coupon(coupon):
    """Списати одне використання промокоду.

    Блокуємо рядок і перечитуємо лічильник: між перевіркою купона на сторінці
    й натисканням «Підтвердити» ліміт міг вичерпати хтось інший, і без
    блокування останнім купоном скористалися б двоє.
    """
    locked = Coupon.objects.select_for_update().get(pk=coupon.pk)

    if locked.max_uses and locked.used_count >= locked.max_uses:
        raise ValueError(f'промокод «{locked.code}» щойно вичерпав ліміт використань')

    Coupon.objects.filter(pk=coupon.pk).update(used_count=F('used_count') + 1)


# ---------------------------------------------------------------------------
# Промокод
# ---------------------------------------------------------------------------


@require_POST
@ratelimit(
    group='orders:coupon_apply',
    key='ip',
    rate=LIMITS['orders:coupon_apply'].rate,
    method='POST',
    block=True,
)
def coupon_apply(request):
    """Застосувати промокод до поточного кошика."""
    cart = get_cart(request)
    form = CouponForm(request.POST)

    if form.is_valid():
        coupon, error = apply_coupon(request, form.cleaned_data['code'], cart.get_total_price())
        if error:
            messages.error(request, error)
        else:
            messages.success(
                request, f'Промокод «{coupon.code}» застосовано: {coupon.get_discount_display()}'
            )

    return redirect(request.POST.get('next') or 'cart:cart_detail')


@require_POST
def coupon_remove(request):
    """Прибрати промокод."""
    clear_coupon(request)
    messages.info(request, 'Промокод прибрано')
    return redirect(request.POST.get('next') or 'cart:cart_detail')


# ---------------------------------------------------------------------------
# Замовлення
# ---------------------------------------------------------------------------


def order_success(request, order_number):
    """Сторінка «дякуємо за замовлення». Доступна і гостю."""
    order = get_order_for_request(request, order_number)
    return render(request, 'orders/order_success.html', {'order': order})


@login_required
def order_list(request):
    """Історія замовлень користувача."""
    orders = (
        Order.objects.filter(user=request.user).prefetch_related('items').order_by('-created_at')
    )
    return render(request, 'orders/order_list.html', {'orders': orders})


def order_detail(request, order_number):
    """Деталі одного замовлення. Доступні власнику або гостю з його сесії."""
    order = get_order_for_request(
        request,
        order_number,
        queryset=Order.objects.select_related('user', 'delivery_method').prefetch_related(
            'items', 'status_history'
        ),
    )
    return render(request, 'orders/order_detail.html', {'order': order})


@require_POST
def order_cancel(request, order_number):
    """Скасувати власне замовлення й повернути товари на склад."""
    order = get_order_for_request(request, order_number)

    if not order.can_be_cancelled():
        messages.error(
            request,
            'Це замовлення вже не можна скасувати самостійно. Напишіть нам — '
            'розберемось окремо.',
        )
        return redirect('orders:order_detail', order_number=order.order_number)

    order.cancel(
        by_user=request.user if request.user.is_authenticated else None,
        note='Скасовано покупцем',
    )
    messages.success(
        request,
        f'Замовлення #{order.order_number} скасовано, товари повернулись у продаж.',
    )
    return redirect('orders:order_detail', order_number=order.order_number)


def order_invoice(request, order_number):
    """Рахунок у PDF."""
    order = get_order_for_request(
        request, order_number, queryset=Order.objects.select_related('user')
    )

    try:
        content = render_order_invoice(order)
    except InvoiceRenderError:
        messages.error(request, 'Не вдалося зібрати рахунок. Ми вже знаємо про це.')
        return redirect('orders:order_detail', order_number=order.order_number)

    response = HttpResponse(content, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{invoice_filename(order)}"'
    return response

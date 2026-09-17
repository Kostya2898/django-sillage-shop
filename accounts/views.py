"""Реєстрація, вхід та кабінет користувача."""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django_ratelimit.decorators import ratelimit

from orders.models import Order
from shop_project.ratelimit import LIMITS

from .forms import SignUpForm, UserAccountForm, UserProfileForm


@ratelimit(
    group='accounts:signup',
    key='ip',
    rate=LIMITS['accounts:signup'].rate,
    method='POST',
    block=True,
)
def signup(request):
    """Реєстрація нового користувача з автоматичним входом."""
    if request.user.is_authenticated:
        return redirect('shop:product_list')

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            # login() посилає сигнал user_logged_in, який переносить
            # гостьовий кошик у базу — див. accounts/signals.py.
            login(request, user)
            messages.success(request, f'Вітаємо, {user.username}! Реєстрація успішна.')
            return redirect('shop:product_list')
    else:
        form = SignUpForm()

    return render(request, 'accounts/signup.html', {'form': form})


@login_required
def profile(request):
    """Кабінет: контактні дані, налаштування профілю та історія замовлень."""
    # Профіль створює сигнал post_save на користувачі, тож він завжди існує.
    user_profile = request.user.profile

    if request.method == 'POST':
        account_form = UserAccountForm(request.POST, instance=request.user)
        profile_form = UserProfileForm(request.POST, request.FILES, instance=user_profile)

        if account_form.is_valid() and profile_form.is_valid():
            account_form.save()
            profile_form.save()
            messages.success(request, 'Профіль оновлено')
            return redirect('accounts:profile')

        messages.error(request, 'Перевірте, будь ласка, поля форми')
    else:
        account_form = UserAccountForm(instance=request.user)
        profile_form = UserProfileForm(instance=user_profile)

    orders = (
        Order.objects.filter(user=request.user)
        .prefetch_related('items')
        .order_by('-created_at')[:10]
    )

    return render(
        request,
        'accounts/profile.html',
        {
            'account_form': account_form,
            'profile_form': profile_form,
            'profile': user_profile,
            'orders': orders,
        },
    )

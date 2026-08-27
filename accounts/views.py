"""Реєстрація, вхід та сторінка профілю користувача."""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from orders.models import Order

from .forms import SignUpForm, UserProfileForm
from .models import UserProfile


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
    """Профіль користувача: контактні дані та історія замовлень."""
    user_profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=user_profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Профіль оновлено')
            return redirect('accounts:profile')
    else:
        form = UserProfileForm(instance=user_profile)

    orders = (
        Order.objects.filter(user=request.user)
        .prefetch_related('items')
        .order_by('-created_at')[:10]
    )

    return render(request, 'accounts/profile.html', {
        'form': form,
        'profile': user_profile,
        'orders': orders,
    })

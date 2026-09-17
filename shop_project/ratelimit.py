"""Обмеження частоти запитів: ліміти, IP клієнта і відповідь на перевищення.

Ліміт, повідомлення і `Retry-After` для кожного ендпойнта лежать в одній
таблиці. Розкидані по декораторах і шаблонах, вони розходяться: декоратор
пускає раз на годину, а сторінка просить «спробувати за хвилину».
"""

from dataclasses import dataclass

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render


@dataclass(frozen=True)
class Limit:
    rate: str
    retry_after: int
    message: str


LIMITS = {
    # Підбір пароля: п'ять спроб — із запасом на опечатки, але замало для
    # перебору.
    'accounts:login': Limit(
        rate='5/15m',
        retry_after=15 * 60,
        message='Забагато спроб входу з цієї адреси. Спробуйте ще раз за 15 хвилин.',
    ),
    'accounts:signup': Limit(
        rate='5/h',
        retry_after=60 * 60,
        message='Забагато реєстрацій з цієї адреси. Спробуйте ще раз за годину.',
    ),
    # Живий пошук шле запит після паузи в наборі, тож людина за хвилину
    # робить кільканадцять запитів. Тридцять відсікає скрипт, а не читача.
    'shop:product_search': Limit(
        rate='30/m',
        retry_after=60,
        message='Забагато пошукових запитів. Зачекайте хвилину.',
    ),
    # Промокод — це секрет, який можна перебирати. Покупцеві вистачає
    # двох-трьох спроб; десять на годину — стеля для перебору.
    'orders:coupon_apply': Limit(
        rate='10/h',
        retry_after=60 * 60,
        message='Забагато спроб застосувати промокод. Спробуйте ще раз за годину.',
    ),
}

DEFAULT_MESSAGE = 'Забагато запитів. Спробуйте трохи пізніше.'


def client_ip(request):
    """IP клієнта, на який рахується ліміт.

    За проксі `REMOTE_ADDR` — адреса самого проксі, спільна для всіх, і
    перший же зловмисник вичерпав би ліміт входу за всіх покупців одразу.
    Тоді адресу беремо з `X-Forwarded-For`, але **останню** в списку: її
    дописав наш проксі. Першу може вписати сам клієнт і міняти на кожен
    запит, обходячи ліміт.

    Без проксі заголовку не довіряємо зовсім — його підробляє будь-хто.
    """
    if getattr(settings, 'RATELIMIT_TRUST_PROXY', False):
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        chain = [part.strip() for part in forwarded.split(',') if part.strip()]
        if chain:
            return chain[-1]

    return request.META['REMOTE_ADDR']


def limited(request, exception):
    """Відповідь на перевищення ліміту: 429 з поясненням, а не 403 чи 500."""
    match = getattr(request, 'resolver_match', None)
    limit = LIMITS.get(match.view_name) if match else None
    message = limit.message if limit else DEFAULT_MESSAGE

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        response = JsonResponse({'ok': False, 'error': message}, status=429)
    else:
        response = render(request, '429.html', {'message': message}, status=429)

    if limit:
        response['Retry-After'] = str(limit.retry_after)

    return response

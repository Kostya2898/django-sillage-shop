"""Налаштування для локальної розробки.

Модуль за замовчуванням: `manage.py`, `wsgi.py` і `asgi.py` беруть саме його,
якщо `DJANGO_SETTINGS_MODULE` не задано явно.

Проєкт має запускатися і без файлу `.env` — усі дефолти нижче безпечні,
бо ніколи не потрапляють у production.
"""

import importlib.util
import sys

from .base import *  # noqa: F403
from .base import INSTALLED_APPS, MIDDLEWARE, env

# ---------------------------------------------------------------------------
# Основне
# ---------------------------------------------------------------------------

DEBUG = env.bool('DEBUG', default=True)

SECRET_KEY = env('SECRET_KEY', default='dev-only-insecure-key-change-me')

ALLOWED_HOSTS = env.list(
    'ALLOWED_HOSTS',
    default=['localhost', '127.0.0.1', '[::1]', 'testserver'],
)


# ---------------------------------------------------------------------------
# Інструменти розробника
# ---------------------------------------------------------------------------


def _installed(module_name):
    """Чи стоїть пакет у поточному середовищі.

    Інструменти розробника лежать у requirements-dev.txt, а не в
    requirements.txt. Без цієї перевірки чистий venv, зібраний лише з
    production-залежностей, не підняв би навіть dev-сервер.
    """
    return importlib.util.find_spec(module_name) is not None


# Django під час тестів примусово ставить DEBUG=False, і Debug Toolbar на це
# лається помилкою E001. Панель у тестах усе одно ні до чого — просто не
# підключаємо її, заразом трохи швидший прогін.
RUNNING_TESTS = 'test' in sys.argv

INSTALLED_APPS = INSTALLED_APPS.copy()
MIDDLEWARE = MIDDLEWARE.copy()

if _installed('debug_toolbar') and not RUNNING_TESTS:
    INSTALLED_APPS.append('debug_toolbar')
    # Debug Toolbar має стояти якомога вище, але після SecurityMiddleware —
    # інакше він не побачить редіректів, які той робить.
    MIDDLEWARE.insert(1, 'debug_toolbar.middleware.DebugToolbarMiddleware')

if _installed('django_extensions'):
    INSTALLED_APPS.append('django_extensions')

INTERNAL_IPS = ['127.0.0.1']


def _show_toolbar(request):
    """Панель показується тільки в DEBUG і тільки для запитів з INTERNAL_IPS."""
    return DEBUG and request.META.get('REMOTE_ADDR') in INTERNAL_IPS


DEBUG_TOOLBAR_CONFIG = {
    'SHOW_TOOLBAR_CALLBACK': _show_toolbar,
    'SHOW_COLLAPSED': True,
}


# ---------------------------------------------------------------------------
# Пошта
# ---------------------------------------------------------------------------

# У розробці листи друкуються в консоль runserver — окремий SMTP не потрібен.
EMAIL_BACKEND = env(
    'EMAIL_BACKEND',
    default='django.core.mail.backends.console.EmailBackend',
)


# ---------------------------------------------------------------------------
# Кеш
# ---------------------------------------------------------------------------

# LocMem за замовчуванням: працює без Redis і скидається разом із процесом.
CACHES = {
    'default': env.cache_url('CACHE_URL', default='locmemcache://'),
}


# ---------------------------------------------------------------------------
# Логування
# ---------------------------------------------------------------------------

# У розробці показуємо докладний формат — з модулем і номером рядка.
LOGGING['handlers']['console']['formatter'] = 'verbose'  # noqa: F405

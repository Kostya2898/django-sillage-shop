"""Налаштування для production.

Модуль **не має** безпечних дефолтів там, де їх не може бути: без `SECRET_KEY`
і `ALLOWED_HOSTS` в оточенні запуск свідомо падає з `ImproperlyConfigured`,
а не стартує з ключем із репозиторію.

Запуск:
    set DJANGO_SETTINGS_MODULE=shop_project.settings.prod
    python manage.py check --deploy
"""

from .base import *  # noqa: F403
from .base import BASE_DIR, LOG_LEVEL, LOGGING, env

# ---------------------------------------------------------------------------
# Основне
# ---------------------------------------------------------------------------

DEBUG = False

# Без дефолту: якщо змінної немає — падаємо на старті, а не тихо працюємо
# з ключем, який лежить у git.
SECRET_KEY = env('SECRET_KEY')

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')

# Домени, яким довіряємо для CSRF (потрібно за проксі/HTTPS).
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])


# ---------------------------------------------------------------------------
# Безпека транспорту
# ---------------------------------------------------------------------------

SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=True)

# HSTS. Починати варто з малого значення (напр. 3600) і піднімати до року,
# коли переконаєшся, що весь сайт справді доступний по HTTPS.
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=True)
SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=True)

SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # шаблони читають токен із cookie для fetch-запитів
X_FRAME_OPTIONS = 'DENY'

# Якщо додаток стоїть за reverse-proxy (nginx, Traefik), який термінує TLS.
if env.bool('USE_X_FORWARDED_PROTO', default=False):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# ---------------------------------------------------------------------------
# Пошта
# ---------------------------------------------------------------------------

# У production консольний backend недопустимий — лист має реально піти.
EMAIL_BACKEND = env(
    'EMAIL_BACKEND',
    default='django.core.mail.backends.smtp.EmailBackend',
)


# ---------------------------------------------------------------------------
# Логування у файл із ротацією
# ---------------------------------------------------------------------------

LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING['handlers']['file'] = {
    'class': 'logging.handlers.RotatingFileHandler',
    'filename': str(LOG_DIR / 'app.log'),
    'maxBytes': 5 * 1024 * 1024,  # 5 МБ
    'backupCount': 5,
    'encoding': 'utf-8',
    'formatter': 'verbose',
    'level': LOG_LEVEL,
}

# Усі логери пишуть і в консоль (її збирає systemd/docker), і у файл.
LOGGING['root']['handlers'] = ['console', 'file']
for _logger in LOGGING['loggers'].values():
    _logger['handlers'] = ['console', 'file']

# Автоперезавантажувача в production немає, але глушник лишаємо про всяк випадок.
LOGGING['loggers']['django.utils.autoreload']['level'] = 'WARNING'

# Помилки 500 додатково йдуть на пошту ADMINS.
LOGGING['handlers']['mail_admins'] = {
    'class': 'django.utils.log.AdminEmailHandler',
    'level': 'ERROR',
    'include_html': False,
}
LOGGING['loggers']['django.request'] = {
    'handlers': ['console', 'file', 'mail_admins'],
    'level': 'ERROR',
    'propagate': False,
}

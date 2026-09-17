"""Налаштування для production.

Модуль **не має** безпечних дефолтів там, де їх не може бути: без `SECRET_KEY`
і `ALLOWED_HOSTS` в оточенні запуск свідомо падає з `ImproperlyConfigured`,
а не стартує з ключем із репозиторію.

Запуск:
    set DJANGO_SETTINGS_MODULE=shop_project.settings.prod
    python manage.py check --deploy
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import BASE_DIR, LOG_LEVEL, LOGGING, MIDDLEWARE, env

# Ключ із base.py — дефолт для розробки. У production він означає, що змінну
# забули задати, а `.env` із машини розробника підставив свій.
DEV_SECRET_KEY = 'dev-only-insecure-key-change-me'
MIN_SECRET_KEY_LENGTH = 50

# ---------------------------------------------------------------------------
# Основне
# ---------------------------------------------------------------------------

DEBUG = False

# Відсутність змінної `environ` ловить сам, а **порожню** — ні: `SECRET_KEY=`,
# створена на хостингу й не заповнена, проходила перевірку мовчки. Django
# скаржиться на порожній ключ лише при першому зверненні до нього, тобто
# вже на живому трафіку. Слабкий ключ `check --deploy` лише попереджає
# (W009), а gunicorn `check --deploy` не запускає взагалі. Тому все це —
# помилка старту, а не попередження, яке ніхто не прочитає.
SECRET_KEY = env('SECRET_KEY').strip()

if not SECRET_KEY:
    raise ImproperlyConfigured('SECRET_KEY порожній. Згенеруйте ключ і задайте його в оточенні.')

if (
    SECRET_KEY == DEV_SECRET_KEY
    or SECRET_KEY.startswith('django-insecure-')
    or len(SECRET_KEY) < MIN_SECRET_KEY_LENGTH
):
    raise ImproperlyConfigured(
        f'SECRET_KEY слабкий: потрібно щонайменше {MIN_SECRET_KEY_LENGTH} випадкових символів, '
        'не ключ розробки. Згенерувати: python -c "from django.core.management.utils '
        'import get_random_secret_key as k; print(k())"'
    )

# Порожній список — не «дозволено все», а навпаки: з DEBUG=False кожен запит
# отримає 400. Сайт при цьому «стартує», і помилку шукають не там.
ALLOWED_HOSTS = [host for host in env.list('ALLOWED_HOSTS') if host.strip()]

if not ALLOWED_HOSTS:
    raise ImproperlyConfigured('ALLOWED_HOSTS порожній: з DEBUG=False сайт відповідатиме 400.')

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

# `same-origin`: на чужі сайти Referer не йде зовсім. Посилання на гостьове
# замовлення несе підписаний токен прямо в шляху, і політика, що віддає
# чужому сайту повну адресу, віддала б разом з нею доступ до замовлення.
SECURE_REFERRER_POLICY = 'same-origin'

# За проксі, який термінує TLS (Railway, Render, nginx у compose), Django
# бачить звичайний HTTP. Без цього заголовка `SECURE_SSL_REDIRECT` щоразу
# відправляє на https, проксі знову приносить http — і сайт падає в
# нескінченний редирект. Тому за замовчуванням увімкнено: саме так проєкт
# і розгортається.
#
# Вимикати (`USE_X_FORWARDED_PROTO=False`) — лише якщо gunicorn дивиться в
# інтернет напряму без проксі: тоді заголовок може підробити будь-хто.
BEHIND_PROXY = env.bool('USE_X_FORWARDED_PROTO', default=True)

if BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Той самий проксі дописує адресу клієнта в X-Forwarded-For. Без довіри до
# нього всі покупці ділили б один ліміт входу — адресу проксі.
RATELIMIT_TRUST_PROXY = BEHIND_PROXY


# ---------------------------------------------------------------------------
# Статика
# ---------------------------------------------------------------------------

# Хеш у назві файлу (`app.3f9c1a.js`) дозволяє віддавати статику з кешем на
# рік і `immutable`: нова версія — нова адреса, старий кеш не заважає.
# WhiteNoise заодно кладе поруч gzip і brotli, і сервер не стискає на льоту.
#
# Тільки тут, не в base.py: маніфест існує лише після collectstatic, а без
# нього `{% static %}` падає — тести й runserver зламались би.
#
# Зворотний бік тієї ж суворості: посилання на файл, якого немає, у prod —
# 500 на сторінці, а не бита картинка. Так знайшовся відсутній
# `og/cover.png`, на який посилався base.html.
# WhiteNoise — одразу після SecurityMiddleware: статика віддається до сесій,
# CSRF і автентифікації (запит за CSS не має чіпати базу), але після безпеки,
# щоб і вона отримала nosniff і HSTS.
#
# Лише в prod. У dev із DEBUG=True WhiteNoise вмикає autorefresh і на кожен
# запит перевіряє файлову систему — тести з ним ішли на 30 % довше (заміряно:
# 23.4 с проти 18.1 с на 111 тестах). Статику в розробці й так віддає runserver.
MIDDLEWARE = MIDDLEWARE.copy()
MIDDLEWARE.insert(
    MIDDLEWARE.index('django.middleware.security.SecurityMiddleware') + 1,
    'whitenoise.middleware.WhiteNoiseMiddleware',
)

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}


# ---------------------------------------------------------------------------
# База даних
# ---------------------------------------------------------------------------

# DATABASE_URL читає base.py через django-environ (postgres://...), тому
# dj-database-url не потрібен — це був би другий парсер тієї самої змінної.
# Тут лише тримаємо з'єднання між запитами: нове TCP+TLS з'єднання з
# Postgres на кожен запит коштує більше за сам запит до каталогу.
DATABASES['default']['CONN_MAX_AGE'] = env.int('CONN_MAX_AGE', default=60)  # noqa: F405
# Перевірка перед повторним використанням: інакше перший запит після
# рестарту бази отримує 500 на «мертвому» з'єднанні з пулу.
DATABASES['default']['CONN_HEALTH_CHECKS'] = True  # noqa: F405


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

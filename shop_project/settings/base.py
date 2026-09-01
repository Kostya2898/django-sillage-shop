"""Спільні налаштування проєкту SILLAGE.

Цей модуль не використовується напряму — його імпортують `dev.py` і `prod.py`.
Усе, що залежить від оточення, читається через `django-environ` зі змінних
оточення або з файлу `.env` у корені проєкту.

Документація змінних — у `.env.example`.
"""

from pathlib import Path

import environ
from django.contrib.messages import constants as messages

# BASE_DIR — корінь проєкту (там, де manage.py).
# Файл лежить у shop_project/settings/base.py, тому вгору треба на три рівні.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Оточення
# ---------------------------------------------------------------------------

env = environ.Env()

# Дефолти тут — безпечні для розробки. Production перевизначає їх у prod.py,
# де відсутність SECRET_KEY чи ALLOWED_HOSTS свідомо валить запуск.
ENV_FILE = BASE_DIR / '.env'
if ENV_FILE.exists():
    env.read_env(ENV_FILE)


# ---------------------------------------------------------------------------
# Безпека
# ---------------------------------------------------------------------------

SECRET_KEY = env('SECRET_KEY', default='dev-only-insecure-key-change-me')

DEBUG = env.bool('DEBUG', default=False)

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])


# ---------------------------------------------------------------------------
# Застосунки
# ---------------------------------------------------------------------------

DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

# Застосунки магазину. Порядок має значення для пошуку шаблонів.
LOCAL_APPS = [
    'accounts.apps.AccountsConfig',
    'shop.apps.ShopConfig',
    'cart.apps.CartConfig',
    'orders.apps.OrdersConfig',
    'payments.apps.PaymentsConfig',
]

# Сторонні пакети додаються в dev.py / prod.py — спільних поки немає.
THIRD_PARTY_APPS = []

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'shop_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'cart.context_processors.cart',
            ],
        },
    },
]

WSGI_APPLICATION = 'shop_project.wsgi.application'
ASGI_APPLICATION = 'shop_project.asgi.application'


# ---------------------------------------------------------------------------
# База даних
# ---------------------------------------------------------------------------

# DATABASE_URL у форматі django-environ: sqlite:///db.sqlite3,
# postgres://user:pass@host:5432/dbname тощо.
DATABASES = {
    'default': env.db_url(
        'DATABASE_URL',
        default=f'sqlite:///{BASE_DIR / "db.sqlite3"}',
    ),
}


# ---------------------------------------------------------------------------
# Кеш
# ---------------------------------------------------------------------------

# CACHE_URL: locmemcache://, dummycache://, rediscache://127.0.0.1:6379/1
CACHES = {
    'default': env.cache_url('CACHE_URL', default='locmemcache://'),
}


# ---------------------------------------------------------------------------
# Валідація паролів
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ---------------------------------------------------------------------------
# Локалізація
# ---------------------------------------------------------------------------

LANGUAGE_CODE = 'uk'
TIME_ZONE = 'Europe/Kyiv'
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Статика і медіа
# ---------------------------------------------------------------------------

# Провідний слеш обовʼязковий: без нього URL стає відносним до поточної
# сторінки, і посилання ламаються на вкладених адресах.
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Каталоги, які мають існувати ще до старту сервера. STATIC_ROOT сюди не
# входить — його створює collectstatic.
for directory in (STATICFILES_DIRS[0], MEDIA_ROOT):
    directory.mkdir(parents=True, exist_ok=True)

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# Модель користувача
# ---------------------------------------------------------------------------

# Кастомна модель задається до першої міграції і після цього фактично
# не змінюється — усі FK на користувача в проєкті йдуть через цю змінну.
AUTH_USER_MODEL = 'accounts.CustomUser'


# ---------------------------------------------------------------------------
# Кошик
# ---------------------------------------------------------------------------

# Ключ, під яким session-based кошик зберігається у сесії користувача.
CART_SESSION_ID = 'cart'

# Максимальна кількість одного товару в кошику. У налаштуваннях, а не в коді,
# щоб магазин міг змінити ліміт без правки views.
CART_MAX_QUANTITY_PER_PRODUCT = env.int('CART_MAX_QUANTITY_PER_PRODUCT', default=99)


# ---------------------------------------------------------------------------
# Автентифікація
# ---------------------------------------------------------------------------

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'shop:product_list'
LOGOUT_REDIRECT_URL = 'shop:product_list'


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

# EMAIL_URL у форматі django-environ:
#   consolemail://                          — друк у консоль (розробка)
#   smtp://user:password@host:587?tls=True  — справжня відправка
globals().update(env.email_url('EMAIL_URL', default='consolemail://'))

DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='shop@example.com')
SERVER_EMAIL = env('SERVER_EMAIL', default=DEFAULT_FROM_EMAIL)

# ADMINS у .env — рядок виду "Імʼя:пошта,Імʼя2:пошта2"
ADMINS = [
    tuple(pair.split(':', 1))
    for pair in env.list('ADMINS', default=['Адміністратор магазину:admin@example.com'])
    if ':' in pair
]
MANAGERS = ADMINS


# ---------------------------------------------------------------------------
# Платежі (мок платіжного шлюзу)
# ---------------------------------------------------------------------------

PAYMENT_CURRENCY = env('PAYMENT_CURRENCY', default='UAH')
# Частка від суми замовлення, напр. '0.20' для 20%.
PAYMENT_TAX_RATE = env('PAYMENT_TAX_RATE', default='0.00')
PAYMENT_SECRET_KEY = env('PAYMENT_SECRET_KEY', default='dev-payment-secret-change-me')
PAYMENT_API_URL = env('PAYMENT_API_URL', default='https://api.example-gateway.com/v3/payments')


# ---------------------------------------------------------------------------
# Абсолютні посилання в листах
# ---------------------------------------------------------------------------

# У листі відносне посилання не працює: у поштового клієнта немає «поточної
# сторінки», від якої його відраховувати. Домен беремо з оточення.
SITE_URL = env('SITE_URL', default='http://127.0.0.1:8000').rstrip('/')

# Скільки днів живе посилання на гостьове замовлення з листа. Гість не має
# акаунта, тому підписаний токен — його єдиний спосіб повернутись до покупки.
GUEST_ORDER_LINK_DAYS = env.int('GUEST_ORDER_LINK_DAYS', default=60)


# ---------------------------------------------------------------------------
# Рахунок (PDF)
# ---------------------------------------------------------------------------

# Реквізити продавця для друкованого рахунку. У налаштуваннях, а не в шаблоні:
# юридична особа змінюється без правки верстки, і в тестах їх видно.
INVOICE_SELLER = {
    'name': env('INVOICE_SELLER_NAME', default='ТОВ «Сіяж»'),
    'legal': env('INVOICE_SELLER_LEGAL', default='ЄДРПОУ 00000000'),
    'address': env('INVOICE_SELLER_ADDRESS', default='вул. Ярославів Вал, 15, Київ, 01034'),
    'bank': env('INVOICE_SELLER_BANK', default='IBAN UA00 0000 0000 0000 0000 0000 000'),
    'phone': env('INVOICE_SELLER_PHONE', default='+380 44 000 00 00'),
    'email': env('INVOICE_SELLER_EMAIL', default='hello@sillage.ua'),
    'signatory': env('INVOICE_SELLER_SIGNATORY', default='Директор — К. Гринюк'),
}


# ---------------------------------------------------------------------------
# Повідомлення
# ---------------------------------------------------------------------------

# Класи власної компонентної системи (BEM-модифікатори), а не Bootstrap.
# Головне тут — ERROR більше не дає клас `error`, під який ніде немає стилю:
# тепер це `toast--error`. Кольори модифікаторів — з палітри PROJECT_VISION.md
# (успіх — латунь #C8A45C, помилка — вуглиста троянда #B8615A).
MESSAGE_TAGS = {
    messages.DEBUG: 'toast--debug',
    messages.INFO: 'toast--info',
    messages.SUCCESS: 'toast--success',
    messages.WARNING: 'toast--warning',
    messages.ERROR: 'toast--error',
}


# ---------------------------------------------------------------------------
# Логування
# ---------------------------------------------------------------------------

LOG_LEVEL = env('LOG_LEVEL', default='INFO').upper()

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {name} {module}:{lineno} — {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'level': LOG_LEVEL,
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        # Автоперезавантажувач у DEBUG сипле рядком на кожну зміну файлу.
        'django.utils.autoreload': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        # Логер наших застосунків. `orders/emails.py` бере логер через
        # getLogger(__name__), тому кожен застосунок зареєстровано окремо —
        # інакше записи йшли б повз і губилися в root.
        'shop': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'accounts': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'cart': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'orders': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'payments': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
    },
}

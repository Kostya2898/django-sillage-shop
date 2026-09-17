#!/bin/sh
# Старт контейнера: дочекатись бази -> міграції -> статика -> gunicorn.
#
# `set -e`: якщо міграція впала, gunicorn не стартує на схемі, що не
# збігається з кодом. Контейнер падає, і це видно в логах одразу, а не
# першою 500 у покупця.
set -e

# --- SECRET_KEY -------------------------------------------------------------
# Для `docker compose up` з нуля ключ не обов'язковий: генеруємо одноразовий,
# щоб не класти секрет у репозиторій. Ціна — після перезапуску контейнера
# сесії, кошики гостей і посилання на гостьові замовлення з листів стають
# недійсними. Для локального показу це прийнятно; на хостингу SECRET_KEY
# задається явно.
if [ -z "${SECRET_KEY}" ]; then
    SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')"
    export SECRET_KEY
    echo "УВАГА: SECRET_KEY не задано — згенеровано одноразовий ключ." \
         "Сесії й посилання з листів не переживуть перезапуску." >&2
fi

# --- домен на хостингу ----------------------------------------------------------
# Адресу сервісу хостинг знає лише після його створення, тож вписати її в
# render.yaml заздалегідь неможливо. Render і Railway самі кладуть домен в
# оточення — беремо його, якщо ALLOWED_HOSTS не задано явно. Без цього prod
# відмовляється стартувати (порожній ALLOWED_HOSTS — ImproperlyConfigured).
PLATFORM_HOST="${RENDER_EXTERNAL_HOSTNAME:-${RAILWAY_PUBLIC_DOMAIN:-}}"
if [ -z "${ALLOWED_HOSTS}" ] && [ -n "${PLATFORM_HOST}" ]; then
    export ALLOWED_HOSTS="${PLATFORM_HOST}"
    echo "ALLOWED_HOSTS узято з домену хостингу: ${PLATFORM_HOST}"
fi
if [ -z "${CSRF_TRUSTED_ORIGINS}" ] && [ -n "${PLATFORM_HOST}" ]; then
    export CSRF_TRUSTED_ORIGINS="https://${PLATFORM_HOST}"
fi
if [ -z "${SITE_URL}" ] && [ -n "${PLATFORM_HOST}" ]; then
    export SITE_URL="https://${PLATFORM_HOST}"
fi

# --- очікування бази ----------------------------------------------------------
# healthcheck у compose вже чекає на Postgres, але на хостингу його немає, а
# база може прокидатись після застосунку. Питаємо саму Django: так
# перевіряється той самий DATABASE_URL, яким вона користуватиметься.
echo "Чекаю на базу даних..."
python - <<'PY'
import sys
import time

import django
from django.db import connection
from django.db.utils import OperationalError

django.setup()

for attempt in range(1, 31):
    try:
        connection.ensure_connection()
    except OperationalError as error:
        print(f"  спроба {attempt}/30: база ще недоступна ({error.__class__.__name__})", flush=True)
        time.sleep(2)
    else:
        print("  база відповідає.", flush=True)
        sys.exit(0)

print("База не відповіла за 60 секунд.", file=sys.stderr)
sys.exit(1)
PY

# --- міграції й статика -------------------------------------------------------
python manage.py migrate --noinput

# Статика вже зібрана на збірці образу. Повторний прогін дешевий (файли не
# змінились) і страхує випадок, коли staticfiles змонтовано томом.
python manage.py collectstatic --noinput

# --- демо-дані ----------------------------------------------------------------
# Лише за явним прапорцем і лише в порожню базу: повторний `up` не має
# перезаписувати те, що вже наповнили через адмінку.
if [ "${SEED_DEMO_DATA}" = "1" ]; then
    if python manage.py shell -c "from shop.models import Product; import sys; sys.exit(0 if Product.objects.exists() else 1)"; then
        echo "Каталог уже наповнений — сид пропущено."
    else
        echo "Порожній каталог — заповнюю демо-даними."
        python manage.py seed_shop
    fi
fi

# --- адміністратор ----------------------------------------------------------------
# На безкоштовному Render немає Shell, тож `createsuperuser` руками не
# запустити. Задайте DJANGO_SUPERUSER_USERNAME / _EMAIL / _PASSWORD — акаунт
# створиться один раз. Після першого входу змінні з оточення варто прибрати:
# пароль не має жити в налаштуваннях сервісу.
if [ -n "${DJANGO_SUPERUSER_USERNAME}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD}" ]; then
    if python manage.py shell -c "from django.contrib.auth import get_user_model; import os, sys; sys.exit(0 if get_user_model().objects.filter(username=os.environ['DJANGO_SUPERUSER_USERNAME']).exists() else 1)"; then
        echo "Адміністратор ${DJANGO_SUPERUSER_USERNAME} уже існує."
    else
        python manage.py createsuperuser --noinput
        echo "Створено адміністратора ${DJANGO_SUPERUSER_USERNAME}."
    fi
fi

# --- сервер ---------------------------------------------------------------------
# exec: gunicorn стає PID 1 і сам отримує SIGTERM від `docker stop`, тож
# встигає дообробити запити замість того, щоб бути вбитим через 10 секунд.
exec gunicorn shop_project.wsgi:application \
    --workers "${GUNICORN_WORKERS:-3}" \
    --bind "0.0.0.0:${PORT:-8000}" \
    --access-logfile - \
    --error-logfile -

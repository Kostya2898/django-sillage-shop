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

# --- сервер ---------------------------------------------------------------------
# exec: gunicorn стає PID 1 і сам отримує SIGTERM від `docker stop`, тож
# встигає дообробити запити замість того, щоб бути вбитим через 10 секунд.
exec gunicorn shop_project.wsgi:application \
    --workers "${GUNICORN_WORKERS:-3}" \
    --bind "0.0.0.0:${PORT:-8000}" \
    --access-logfile - \
    --error-logfile -

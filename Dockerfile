# syntax=docker/dockerfile:1
#
# SILLAGE — образ застосунку.
#
# Дві стадії. `builder` ставить залежності у віртуальне середовище (з
# компілятором на випадок, якщо для якогось пакета немає готового wheel).
# `runtime` отримує лише це середовище й код: компілятора, кешу pip і
# заголовків у робочому образі немає — він менший і має менше того, що
# можна зламати.

ARG PYTHON_VERSION=3.14

# ---------------------------------------------------------------------------
# builder
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Спершу лише requirements: шар із залежностями перебудовується тільки коли
# вони змінились, а не на кожну правку коду.
COPY requirements.txt .
RUN pip install -r requirements.txt


# ---------------------------------------------------------------------------
# runtime
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=shop_project.settings.prod

# Непривілейований користувач: зламаний процес усередині контейнера не
# отримує root.
RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .

# Репозиторій живе на Windows, де git віддає файли з CRLF. Скрипт із \r у
# кінці рядків падає з «/bin/sh^M: not found» ще до першого рядка логу.
# .gitattributes це закриває, sed — страховка на випадок старого checkout.
RUN sed -i 's/\r$//' /app/docker/entrypoint.sh \
    && chmod +x /app/docker/entrypoint.sh

# collectstatic на збірці: статика — частина образу, а не те, що докачується
# на старті. Prod-налаштування вимагають ключ і хости, тож для цього одного
# кроку даємо одноразові значення. У образ вони не потрапляють як ENV — лише
# як змінні цієї команди.
RUN SECRET_KEY="build-only-collectstatic-key-never-used-at-runtime-0000000" \
    ALLOWED_HOSTS="localhost" \
    python manage.py collectstatic --noinput \
    && mkdir -p /app/media /app/logs \
    && chown -R app:app /app/staticfiles /app/media /app/logs

USER app

EXPOSE 8000

# HEALTHCHECK свідомо не тут, а в docker-compose.yml. Перевірка ходить на
# 127.0.0.1, а на хостингу ALLOWED_HOSTS — це домен сайту і ввімкнений
# редирект на https: той самий образ там отримував би 400 чи 301 і вважався
# б хворим. У compose оточення відоме, і перевірка там чесна.

ENTRYPOINT ["/app/docker/entrypoint.sh"]

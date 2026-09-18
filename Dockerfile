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

# build-essential лишається свідомо: у фінальний образ ця стадія не потрапляє,
# тож компілятор коштує хвилину збірки і нуль байтів у результаті. Страховка на
# випадок, коли для Python 3.14 у якогось пакета ще немає готового wheel.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Спершу лише requirements: шар із залежностями перебудовується тільки коли
# вони змінились, а не на кожну правку коду. requirements-tools.txt (numpy,
# ~51 МБ) свідомо не ставиться: рейтрейсер і грейд фото працюють на машині,
# де готують контент, а не на хостингу.
#
# Після встановлення з середовища прибирається сам pip (~11 МБ): у робочому
# образі нічого не доставляється, а зайвий інсталятор пакетів у контейнері —
# це ще й інструмент для того, хто туди потрапить. `rm` замість
# `pip uninstall`, щоб не залежати від того, чи дозволить pip видалити себе.
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && rm -rf /opt/venv/lib/python*/site-packages/pip \
              /opt/venv/lib/python*/site-packages/pip-*.dist-info \
              /opt/venv/bin/pip /opt/venv/bin/pip3 /opt/venv/bin/pip3.*


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

# Один шар на всю підготовку: окремий RUN під sed давав ще один шар із копією
# entrypoint.sh, і жодної користі, бо кешувати тут нічого.
#
# sed: репозиторій живе на Windows, де git віддає файли з CRLF. Скрипт із \r у
# кінці рядків падає з «/bin/sh^M: not found» ще до першого рядка логу.
# .gitattributes це закриває, sed — страховка на випадок старого checkout.
#
# collectstatic на збірці: статика — частина образу, а не те, що докачується
# на старті. Prod-налаштування вимагають ключ і хости, тож для цього одного
# кроку даємо одноразові значення. У образ вони не потрапляють як ENV — лише
# як змінні цієї команди. numpy тут не потрібен: collectstatic його не
# імпортує (перевірено запуском із прихованим від import numpy).
RUN sed -i 's/\r$//' /app/docker/entrypoint.sh \
    && chmod +x /app/docker/entrypoint.sh \
    && SECRET_KEY="build-only-collectstatic-key-never-used-at-runtime-0000000" \
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

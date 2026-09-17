# Деплой SILLAGE

Основний шлях — **Render**: один файл `render.yaml` створює застосунок,
PostgreSQL і Redis. Нижче — покроково, потім чекліст змінних, альтернативи
й що перевірити після деплою.

> **Стан на момент написання.** Файли деплою готові, але жоден із них не
> проганявся на справжньому хостингу, а `docker compose up` не запускався:
> Docker на машині розробки не встановлено. Перевірено без Docker:
> prod-налаштування, `collectstatic` з manifest-сховищем, міграції на
> порожню базу, сид, сторінки (200), заголовки кешу й безпеки, віддача медіа.

---

## 1. Render — покроково

### Перед початком

1. Код лежить на GitHub (Render бере Blueprint звідти).
2. Згенеруйте два ключі — **щонайменше 50 символів**, інакше сервіс не
   стартує:

   ```bash
   python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
   ```

   Запустіть двічі: один для `SECRET_KEY`, другий для `PAYMENT_SECRET_KEY`.

### Створення

3. https://dashboard.render.com → **New** → **Blueprint**.
4. Підключіть GitHub і оберіть репозиторій. Render знайде `render.yaml` і
   покаже три ресурси: `sillage` (web), `sillage-cache` (Key Value),
   `sillage-db` (Postgres).
5. Render попросить значення для змінних із `sync: false`:
   - `SECRET_KEY` — перший ключ із кроку 2;
   - `PAYMENT_SECRET_KEY` — другий.
6. **Apply**. Перша збірка образу — 5–10 хвилин.

### Адміністратор (на безкоштовному плані немає Shell)

7. Сервіс `sillage` → **Environment** → додайте:
   - `DJANGO_SUPERUSER_USERNAME`
   - `DJANGO_SUPERUSER_EMAIL`
   - `DJANGO_SUPERUSER_PASSWORD`
8. **Save** → сервіс перезапуститься й створить акаунт (у логах: «Створено
   адміністратора»).
9. Увійдіть у `/admin/`, **після цього видаліть** `DJANGO_SUPERUSER_PASSWORD`
   з оточення.

### Що вийде

- адреса виду `https://sillage-xxxx.onrender.com`;
- `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` і `SITE_URL` підставляються з
  `RENDER_EXTERNAL_HOSTNAME` автоматично (`docker/entrypoint.sh`);
- порожній каталог заповнюється демо-даними (`SEED_DEMO_DATA=1`).

---

## 2. Чекліст змінних оточення

**Обов'язкові в prod** — без них сервіс не стартує або працює неправильно:

| Змінна | Звідки | Що буде без неї |
|---|---|---|
| `SECRET_KEY` | згенерувати, ≥ 50 символів | старт падає з `ImproperlyConfigured` |
| `ALLOWED_HOSTS` | домен сайту; на Render і Railway — автоматично | старт падає |
| `DATABASE_URL` | `postgres://...`; на Render — з `sillage-db` | SQLite у контейнері, дані зникнуть при перезапуску |
| `CACHE_URL` | `redis://...`; на Render — з `sillage-cache` | `migrate` падає з `django_ratelimit.E003`: ліміти входу потребують спільного кешу |
| `DJANGO_SETTINGS_MODULE` | `shop_project.settings.prod` | **у Docker уже задано**; без Docker — сайт стартує з dev-налаштуваннями |

**Бажані:**

| Змінна | Навіщо | За замовчуванням |
|---|---|---|
| `PAYMENT_SECRET_KEY` | підпис callback платежу | ключ розробки — у prod замінити |
| `CSRF_TRUSTED_ORIGINS` | форми за HTTPS-проксі; на Render/Railway — автоматично | — |
| `SITE_URL` | абсолютні посилання в листах; на Render/Railway — автоматично | http://127.0.0.1:8000 |
| `EMAIL_URL` + `EMAIL_BACKEND` | справжня пошта: `smtp://user:pass@host:587?tls=True` і `django.core.mail.backends.smtp.EmailBackend` | у `render.yaml` — консоль (лог сервісу) |
| `DEFAULT_FROM_EMAIL` | адреса відправника | shop@example.com |
| `SERVE_MEDIA` | Django віддає `/media/` сам | `False`; у `render.yaml` — `True` |
| `SEED_DEMO_DATA` | демо-каталог у порожню базу | вимкнено; у `render.yaml` — `1` |
| `GUNICORN_WORKERS` | кількість воркерів | 3; у `render.yaml` — 2 (512 МБ) |
| `DJANGO_SUPERUSER_*` | адміністратор без Shell | — |

**Не чіпати на хостингу** (потрібні лише для локального http у compose):
`SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`,
`SECURE_HSTS_SECONDS`, `USE_X_FORWARDED_PROTO`. Їхні prod-дефолти правильні
для будь-якого хостингу з TLS-проксі.

---

## 3. Після деплою — перевірити

- [ ] головна відкривається по `https://`, `http://` редиректить на `https://`;
- [ ] `/admin/` — вхід працює (якщо вхід «не тримається» — перевірити `CSRF_TRUSTED_ORIGINS`);
- [ ] каталог показує 30 товарів;
- [ ] додати в кошик → оформити як гість → замовлення створено, у логах сервісу видно лист;
- [ ] шосту невдалу спробу входу поспіль сайт відхиляє сторінкою 429;
- [ ] у логах немає `ConnectionInterrupted` (означало б, що Redis недоступний).

---

## 4. Обмеження безкоштовного плану

- **Сервіс засинає** без трафіку; перший запит після паузи — до хвилини.
- **Немає постійного диска**: фото, завантажені через адмінку, зникнуть
  при наступному деплої. Для показу — залийте фото заново або використайте
  S3/R2 замість `SERVE_MEDIA`.
- **Безкоштовна база має обмежений термін життя** — перевірте поточні умови
  на сторінці тарифів Render перед захистом.
- Фото товарів у репозиторії немає — на свіжому деплої картки будуть без
  зображень, доки їх не завантажено.

---

## 5. Альтернативи

### Railway

1. **New Project** → **Deploy from GitHub repo**. Railway знайде `Dockerfile`
   і збиратиме з нього — `Procfile` при цьому не використовується.
2. **+ New** → **Database** → **PostgreSQL**, потім **+ New** → **Database** → **Redis**.
3. У сервісі застосунку → **Variables**:
   - `SECRET_KEY` — згенерований ключ;
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`;
   - `CACHE_URL` = `${{Redis.REDIS_URL}}`;
   - `SERVE_MEDIA=True`, `SEED_DEMO_DATA=1`.
4. **Settings** → **Networking** → **Generate Domain**. `ALLOWED_HOSTS`
   підставиться з `RAILWAY_PUBLIC_DOMAIN`.

### Платформа з buildpack (без Docker)

`Procfile` для такого випадку: `release` виконує міграції, `web` — gunicorn.
**Обов'язково** задайте `DJANGO_SETTINGS_MODULE=shop_project.settings.prod`:
`manage.py` і `wsgi.py` без неї беруть dev-налаштування. `collectstatic`
платформа запускає сама під час збірки.

### Свій сервер

```bash
git clone <репозиторій> && cd <репозиторій>
docker compose up -d --build
```

Для публічного сервера з доменом перед compose потрібен проксі з TLS
(Caddy, nginx), а змінні `SECURE_SSL_REDIRECT`, `*_COOKIE_SECURE`,
`SECURE_HSTS_SECONDS`, `USE_X_FORWARDED_PROTO` з `docker-compose.yml` треба
прибрати — вони там лише для локального http.

---

## 6. Локально в Docker — перший запуск

Цей крок на машині розробки **не виконувався**. Що треба зробити:

1. Встановити Docker Desktop: https://www.docker.com/products/docker-desktop/
   (на Windows — з WSL 2).
2. У корені проєкту:

   ```bash
   docker compose up --build
   ```

3. Дочекатись у логах рядка gunicorn `Listening at: http://0.0.0.0:8000`.
4. http://localhost:8000 — сайт, каталог наповнений.
5. Якщо впало — надіслати вивід `docker compose logs web`.

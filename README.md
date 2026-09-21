# SILLAGE

Кураторський інтернет-магазин нішевої парфумерії. Фінальний проєкт курсу Django.

Тридцять ароматів замість тридцяти тисяч: кожен обраний за те, що він
розповідає. Каталог із фільтрами за нотами, гостьове замовлення без
реєстрації, промокоди, PDF-рахунок і листи на кожну зміну статусу.

![Головна](docs/screenshots/01-home.png)

| Каталог | Кошик | Оформлення |
|---|---|---|
| ![Каталог](docs/screenshots/02-catalogue.png) | ![Кошик](docs/screenshots/04-cart-drawer.png) | ![Оформлення](docs/screenshots/05-checkout.png) |

---

## Стек

| | |
|---|---|
| Мова, фреймворк | Python 3.14, Django 6.0 |
| База | SQLite у розробці, PostgreSQL 16 у Docker і на хостингу |
| Кеш | Redis 7 через django-redis; без Redis — LocMemCache |
| Статика | WhiteNoise, хешовані імена, gzip |
| Сервер | gunicorn |
| PDF | xhtml2pdf + reportlab, шрифт DejaVu Sans (кирилиця) |
| Фронтенд | власні CSS-токени й компоненти, ванільний JS, GSAP для появ і паралаксу (скрол рідний) |
| Тести | Django TestCase, factory_boy, coverage |

Без DRF, Celery і SPA: серверний рендеринг і точковий `fetch` там, де
перезавантаження сторінки заважає.

---

## Що вміє

**Каталог**
- категорії з підкатегоріями, бренди, ольфакторні ноти, концентрації;
- фільтри й сортування без перезавантаження, з робочою версією без JS;
- живий пошук із підсвіткою збігу і порадою, коли нічого не знайдено;
- відгуки з модерацією, рейтинг на картках.

**Кошик**
- гібридний: у сесії для гостя, у базі для авторизованого, злиття при вході;
- бокова панель із кількістю, що змінюється одразу, і відкатом при помилці;
- перевірка складу з урахуванням того, що вже лежить у кошику.

**Оформлення й замовлення**
- гостьовий checkout; замовлення гостя прив'язуються до акаунта після реєстрації;
- промокоди (відсоток або сума, мінімальне замовлення, ліміт використань);
- способи доставки з безкоштовним порогом;
- скасування протягом 24 годин із поверненням товару на склад;
- листи в HTML і тексті на кожну зміну статусу, PDF-рахунок у вкладенні;
- навчальний мок платіжного шлюзу з підписаним callback (див. нижче).

**Панель керування**
- масова зміна статусів з історією, фільтр за періодом, PDF із адмінки;
- керування каталогом, фото й джерелами зображень.

**Безпека й продуктивність**
- prod не стартує з порожнім чи слабким `SECRET_KEY` або порожнім `ALLOWED_HOSTS`;
- HSTS, Secure-cookie, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`;
- ліміти частоти: вхід, реєстрація, живий пошук, промокод — 429 з поясненням;
- кеш дерева категорій, брендів, фасетів і головної з інвалідацією сигналами;
- статика з `Cache-Control: immutable` на рік.

---

## Локальний запуск

Потрібен Python 3.12+. Redis і PostgreSQL для розробки не потрібні.

```bash
python -m venv .venv
```

Windows (PowerShell):

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
copy .env.example .env
python manage.py migrate
python manage.py seed_shop --flush
python manage.py createsuperuser
python manage.py runserver
```

Linux / macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_shop --flush
python manage.py createsuperuser
python manage.py runserver
```

Сайт — http://127.0.0.1:8000, панель — http://127.0.0.1:8000/admin/.
Листи в розробці друкуються в консоль `runserver`.

`seed_shop` створює 30 товарів, демо-покупців (логін `olena` … `sofiia`,
пароль `sillage-demo-2026`), замовлення, промокоди й відгуки. Зображення
товарів генерує окрема команда `render_product_images`.

---

## Запуск у Docker

```bash
docker compose up --build
```

Піднімає застосунок, PostgreSQL 16 і Redis 7. Працює без `.env`:
`SECRET_KEY` генерується на старті, порожній каталог заповнюється
демо-даними. Сайт — http://localhost:8000.

Статика збирається один раз — на збірці образу. На старті
(`docker/entrypoint.sh`): очікування бази → `migrate` → демо-дані, якщо
каталог порожній → gunicorn на 3 воркерах.

Фото товарів у репозиторій не входять. Щоб показати їх у контейнері:

```bash
docker compose cp media/. web:/app/media/
```

> Файли Docker написані й перевірені по частинах без Docker (prod-налаштування,
> `collectstatic`, міграції, сторінки, заголовки). Повний `docker compose up`
> на машині розробки не запускався — див. [docs/deploy.md](docs/deploy.md).

---

## Змінні оточення

Повний перелік із поясненнями — [`.env.example`](.env.example). Головне:

| Змінна | Навіщо | За замовчуванням |
|---|---|---|
| `SECRET_KEY` | підписи сесій, CSRF, посилань на гостьові замовлення. **У prod ≥ 50 символів**, інакше старт падає | ключ розробки |
| `DEBUG` | лише dev; у prod жорстко `False` | `True` у dev |
| `ALLOWED_HOSTS` | домени сайту через кому. **У prod обов'язкова** | localhost |
| `CSRF_TRUSTED_ORIGINS` | зі схемою: `https://sillage.example.com` | — |
| `DATABASE_URL` | `postgres://user:pass@host:5432/db` | SQLite |
| `CACHE_URL` | `redis://host:6379/1`. **У prod потрібна**: ліміти входу рахуються в кеші | LocMemCache |
| `EMAIL_URL` | `smtp://user:pass@host:587?tls=True` | консоль |
| `SITE_URL` | абсолютні посилання в листах | http://127.0.0.1:8000 |
| `PAYMENT_SECRET_KEY` | підпис callback платежу | ключ розробки |
| `USE_X_FORWARDED_PROTO` | застосунок за TLS-проксі (Railway, Render, nginx) | `True` у prod |
| `SERVE_MEDIA` | Django сам віддає `/media/`, коли немає nginx чи S3 | `False` |
| `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS` | вимикаються лише для локального http | увімкнені в prod |

---

## Тести

```bash
python manage.py test
```

560 тестів. Покриття — 88.5 % з урахуванням гілок
([звіт](docs/coverage-report.txt)):

```bash
coverage run manage.py test
coverage report
```

Перед комітом:

```bash
ruff check .
black --check .
python manage.py makemigrations --check --dry-run
python manage.py check --deploy --settings=shop_project.settings.prod
```

Останню команду запускати з prod-оточенням (`SECRET_KEY`, `ALLOWED_HOSTS`,
`CACHE_URL=redis://...`) — на LocMemCache вона свідомо дає помилку.

---

## Структура

```
shop_project/        налаштування (base / dev / prod), URL, ліміти частоти
accounts/            CustomUser, профіль, реєстрація, кабінет, злиття кошиків
shop/                каталог: товари, бренди, ноти, відгуки, пошук, кеш
  cache.py           ключі кешу й invalidate_catalog_cache()
  services.py        фільтри, фасети, дерево меню, підказки пошуку
  management/        seed_shop, render_product_images, fetch_product_photos
cart/                SessionCart / DatabaseCart з одним інтерфейсом, JSON API
orders/              checkout, замовлення, промокоди, доставка, листи, PDF
payments/            мок платіжного шлюзу з HMAC-підписом callback
templates/           усі шаблони, згруповані за застосунками
static/              CSS-токени й компоненти, JS, шрифти
testing/             фабрики й базовий TestCase
docker/              entrypoint контейнера
docs/                захист, деплой, арт-дирекшен, покриття, скріншоти
```

---

## ⚠️ Платіжний шлюз — навчальний мок

**Реальний платіжний провайдер до проєкту не підключений.** Жодних грошей
не списується, картка ніде не вводиться. `payments/` імітує потік справжнього
шлюзу (ініціація → сторінка провайдера → callback), щоб показати архітектуру
інтеграції, а не щоб приймати платежі.

Що зроблено, аби мок був чесним у межах демонстрації:

- callback підписано **HMAC-SHA256** від `(tx_ref, amount, currency)` на
  `PAYMENT_SECRET_KEY`; підпис звіряється через `hmac.compare_digest`;
- транзакція перевіряється на належність покупцю, на статус і на збіг суми
  й валюти із замовленням;
- повторний callback ідемпотентний — нічого не змінює і другого листа не шле.

Чого це **не** замінює: справжній провайдер сам верифікує платіж окремим
запитом до свого API, має власні вебхуки, звірку й повернення коштів.

---

## Відомі обмеження

- **Docker** перевірено по частинах (prod-налаштування, `collectstatic`,
  міграції, сторінки, заголовки, старт без numpy); сам образ уперше
  збереться на Render — див. [docs/deploy.md](docs/deploy.md).
- **Каркас навігації (F1) не закритий**: не перевірені ширина 360 px, покупка
  без JS, `prefers-reduced-motion`; немає профілю продуктивності.
- **Зображення товарів.** Частина зведених фотографій має WebP-блочність,
  помітну на сторінці товару в масштабі 1:1; у сітці каталогу її не видно.
  Для скріншотів обрано чисті кадри. На деплої фото немає зовсім — вони не
  входять у репозиторій.
- **Медіа** в prod віддає сам Django (`SERVE_MEDIA`) — прийнятно для
  навчального деплою, для справжнього потрібне S3 чи nginx.
- **Поки Redis недоступний**, ліміти частоти не діють (свідомо: інакше
  ніхто не зміг би увійти).

## Документи

| Файл | Про що |
|---|---|
| [docs/DEFENCE.md](docs/DEFENCE.md) | Конспект для захисту: рішення і чому саме так |
| [docs/deploy.md](docs/deploy.md) | Деплой покроково, чекліст змінних |
| [AUDIT.md](AUDIT.md) | Аудит коду: вимоги ТЗ, борги, ризики міграцій |
| [PROJECT_VISION.md](PROJECT_VISION.md) | Концепція бренду, палітра, типографіка |
| [docs/ART_DIRECTION.md](docs/ART_DIRECTION.md) | Арт-дирекшен і дизайн-система |
| [docs/course-notes.md](docs/course-notes.md) | Конспект курсу |

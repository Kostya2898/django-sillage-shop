# Деплой SILLAGE на Render

Один файл `render.yaml` створює три ресурси: сайт (збирається з нашого
`Dockerfile`), базу PostgreSQL і Redis. Нижче — покроково, з тим, що буде
на екрані, і з таблицею «що робити, якщо впало».

**Час:** 5 хвилин рук + 10–15 хвилин очікування збірки.

> **Стан на момент написання.** Жоден із кроків ще не виконувався на
> справжньому Render, і образ ще жодного разу не збирався: Docker на машині
> розробки не встановлено. Перша збірка на Render і є перевіркою Dockerfile.
> Якщо щось упаде — скопіюйте лог (див. розділ 6).

---

## 0. Що знадобиться

- акаунт на GitHub;
- акаунт на Render — https://render.com, **Get Started**, найпростіше
  зареєструватися через GitHub;
- два ключі — `SECRET_KEY` і `PAYMENT_SECRET_KEY`, **щонайменше 50 символів**
  кожен. Згенерувати:

  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```

  Запустіть двічі. Ключі нікуди в репозиторій не пишіть — лише в Render.

---

## 1. Залити код на GitHub

Render бере код з GitHub. Репозиторій може бути **приватним** — Render
отримає до нього доступ через свій застосунок GitHub.

1. https://github.com/new → **Repository name**: `sillage` →
   **Private** → **нічого не додавайте** (без README, .gitignore, ліцензії) →
   **Create repository**.
2. У корені проєкту:

   ```bash
   git remote add origin https://github.com/<ваш-логін>/sillage.git
   git push -u origin main
   ```

3. Оновіть сторінку репозиторію на GitHub — має з'явитись код і README зі
   скріншотами.

Секретів у репозиторії немає: `.env`, база й дамп із користувачами в
`.gitignore` (перевірено перед написанням цієї інструкції).

---

## 2. Створити сервіси на Render

1. https://dashboard.render.com → кнопка **New** угорі → **Blueprint**.
2. Якщо GitHub ще не підключений — Render попросить дати доступ.
   Оберіть **Only select repositories** → `sillage` → **Install**.
3. У списку репозиторіїв біля `sillage` натисніть **Connect**.
4. Форма Blueprint:

   | Поле | Що ввести |
   |---|---|
   | **Blueprint Name** | `sillage` |
   | **Branch** | `main` |
   | **Blueprint Path** | лишити порожнім (означає `render.yaml` у корені) |

   Нижче Render покаже три ресурси, які створить:
   `sillage` (Web Service, Docker), `sillage-cache` (Key Value),
   `sillage-db` (PostgreSQL) — усі **Free**.

5. Там же — поля для змінних із позначкою `sync: false`:

   | Змінна | Значення |
   |---|---|
   | `SECRET_KEY` | перший ключ |
   | `PAYMENT_SECRET_KEY` | другий ключ |

6. **Deploy Blueprint**.

---

## 3. Що буде на екрані

1. Сторінка **Blueprint provisioning**: спершу створюються база й Redis
   (1–2 хвилини), потім починається збірка сайту.
2. Відкрийте сервіс **sillage** → вкладка **Logs**. Збірка йде кроками
   Docker — приблизно так (номери кроків і кількість файлів можуть
   відрізнятись, це нормально):

   ```
   ==> Building...
   #1 [builder 1/5] FROM docker.io/library/python:3.14-slim
   ...
   #12 [runtime 6/6] RUN sed -i ... && python manage.py collectstatic --noinput
   155 static files copied to '/app/staticfiles', 463 post-processed.
   ==> Pushing image...
   ```

   Статика збирається тут, на збірці, — на старті її вже не чіпаємо.
   Встановлюється лише `requirements.txt`: dev-інструменти й numpy в образ
   не потрапляють.

3. Потім запуск. Перший старт довший за наступні — він наповнює каталог:

   ```
   ALLOWED_HOSTS узято з домену хостингу: sillage-xxxx.onrender.com
   Чекаю на базу даних...
     база відповідає.
   Operations to perform: ...
     Applying shop.0001_initial... OK
   Порожній каталог — заповнюю демо-даними.
   ...
   Готово. Демо-покупці: логін olena…sofiia / sillage-demo-2026
   [INFO] Listening at: http://0.0.0.0:10000
   ==> Your service is live 🎉
   ```

4. Угорі сторінки сервісу — адреса виду `https://sillage-xxxx.onrender.com`.
   Відкрийте її.

---

## 4. Адміністратор

На безкоштовному тарифі немає консолі, тож `createsuperuser` руками не
запустити — акаунт створить сам контейнер.

1. Render питає `DJANGO_SUPERUSER_USERNAME`, `_EMAIL` і `_PASSWORD` разом із
   ключами на кроці 2. Якщо їх тоді лишили порожніми — сервіс **sillage** →
   **Environment** → заповніть ці три змінні → **Save Changes**.
2. У **Logs** з'явиться `Створено адміністратора <логін>.`
3. Увійдіть на `https://…onrender.com/admin/`.
4. Поверніться в **Environment** і **видаліть** `DJANGO_SUPERUSER_PASSWORD`
   (іконка кошика біля змінної → **Save Changes**). Акаунт лишиться, а пароль
   більше не лежить у налаштуваннях.

---

## 5. Усі змінні оточення

Більшість Render заповнить сам із `render.yaml`. Руками — лише два ключі
і, за бажанням, адміністратор: Render спитає їх в одній формі на кроці 2.

| Змінна | Звідки | Значення |
|---|---|---|
| `SECRET_KEY` | **ви**, крок 2 | ≥ 50 символів, інакше сайт не стартує |
| `PAYMENT_SECRET_KEY` | **ви**, крок 2 | ≥ 50 символів |
| `DATABASE_URL` | Render, з `sillage-db` | підставиться сам |
| `CACHE_URL` | Render, з `sillage-cache` | підставиться сам |
| `SERVE_MEDIA` | `render.yaml` | `True` |
| `SEED_DEMO_DATA` | `render.yaml` | `1` — лише в порожній каталог |
| `GUNICORN_WORKERS` | `render.yaml` | `2` (512 МБ пам'яті) |
| `EMAIL_BACKEND` | `render.yaml` | листи пишуться в **Logs** |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL` | контейнер, з домену Render | нічого не задавати |
| `DJANGO_SUPERUSER_*` | **ви**, крок 2 | після входу пароль видалити |

`DJANGO_SETTINGS_MODULE=shop_project.settings.prod` уже вшитий в образ.
Змінні `SECURE_*`, `*_COOKIE_SECURE`, `USE_X_FORWARDED_PROTO` **не задавайте**:
їхні значення за замовчуванням правильні саме для Render.

---

## 6. Якщо щось упало

Спершу — **Logs** сервісу `sillage`. Шукайте останній рядок з `Error`.

| Що в лозі | Причина | Що зробити |
|---|---|---|
| `Killed` або `exit code 137` під час **збірки** | забракло пам'яті на збірку | **Manual Deploy** → **Clear build cache & deploy**. Повторилось — скиньте мені лог |
| `ERROR: Could not find a version that satisfies ...` | для Python 3.14 немає пакета | скиньте мені лог — перепишу версію Python в `Dockerfile` |
| `ImproperlyConfigured: SECRET_KEY порожній` / `слабкий` | ключ не введено або коротший за 50 | **Environment** → виправити `SECRET_KEY` → **Save Changes** |
| `django_ratelimit.E003 ... LocMemCache` | не підключився Redis | перевірте, що `sillage-cache` створений і має статус **Available**; **Manual Deploy** |
| `База не відповіла за 60 секунд` | Postgres ще створюється | зачекайте 2 хвилини → **Manual Deploy** → **Deploy latest commit** |
| `No open ports detected` | контейнер упав до запуску gunicorn | дивіться рядки **вище** — там справжня помилка |
| `Out of memory` уже після старту | два воркери не влазять у 512 МБ | **Environment** → `GUNICORN_WORKERS` = `1` → **Save Changes** |
| сайт відкривається, але вхід не тримається («CSRF») | власний домен | додайте `CSRF_TRUSTED_ORIGINS=https://ваш-домен` |

**Як скинути лог:** **Logs** → прокрутіть до першого червоного рядка →
скопіюйте його разом із 30 рядками над ним і надішліть. Цього досить, щоб
знайти й виправити причину.

---

## 7. Перевірка після деплою

- [ ] головна відкривається по `https://`;
- [ ] каталог показує 30 товарів;
- [ ] у кошик додається товар → оформлення як гість → замовлення створено,
      у **Logs** видно лист;
- [ ] `/admin/` — вхід працює;
- [ ] шоста невдала спроба входу поспіль дає сторінку «Зачекайте трохи» (429).

---

## 8. Обмеження безкоштовного тарифу

- **Сервіс засинає** після 15 хвилин без трафіку; перший запит після паузи
  — до хвилини. Перед захистом відкрийте сайт заздалегідь.
- **Постійного диска немає.** Фото каталогу це не зачіпає: вони лежать у
  репозиторії (`shop/photos/catalogue/`), і контейнер на кожному старті
  повертає їх командою `load_product_photos`. А от фото, завантажене через
  адмінку, зникне при наступному деплої чи перезапуску.
- **Безкоштовна база має обмежений термін.** Перевірте умови на сторінці
  тарифів Render перед захистом.

---

## Інші варіанти

### Локально в Docker

Потрібен Docker Desktop (на Windows — з WSL 2).

```bash
docker compose up --build
```

Сайт — http://localhost:8000, каталог наповнюється сам. Якщо впало —
`docker compose logs web`.

### Railway

1. **New Project** → **Deploy from GitHub repo** → `sillage`. Railway знайде
   `Dockerfile`.
2. **+ New** → **Database** → **PostgreSQL**; ще раз → **Redis**.
3. Сервіс застосунку → **Variables**: `SECRET_KEY`, `PAYMENT_SECRET_KEY`,
   `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `CACHE_URL=${{Redis.REDIS_URL}}`,
   `SERVE_MEDIA=True`, `SEED_DEMO_DATA=1`.
4. **Settings** → **Networking** → **Generate Domain**. `ALLOWED_HOSTS`
   підставиться з `RAILWAY_PUBLIC_DOMAIN`.

### Платформа без Docker (buildpack)

`Procfile`: `release` виконує міграції, `web` — gunicorn. **Обов'язково**
задайте `DJANGO_SETTINGS_MODULE=shop_project.settings.prod` — без неї
`manage.py` бере налаштування розробки.

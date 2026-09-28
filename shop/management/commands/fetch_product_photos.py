"""Завести справжні фотографії в каталог, звівши їх до однієї зйомки.

Два режими подачі, обидва — точкові:

    --from-folder photos_in/   файли, складені по теках зі slug товару
    --from-urls sources.json   список прямих адрес на товар

Павука тут немає навмисно. Обхід сайту по внутрішніх посиланнях із
викачуванням усього підряд — це і бан по IP посеред роботи, і чужий трафік
задарма. Схема інша: конкретний список адрес → точкове завантаження кожної,
з паузою і в один потік.

Рейтрейсер лишається: товари, для яких придатного кадру не знайшлося,
зберігають рендер, і команда перелічує їх окремо. Мовчазних дірок у каталозі
бути не повинно.
"""

import json
import time
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from shop.models import Product, ProductImage, ProductNote
from shop.photo_rejects import is_rejected_hash, is_rejected_url, reason_for

from . import _photos

# Оригінали лишаються на диску, щоб повторний запуск нічого не перекачував.
ORIGINALS_DIR = 'media/_originals'

# Мережеві правила. Ми качаємо десятки файлів, а не тисячі, і поводитись
# треба відповідно: один запит за раз і пауза між ними.
REQUEST_TIMEOUT = 15
REQUEST_PAUSE = 1.5
MAX_ATTEMPTS = 2
# Лише ASCII. Заголовки HTTP кодуються в latin-1, і кирилиця тут валила
# кожен запит ще до виходу в мережу: `requests` кидав UnicodeEncodeError,
# команда записувала його як «мережа» і відкидала всіх кандидатів підряд.
# Тести підміняють `requests.get`, тож до справжнього прогону цього ніхто
# не бачив.
USER_AGENT = 'SILLAGE-catalogue/1.0 (course project; product image download)'

# Скільки зображень на товар: обкладинка, другий ракурс, макро-кроп.
IMAGES_PER_PRODUCT = 3

# Скільки придатних кадрів беремо з кандидатів. Другий — це другий ракурс;
# якщо його немає, обійдемось ширшим кропом першого.
CANDIDATES_PER_PRODUCT = 2


class Command(BaseCommand):
    help = 'Заводить фотографії товарів і зводить їх єдиним грейдом'

    def add_arguments(self, parser):
        parser.add_argument(
            '--from-folder',
            metavar='DIR',
            help='тека з підтеками за slug товару: photos_in/<slug>/*.jpg',
        )
        parser.add_argument(
            '--from-urls',
            metavar='FILE',
            help='JSON {"<slug>": [{"url": "...", "query": "..."}]}',
        )
        parser.add_argument('--only', metavar='SLUG', help='один товар')
        parser.add_argument(
            '--force',
            action='store_true',
            help='перезаписати наявні фото; забраковані кандидати пропускаються',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='показати таблицю відсіву, нічого не зберігаючи',
        )
        parser.add_argument('--limit', type=int, metavar='N', help='обробити не більше N товарів')
        parser.add_argument(
            '--as-is',
            action='store_true',
            help='без грейду: для кадрів, уже відібраних під каталог вручну',
        )

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        self.force = options['force']
        self.graded = not options['as_is']

        sources = self._load_sources(options)
        products = self._select_products(options, sources)

        if not products:
            self.stdout.write(self.style.WARNING('Немає товарів для обробки.'))
            return

        self.stdout.write(f'Товарів: {len(products)}' + (' — сухий прогін' if self.dry_run else ''))
        self.stdout.write('')

        report = []
        # Хеші, набрані в цьому прогоні: один знімок не може стояти у двох
        # товарів навіть у межах однієї партії.
        batch = {}

        for product in products:
            # Власні кадри товару виключаємо, інакше --force вважав би
            # переімпорт дублем самого себе.
            seen = {**self._existing_hashes(exclude_product=product), **batch}
            line = self._handle_product(product, sources.get(product.slug, []), seen)

            for index, accepted in enumerate(line['accepted']):
                batch[f'{product.slug}-{index}'] = accepted['hash']

            report.append(line)

        self._report(report)

    # --- підготовка ------------------------------------------------------

    def _load_sources(self, options):
        """Зібрати кандидатів: {slug: [{url|path, query}]}."""
        folder = options['from_folder']
        urls = options['from_urls']

        if not folder and not urls:
            raise CommandError(
                'Вкажіть джерело: --from-folder photos_in/ або --from-urls sources.json'
            )

        sources = {}

        if urls:
            path = Path(urls)
            if not path.exists():
                raise CommandError(f'Немає файлу {path}')

            for slug, entries in json.loads(path.read_text(encoding='utf-8')).items():
                sources.setdefault(slug, []).extend(
                    (
                        {'url': item['url'], 'query': item.get('query', '')}
                        if isinstance(item, dict)
                        else {'url': item, 'query': ''}
                    )
                    for item in entries
                )

        if folder:
            root = Path(folder)
            if not root.exists():
                raise CommandError(f'Немає теки {root}')

            for directory in sorted(p for p in root.iterdir() if p.is_dir()):
                files = sorted(
                    f
                    for f in directory.iterdir()
                    if f.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff'}
                )
                sources.setdefault(directory.name, []).extend(
                    {'path': f, 'query': f'файл {f.name}'} for f in files
                )

        return sources

    def _select_products(self, options, sources):
        queryset = Product.objects.select_related('brand', 'category').order_by('id')

        if options['only']:
            queryset = queryset.filter(slug=options['only'])
            if not queryset.exists():
                raise CommandError(f'Товару зі slug «{options["only"]}» немає')
        else:
            # Без --force не чіпаємо тих, у кого фото вже є.
            if not self.force:
                queryset = queryset.exclude(images__source_url__gt='').distinct()
            queryset = queryset.filter(slug__in=sources.keys())

        products = list(queryset)

        limit = options['limit']
        if limit is not None:
            if limit <= 0:
                self.stdout.write(self.style.WARNING(f'Ліміт {limit} — нічого не обробляю.'))
                return []
            products = products[:limit]

        return products

    def _existing_hashes(self, exclude_product=None):
        """Хеші вихідних кадрів, уже заведених у каталог.

        Беремо збережений `source_hash`, а не рахуємо по файлу в медіа:
        у медіа лежить результат грейду, а він для всіх товарів схожий за
        побудовою — на ньому дедуплікація відкидала б геть усе.
        """
        queryset = ProductImage.objects.exclude(source_hash='')
        if exclude_product is not None:
            # Власні кадри товару не мають блокувати його ж переімпорт.
            queryset = queryset.exclude(product=exclude_product)

        return {
            image_id: int(value, 16)
            for image_id, value in queryset.values_list('id', 'source_hash')
        }

    # --- один товар ------------------------------------------------------

    def _handle_product(self, product, candidates, seen):
        line = {'product': product, 'accepted': [], 'rejected': [], 'queries': []}

        self.stdout.write(self.style.MIGRATE_HEADING(f'{product.brand.name} — {product.name}'))

        if not candidates:
            self.stdout.write('  кандидатів немає — лишається рендер')
            return line

        for candidate in candidates:
            query = candidate.get('query', '')
            if query and query not in line['queries']:
                line['queries'].append(query)

            if len(line['accepted']) >= CANDIDATES_PER_PRODUCT:
                # Два придатні кадри — це обкладинка й другий ракурс. Макро
                # робиться з першого, тож третього кандидата шукати не треба.
                break

            source = candidate.get('url') or str(candidate.get('path'))

            if is_rejected_url(source):
                line['rejected'].append((source, f'у списку забракованих: {reason_for(source)}'))
                self.stdout.write(f'  ✗ {_short(source)} — забраковано раніше')
                continue

            data, error = self._read(candidate)
            if error:
                line['rejected'].append((source, error))
                self.stdout.write(f'  ✗ {_short(source)} — {error}')
                continue

            image, rejection = _photos.screen(data)
            if rejection:
                line['rejected'].append((source, str(rejection)))
                self.stdout.write(f'  ✗ {_short(source)} — {rejection}')
                continue

            value = _photos.dhash(image)

            if is_rejected_hash(value):
                line['rejected'].append((source, f'хеш забраковано: {reason_for(value=value)}'))
                self.stdout.write(f'  ✗ {_short(source)} — хеш у списку забракованих')
                continue

            if _photos.is_duplicate(value, seen.values()):
                line['rejected'].append((source, 'дубль уже наявного кадру'))
                self.stdout.write(f'  ✗ {_short(source)} — дубль')
                continue

            line['accepted'].append(
                {'image': image, 'source': source, 'query': query, 'hash': value}
            )
            self.stdout.write(
                self.style.SUCCESS(f'  ✓ {_short(source)} — {image.size[0]}×{image.size[1]}')
            )

        if line['accepted'] and not self.dry_run:
            self._store(product, line['accepted'])

        return line

    def _read(self, candidate):
        """Прочитати кандидата з диска або з мережі. Повертає (дані, помилка)."""
        path = candidate.get('path')
        if path:
            try:
                return Path(path).read_bytes(), None
            except OSError as exc:
                return None, f'не читається: {exc.strerror or exc}'

        return self._download(candidate['url'])

    def _download(self, url):
        """Точкове завантаження однієї адреси.

        Помилка на конкретному кандидаті — не привід падати: 403 від
        hotlink-захисту, 404, HTML замість картинки трапляються постійно.
        Записуємо причину й беремо наступного.
        """
        try:
            import requests
        except ImportError:
            return None, 'потрібен пакет requests для --from-urls'

        cache = Path(ORIGINALS_DIR) / _cache_name(url)
        if cache.exists() and not self.force:
            return cache.read_bytes(), None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = requests.get(
                    url,
                    timeout=REQUEST_TIMEOUT,
                    headers={'User-Agent': USER_AGENT, 'Accept': 'image/*'},
                )
            except Exception as exc:
                if attempt == MAX_ATTEMPTS:
                    return None, f'мережа: {type(exc).__name__}'
                time.sleep(REQUEST_PAUSE)
                continue

            # Пауза після кожного запиту, а не між спробами: качаємо в один
            # потік і не тиснемо на чужий сервер.
            time.sleep(REQUEST_PAUSE)

            if response.status_code != 200:
                return None, f'HTTP {response.status_code}'

            content_type = response.headers.get('Content-Type', '')
            if 'image' not in content_type:
                return None, f'не зображення ({content_type or "без типу"})'

            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(response.content)
            return response.content, None

        return None, 'не вдалося завантажити'

    @transaction.atomic
    @transaction.atomic
    def _store(self, product, accepted):
        """Записати три зображення товару: обкладинка, другий ракурс, макро.

        Другий ракурс — це другий придатний кандидат, якщо він знайшовся.
        Якщо ні, беремо ширший кроп першого: це інше кадрування того самого
        знімка, а не копія — на картці товару воно виконує ту саму роль, і
        видавати його за окрему зйомку ми ніде не намагаємось.
        """
        primary = accepted[0]
        secondary = accepted[1] if len(accepted) > 1 else None

        rendered = _photos.process(primary['image'], seed=product.id, graded=self.graded)

        if secondary is not None:
            angle = _photos.process(secondary['image'], seed=product.id + 1, graded=self.graded)[
                'full'
            ]
            angle_source = secondary
        else:
            wider = _photos.crop_to_ratio(primary['image'], headroom=0.02)
            if self.graded:
                wider = _photos.grade(wider, seed=product.id + 2)
            angle = _photos.encode_webp(wider.convert('RGB'), _photos.FULL_SIZE)
            angle_source = primary

        # Файли прибираємо явно. `delete()` на моделі зносить лише рядки:
        # Django не видаляє вкладення з часів 1.3, і без цього кожен прогін
        # із `--force` лишав у `media/` осиротілий набір. За кілька
        # переімпортів тека виростала вдвічі-втричі, а Django ще й додавав
        # файлам суфікси, бо імена були зайняті.
        for stale in product.images.all():
            stale.image.delete(save=False)
        product.images.all().delete()

        if product.cover:
            product.cover.delete(save=False)

        # Хеш джерела в імені — щоб новий кадр мав нову адресу. З тим самим
        # іменем браузер віддавав зі свого кешу стару картинку: файл на диску
        # уже інший, а адреса та сама.
        tag = f'{primary["hash"]:016x}'[:8]
        product.cover.save(
            f'{product.slug}-photo-{tag}.webp', ContentFile(rendered['full']), save=False
        )
        product.save(update_fields=['cover', 'modified_at'])

        alt = _alt_text(product)
        plan = (
            ('thumb', rendered['thumb'], primary),
            ('angle', angle, angle_source),
            ('macro', rendered['macro'], primary),
        )

        for order, (suffix, payload, source) in enumerate(plan):
            image = ProductImage(
                product=product,
                is_main=order == 0,
                sort_order=order,
                alt_text=alt,
                source_url=_source_uri(source['source']),
                source_query=source['query'],
                source_hash=f'{source["hash"]:016x}',
            )
            source_tag = f'{source["hash"]:016x}'[:8]
            image.image.save(
                f'{product.slug}-{suffix}-{source_tag}.webp', ContentFile(payload), save=False
            )
            image.save()

    # --- звіт ------------------------------------------------------------

    def _report(self, report):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('ПІДСУМОК'))

        done = [line for line in report if line['accepted']]
        left = [line for line in report if not line['accepted']]

        self.stdout.write(f'  фотографії заведено: {len(done)}')
        self.stdout.write(f'  лишились на рендері: {len(left)}')

        if left:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('  Рендер (фото не знайшлося):'))
            for line in left:
                self.stdout.write(f'    · {line["product"].name}')

        rejected = sum(len(line['rejected']) for line in report)
        if rejected:
            self.stdout.write('')
            self.stdout.write(f'  відсіяно кандидатів: {rejected}')

        if self.dry_run:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('  Сухий прогін — нічого не збережено.'))


def _short(source, width=52):
    text = str(source)
    return text if len(text) <= width else f'{text[:width - 1]}…'


def _source_uri(source):
    """Джерело у вигляді URI — і для мережі, і для локального файлу.

    Локальний шлях теж має лишитись у базі: заміна зображень колись
    почнеться саме з питання «звідки це взялося», і відповідь «з якоїсь теки»
    її не наблизить. `file://` — валідний URL, тож поле лишається одне.
    """
    if source.startswith(('http://', 'https://')):
        return source

    try:
        return Path(source).resolve().as_uri()
    except (OSError, ValueError):
        return ''


def _cache_name(url):
    """Імʼя файлу в кеші оригіналів — стабільне для однієї адреси."""
    import hashlib

    return f'{hashlib.sha1(url.encode()).hexdigest()[:16]}.bin'


def _alt_text(product):
    """Осмислений alt: назва, бренд і головна нота серця."""
    heart = (
        ProductNote.objects.filter(product=product, layer=ProductNote.LAYER_HEART)
        .select_related('note')
        .first()
    )
    if heart:
        return f'{product.name} — {product.brand.name}, нота {heart.note.name}'
    return f'{product.name} — {product.brand.name}'

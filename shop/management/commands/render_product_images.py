"""Генерує зображення товарів рейтрейсером на numpy.

    python manage.py render_product_images --only=kedrova-tysha   # одна ітерація
    python manage.py render_product_images --limit=10             # партія з десяти
    python manage.py render_product_images --force                # перемалювати все

Команда відновлювана: без `--force` вона пропускає товари, у яких зображення
вже є, тож перерваний прогін просто продовжується з місця зупинки. Один товар
рендериться близько двох хвилин, тому ганяти краще партіями (`--limit=10`),
а не одним запуском на годину: довгий фоновий процес не переживає кінець сесії.

Специфікація кадру — в `ART_DIRECTION.md`. Ніякої мережі й сторонніх
3D-бібліотек: проєкт має підніматись із нуля будь-де.
"""

import hashlib
import io
import time

import numpy as np
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image

from shop.models import Product, ProductImage, ProductNote

from ._render import LIQUID_COLORS, Bottle, apply_film, render_frame

# Фінальні розміри з ART_DIRECTION.md.
FULL_SIZE = (1200, 1500)
THUMB_SIZE = (600, 750)
SUPERSAMPLE = 2

WEBP_QUALITY = 84

# Категорія → ольфакторний профіль для кольору товщі скла.
CATEGORY_LIQUID = {
    'derevni': 'woody',
    'kvitkovi': 'floral',
    'ambrovi': 'amber',
    'tsytrusovi': 'citrus',
    'hurmanski': 'gourmand',
    'shkira-i-tyutyun': 'leather',
    'akvatychni': 'aquatic',
    'svichky': 'woody',
    'dyfuzory': 'floral',
    'aromasprei': 'citrus',
    'discovery-sety': 'neutral',
    'travel-10ml': 'woody',
    'refily': 'amber',
}

# Концентрація → пропорції корпусу (ART_DIRECTION.md).
CONCENTRATION_SHAPES = {
    Product.CONCENTRATION_EXTRAIT: {'width': 1.06, 'height': 0.80, 'cap': 1.20},
    Product.CONCENTRATION_EDP: {'width': 0.96, 'height': 1.00, 'cap': 1.00},
    Product.CONCENTRATION_EDT: {'width': 0.86, 'height': 1.18, 'cap': 0.90},
    Product.CONCENTRATION_EDC: {'width': 0.80, 'height': 1.30, 'cap': 0.84},
    Product.CONCENTRATION_OIL: {'width': 0.72, 'height': 1.10, 'cap': 0.78},
    '': {'width': 1.10, 'height': 0.78, 'cap': 0.55},  # свічки, дифузори, сети
}

# Три ракурси: (суфікс, позиція камери, ціль, кут огляду, нахил).
VIEWS = [
    (
        'front',
        np.array([0.0, 0.55, 7.4], dtype=np.float32),
        np.array([0.0, 0.30, 0.0], dtype=np.float32),
        15.5,
        0.0,
    ),
    (
        'three-quarter',
        np.array([3.5, 1.05, 6.3], dtype=np.float32),
        np.array([0.0, 0.28, 0.0], dtype=np.float32),
        16.0,
        0.02,
    ),
    (
        'macro',
        np.array([1.35, 1.62, 3.05], dtype=np.float32),
        np.array([0.0, 1.02, 0.0], dtype=np.float32),
        20.0,
        0.0,
    ),
]


def seed_from_slug(slug):
    """Детермінованість: той самий товар завжди рендериться однаково."""
    digest = hashlib.sha256(slug.encode('utf-8')).digest()
    return int.from_bytes(digest[:8], 'big')


def build_shape(product, rng):
    """Пропорції флакона: від концентрації плюс невелика варіація від slug-а."""
    profile = CONCENTRATION_SHAPES.get(
        product.concentration, CONCENTRATION_SHAPES[Product.CONCENTRATION_EDP]
    )
    jitter = rng.uniform(0.94, 1.06)

    # Масштаб підібраний так, щоб флакон займав близько 60% висоти кадру
    # і зверху лишалося повітря — як у каталожній предметці.
    width = 0.30 * profile['width'] * jitter
    height = 0.40 * profile['height']
    depth = width * rng.uniform(0.42, 0.56)

    return {
        'body': (width, height, depth),
        # Більший радіус ребра = довший шлях променя біля краю = темніший
        # контур. Це та сама «фаска», за якою впізнають скляний флакон.
        'body_radius': width * rng.uniform(0.20, 0.34),
        'neck_radius': width * rng.uniform(0.24, 0.32),
        'neck_height': height * 0.13,
        'cap': (
            width * 0.46 * profile['cap'],
            height * 0.20 * profile['cap'],
            depth * 0.62 * profile['cap'],
        ),
        'cap_radius': width * 0.05,
    }


def liquid_for(product):
    profile = CATEGORY_LIQUID.get(product.category.slug, 'neutral')
    return LIQUID_COLORS[profile]


def encode_webp(array, size):
    """numpy → WebP у памʼяті. Ресайз завжди з великого кадру."""
    image = Image.fromarray(array, mode='RGB').resize(size, Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format='WEBP', quality=WEBP_QUALITY, method=6)
    return buffer.getvalue()


class Command(BaseCommand):
    help = 'Рендерить зображення товарів (SDF-рейтрейсер на numpy)'

    def add_arguments(self, parser):
        parser.add_argument('--only', help='Відрендерити лише один товар за slug')
        parser.add_argument(
            '--force', action='store_true', help='Перемалювати навіть те, що вже має зображення'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Відрендерити щонайбільше N товарів за запуск — щоб ганяти партіями',
        )
        parser.add_argument(
            '--scale',
            type=float,
            default=1.0,
            help='Множник роздільності для швидкої ітерації (0.5 = вчетверо швидше)',
        )

    def handle(self, *args, **options):
        products = Product.objects.select_related('category', 'brand').order_by('sku')
        if options['only']:
            products = products.filter(slug=options['only'])

        if not products.exists():
            self.stderr.write('Не знайдено жодного товару.')
            return

        total = products.count()
        pending = [item for item in products if options['force'] or not self._is_done(item)]
        skipped = total - len(pending)

        if skipped:
            self.stdout.write(f'· Пропущено готових: {skipped}')

        # Порожній список перевіряємо ДО обрізання лімітом: інакше
        # `--limit=0` рапортував би «усі готові», хоч це неправда.
        if not pending:
            self.stdout.write(self.style.SUCCESS('Усі товари вже мають зображення.'))
            return

        if options['limit'] is not None:
            pending = pending[: options['limit']]
            if not pending:
                self.stdout.write('Ліміт 0 — нічого не рендерю.')
                return

        total_bytes = 0
        started = time.time()

        for index, product in enumerate(pending, start=1):
            elapsed, written = self._render_product(product, options['scale'])
            total_bytes += written
            self.stdout.write(
                f'✓ [{index}/{len(pending)}] {product.name:34.34} '
                f'{written / 1024:7.0f} КБ  {elapsed:5.1f} с'
            )

        ready = Product.objects.exclude(cover='').count()
        self.stdout.write(
            self.style.SUCCESS(
                f'\nПартія з {len(pending)} за {time.time() - started:.0f} с, '
                f'{total_bytes / 1024 / 1024:.1f} МБ. '
                f'Загалом готово {ready}/{Product.objects.count()}.'
            )
        )

    def _is_done(self, product):
        """Товар готовий, лише коли є і обкладинка, і всі три ракурси.

        Перевіряти саму обкладинку замало: прогін могло обірвати посеред
        товару, і тоді в базі лишається напівготовий набір, який мовчки
        стояв би без двох ракурсів назавжди.
        """
        return bool(product.cover) and product.images.count() >= len(VIEWS)

    def _render_product(self, product, scale):
        started = time.time()
        rng = np.random.default_rng(seed_from_slug(product.slug))

        bottle = Bottle(build_shape(product, rng))
        liquid = liquid_for(product)

        width = int(FULL_SIZE[0] * SUPERSAMPLE * scale)
        height = int(FULL_SIZE[1] * SUPERSAMPLE * scale)

        # Перемальовуємо повністю: інакше повторний --force плодив би
        # зображення замість того, щоб їх замінювати.
        for old in product.images.all():
            old.image.delete(save=False)
        product.images.all().delete()
        if product.cover:
            product.cover.delete(save=False)

        written = 0

        for index, (suffix, camera, target, fov, roll) in enumerate(VIEWS):
            linear = render_frame(bottle, liquid, width, height, camera, target, fov, roll)
            pixels = apply_film(linear, rng)

            full = encode_webp(pixels, FULL_SIZE)
            name = f'{product.slug}-{suffix}.webp'

            if index == 0:
                # Фронтальний кадр — обкладинка каталогу.
                product.cover.save(name, ContentFile(full), save=False)
                written += len(full)

                thumb = encode_webp(pixels, THUMB_SIZE)
                written += len(thumb)
                self._add_image(product, f'{product.slug}-thumb.webp', thumb, is_main=True, order=0)
            else:
                written += len(full)
                self._add_image(product, name, full, is_main=False, order=index)

        product.save(update_fields=['cover', 'modified_at'])
        return time.time() - started, written

    def _add_image(self, product, name, payload, is_main, order):
        image = ProductImage(
            product=product,
            is_main=is_main,
            sort_order=order,
            alt_text=self._alt_text(product),
        )
        image.image.save(name, ContentFile(payload), save=False)
        image.save()

    def _alt_text(self, product):
        """Осмислений alt: назва, бренд і головна нота серця."""
        heart = (
            ProductNote.objects.filter(product=product, layer=ProductNote.LAYER_HEART)
            .select_related('note')
            .first()
        )
        tail = f', {heart.note.name}' if heart else ''
        return f'{product.name} — {product.brand.name}{tail}'

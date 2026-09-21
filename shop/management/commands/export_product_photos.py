"""Вивантажити готові фото каталогу з медіа в репозиторій.

Пара до `load_product_photos`. Фото готуються локально —
`fetch_product_photos` качає, відсіює й кадрує, — а `media/` у git не
потрапляє. Ця команда кладе результат у `shop/photos/catalogue/<slug>/`
разом із маніфестом, і вже звідти прод заводить його без numpy.

Експортуються лише фото з відомим джерелом (`source_url`). Рендери й ручні
завантаження лишаються там, де лежать.
"""

import json
import shutil
from pathlib import Path

from django.core.management.base import BaseCommand

from shop.models import Product

from .load_product_photos import DEFAULT_DIR, MANIFEST


class Command(BaseCommand):
    help = 'Вивантажує фото каталогу з медіа в shop/photos/catalogue/'

    def add_arguments(self, parser):
        parser.add_argument(
            '--target',
            metavar='DIR',
            default=str(DEFAULT_DIR),
            help='куди вивантажити (за замовчуванням shop/photos/catalogue/)',
        )

    def handle(self, *args, **options):
        root = Path(options['target'])
        # Тека перезбирається цілком: товар, якому фото прибрали, не має
        # лишитись у маніфесті зі старим кадром.
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)

        manifest = {}
        products = (
            Product.objects.filter(images__source_url__gt='')
            .distinct()
            .order_by('slug')
            .prefetch_related('images')
        )

        for product in products:
            images = [image for image in product.images.all() if image.source_url]
            if not images or not product.cover:
                continue

            folder = root / product.slug
            folder.mkdir()
            _copy(product.cover, folder / 'cover.webp')

            entries = []
            for image in images:
                name = f'{_role(image, product.slug)}.webp'
                _copy(image.image, folder / name)
                entries.append(
                    {
                        'file': name,
                        'is_main': image.is_main,
                        'sort_order': image.sort_order,
                        'alt_text': image.alt_text,
                        'source_url': image.source_url,
                        'source_query': image.source_query,
                        'source_hash': image.source_hash,
                    }
                )

            manifest[product.slug] = {'cover': 'cover.webp', 'images': entries}

        (root / MANIFEST).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )

        size = sum(f.stat().st_size for f in root.rglob('*.webp'))
        self.stdout.write(
            self.style.SUCCESS(
                f'Вивантажено {len(manifest)} товарів, {size / 1048576:.1f} МБ → {root}'
            )
        )


def _role(image, slug):
    """Роль кадру з імені файлу: thumb, angle, macro.

    Після slug в імені йдуть роль, хеш джерела й, можливо, суфікс Django на
    випадок зайнятого імені: `kedrova-tysha-thumb-a42273f2_DR0s0rC`. Беремо
    перше слово, а за його відсутності — порядок.
    """
    stem = Path(image.image.name).stem
    role = stem.removeprefix(f'{slug}-').replace('_', '-').split('-', 1)[0]
    return role or f'shot-{image.sort_order}'


def _copy(field, destination):
    with field.open('rb') as source:
        destination.write_bytes(source.read())

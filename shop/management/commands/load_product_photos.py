"""Завести готові фото каталогу з репозиторію в базу й медіа.

Навіщо окрема команда, коли є `fetch_product_photos`. Той качає, відсіює й
зводить кадри — і тягне за собою numpy, якого в прод-образі немає: його
прибрали, щоб образ схуд на ~69 МБ. Тому фото готуються там, де готують
контент, і експортуються в `shop/photos/catalogue/` командою
`export_product_photos`. Ця команда лише розкладає вже готові файли — на
Pillow і стандартній бібліотеці.

Запускається на кожному старті контейнера, а не лише на першому. На
безкоштовному Render диск стирається при кожному перезапуску, а база
лишається: рядки зображень на місці, файлів під ними вже немає. Тому
команда перевіряє не «чи є рядки», а «чи є файли», і відновлює те, що
зникло. Коли все на місці, вона нічого не пише.

Чужих фото команда не чіпає. Товар, у якого є зображення без `source_url`
(завантажене через адмінку), пропускається — без `--force` його ніхто не
перезапише.
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from shop.models import Product, ProductImage

DEFAULT_DIR = Path(settings.BASE_DIR) / 'shop' / 'photos' / 'catalogue'
MANIFEST = 'manifest.json'


class Command(BaseCommand):
    help = 'Заводить готові фото каталогу з shop/photos/catalogue/'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            metavar='DIR',
            default=str(DEFAULT_DIR),
            help='тека з експортом (за замовчуванням shop/photos/catalogue/)',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='перезаписати й ті фото, що завантажені вручну',
        )

    def handle(self, *args, **options):
        root = Path(options['source'])
        manifest_path = root / MANIFEST
        if not manifest_path.exists():
            raise CommandError(f'Немає {manifest_path}. Спершу export_product_photos.')

        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        products = Product.objects.filter(slug__in=manifest).prefetch_related('images')

        counts = {'loaded': 0, 'current': 0, 'manual': 0}
        for product in products:
            entry = manifest[product.slug]

            if not options['force'] and _has_manual_images(product):
                counts['manual'] += 1
                continue

            if _is_current(product, entry):
                counts['current'] += 1
                continue

            self._load(product, entry, root / product.slug)
            counts['loaded'] += 1

        missing = len(manifest) - products.count()
        self.stdout.write(
            f'Фото каталогу: заведено {counts["loaded"]}, актуальних {counts["current"]}, '
            f'пропущено з ручними фото {counts["manual"]}'
            + (f', товарів немає в базі: {missing}' if missing else '')
        )

    @transaction.atomic
    def _load(self, product, entry, folder):
        # Файли прибираємо явно: `delete()` на моделі зносить лише рядки, і
        # без цього кожен перезапуск лишав би в медіа осиротілі копії.
        for stale in product.images.all():
            stale.image.delete(save=False)
        product.images.all().delete()
        if product.cover:
            product.cover.delete(save=False)

        # Хеш у імені — нова адреса для нового кадру, інакше браузер
        # показував би стару картинку зі свого кешу.
        tag = entry['images'][0]['source_hash'][:8]
        product.cover.save(
            f'{product.slug}-photo-{tag}.webp',
            ContentFile((folder / entry['cover']).read_bytes()),
            save=False,
        )
        product.save(update_fields=['cover', 'modified_at'])

        for item in entry['images']:
            image = ProductImage(
                product=product,
                is_main=item['is_main'],
                sort_order=item['sort_order'],
                alt_text=item['alt_text'],
                source_url=item['source_url'],
                source_query=item['source_query'],
                source_hash=item['source_hash'],
            )
            image.image.save(
                f'{product.slug}-{Path(item["file"]).stem}-{item["source_hash"][:8]}.webp',
                ContentFile((folder / item['file']).read_bytes()),
                save=False,
            )
            image.save()


def _has_manual_images(product):
    """Чи є в товару зображення, завантажене не конвеєром, а людиною."""
    return any(not image.source_url for image in product.images.all())


def _is_current(product, entry):
    """Чи в базі вже ці самі кадри — і чи лежать під ними файли.

    Порівнюємо хеші джерел, а не імена файлів: Django додає до імен суфікси,
    коли ім'я зайняте, і за іменем актуальний набір виглядав би застарілим.
    """
    images = list(product.images.all())
    expected = sorted(item['source_hash'] for item in entry['images'])
    if sorted(image.source_hash for image in images) != expected:
        return False

    storage_files = [image.image for image in images]
    if product.cover:
        storage_files.append(product.cover)
    else:
        return False

    return all(field.storage.exists(field.name) for field in storage_files)

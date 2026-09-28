"""Контактний лист: усі обкладинки каталогу однією сіткою.

Єдиний спосіб побачити різнобій. По одному кадру все завжди виглядає
прийнятно — око не має з чим порівняти; поруч одразу видно, який випадає за
експозицією, фоном чи кропом.

Запасні рендери мають лягти в той самий ряд, а не кричати, що вони з
іншої опери, — тому вони теж потрапляють на лист, і кожен кадр підписаний.
"""

from pathlib import Path

from django.core.management.base import BaseCommand
from PIL import Image, ImageDraw

from shop.models import Product

from ._photos import BLACK_FLOOR

# 5 колонок × 6 рядків = 30 товарів.
COLUMNS = 5
CELL = (240, 300)
GAP = 10
LABEL_HEIGHT = 26

BACKGROUND = tuple((BLACK_FLOOR * 255).astype(int).tolist())
INK = (156, 147, 166)
BRASS = (200, 164, 92)


class Command(BaseCommand):
    help = 'Збирає контактний лист з обкладинок усіх товарів'

    def add_arguments(self, parser):
        parser.add_argument(
            '--out',
            default='contact-sheet.webp',
            help='куди зберегти (за замовчуванням contact-sheet.webp у корені)',
        )
        parser.add_argument(
            '--source',
            choices=['cover', 'original'],
            default='cover',
            help='cover — обкладинки каталогу; original — вхідні кадри до грейду',
        )

    def handle(self, *args, **options):
        products = list(
            Product.objects.select_related('brand').prefetch_related('images').order_by('id')
        )
        if not products:
            self.stdout.write(self.style.WARNING('Товарів немає.'))
            return

        rows = (len(products) + COLUMNS - 1) // COLUMNS
        cell_h = CELL[1] + LABEL_HEIGHT

        sheet = Image.new(
            'RGB',
            (
                COLUMNS * CELL[0] + (COLUMNS + 1) * GAP,
                rows * cell_h + (rows + 1) * GAP,
            ),
            BACKGROUND,
        )
        draw = ImageDraw.Draw(sheet)

        photos = renders = 0

        for index, product in enumerate(products):
            column, row = index % COLUMNS, index // COLUMNS
            x = GAP + column * (CELL[0] + GAP)
            y = GAP + row * (cell_h + GAP)

            is_photo = product.images.filter(source_url__gt='').exists()
            photos += is_photo
            renders += not is_photo

            thumb = self._thumbnail(product)
            if thumb is not None:
                sheet.paste(thumb, (x, y))
            else:
                draw.rectangle([x, y, x + CELL[0], y + CELL[1]], outline=INK)
                draw.text((x + 8, y + CELL[1] // 2), 'немає зображення', fill=INK)

            # Підпис: номер, назва і позначка «рендер» — щоб на листі було
            # видно не тільки різнобій, а й що саме не є фотографією.
            label = f'{index + 1:02d}  {product.name}'
            draw.text((x + 2, y + CELL[1] + 6), label[:34], fill=INK)
            if not is_photo:
                draw.text((x + CELL[0] - 46, y + 6), 'рендер', fill=BRASS)

        out = Path(options['out'])
        sheet.save(out, format='WEBP', quality=90, method=6)

        self.stdout.write(
            self.style.SUCCESS(
                f'Контактний лист: {out} ({sheet.size[0]}×{sheet.size[1]}, '
                f'{out.stat().st_size / 1024:.0f} КБ)'
            )
        )
        self.stdout.write(f'  фотографії: {photos}')
        self.stdout.write(f'  рендери: {renders}')

    def _thumbnail(self, product):
        source = product.cover
        if not source:
            return None

        try:
            with source.open('rb') as handle:
                image = Image.open(handle)
                image.load()
        except Exception:
            return None

        return image.convert('RGB').resize(CELL, Image.LANCZOS)

"""Готові фото каталогу: експорт у репозиторій і заведення назад на старті.

На безкоштовному Render диск стирається при кожному перезапуску, а база
лишається. Тому головне тут — не «команда створює рядки», а «команда
помічає, що файлів під рядками вже немає, і повертає їх».
"""

import io
import json
import shutil
import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from PIL import Image

from shop.models import ProductImage
from testing import ShopTestCase
from testing.factories import ProductFactory


def webp(colour):
    buffer = io.BytesIO()
    Image.new('RGB', (120, 150), colour).save(buffer, format='WEBP')
    return buffer.getvalue()


class PhotoBundleTests(ShopTestCase):
    def setUp(self):
        self.media = Path(self._tempdir())
        self.source = Path(self._tempdir())
        override = self.settings(MEDIA_ROOT=str(self.media))
        override.enable()
        self.addCleanup(override.disable)

        self.product = ProductFactory(slug='kedrova-tysha')
        self._write_bundle(self.product.slug, hash_value='a42273f2981a9acd')

    def _tempdir(self):
        path = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, path, True)
        return path

    def _write_bundle(self, slug, hash_value):
        folder = self.source / slug
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'cover.webp').write_bytes(webp((40, 30, 20)))

        images = []
        for order, role in enumerate(('thumb', 'angle', 'macro')):
            (folder / f'{role}.webp').write_bytes(webp((order * 60, 20, 20)))
            images.append(
                {
                    'file': f'{role}.webp',
                    'is_main': order == 0,
                    'sort_order': order,
                    'alt_text': 'Кедрова тиша — тест',
                    'source_url': 'https://images.unsplash.com/photo-test',
                    'source_query': 'Unsplash · Viki C',
                    'source_hash': hash_value,
                }
            )

        manifest_path = self.source / 'manifest.json'
        manifest = (
            json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
        )
        manifest[slug] = {'cover': 'cover.webp', 'images': images}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')

    def load(self, *args):
        out = io.StringIO()
        call_command('load_product_photos', '--source', str(self.source), *args, stdout=out)
        return out.getvalue()

    def test_bundle_becomes_cover_and_three_images(self):
        self.load()

        self.product.refresh_from_db()
        images = list(self.product.images.order_by('sort_order'))
        self.assertTrue(self.product.cover)
        self.assertEqual([image.sort_order for image in images], [0, 1, 2])
        self.assertEqual([image.is_main for image in images], [True, False, False])
        self.assertEqual(images[0].source_query, 'Unsplash · Viki C')
        for image in images:
            self.assertTrue(image.image.storage.exists(image.image.name))

    def test_second_run_writes_nothing(self):
        """Коли все на місці, перезапуск контейнера не чіпає ні рядків, ні файлів."""
        self.load()
        before = sorted(ProductImage.objects.values_list('id', flat=True))

        output = self.load()

        self.assertEqual(sorted(ProductImage.objects.values_list('id', flat=True)), before)
        self.assertIn('актуальних 1', output)

    def test_files_wiped_from_disk_are_restored(self):
        """Саме сценарій Render: рядки в базі є, файлів під ними вже немає."""
        self.load()
        main = self.product.images.get(is_main=True)
        main.image.storage.delete(main.image.name)

        self.load()

        restored = self.product.images.get(is_main=True)
        self.assertTrue(restored.image.storage.exists(restored.image.name))

    def test_changed_photo_replaces_the_old_one(self):
        self.load()
        self._write_bundle(self.product.slug, hash_value='00000000000000ff')

        self.load()

        hashes = set(self.product.images.values_list('source_hash', flat=True))
        self.assertEqual(hashes, {'00000000000000ff'})

    def test_new_photo_gets_a_new_address(self):
        """З тим самим іменем браузер показував би стару картинку зі свого кешу."""
        self.load()
        self.product.refresh_from_db()
        old_cover = self.product.cover.name
        old_main = self.product.images.get(is_main=True).image.name

        self._write_bundle(self.product.slug, hash_value='00000000000000ff')
        self.load()
        self.product.refresh_from_db()

        self.assertNotEqual(self.product.cover.name, old_cover)
        self.assertNotEqual(self.product.images.get(is_main=True).image.name, old_main)

    def test_manually_uploaded_photo_is_left_alone(self):
        """Фото з адмінки не має зникати через те, що контейнер перезапустився."""
        manual = ProductImage(product=self.product, is_main=True, alt_text='Своє фото')
        manual.image.save('own.webp', io.BytesIO(webp((200, 200, 200))), save=True)

        output = self.load()

        self.assertEqual(list(self.product.images.all()), [manual])
        self.assertIn('пропущено з ручними фото 1', output)

    def test_force_replaces_manual_photo(self):
        manual = ProductImage(product=self.product, is_main=True)
        manual.image.save('own.webp', io.BytesIO(webp((200, 200, 200))), save=True)

        self.load('--force')

        self.assertFalse(ProductImage.objects.filter(pk=manual.pk).exists())
        self.assertEqual(self.product.images.count(), 3)

    def test_export_then_load_is_a_round_trip(self):
        """Експорт віддає рівно те, що load потім заведе назад."""
        self.load()
        target = Path(self._tempdir()) / 'catalogue'

        call_command('export_product_photos', '--target', str(target), stdout=io.StringIO())

        manifest = json.loads((target / 'manifest.json').read_text(encoding='utf-8'))
        entry = manifest[self.product.slug]
        self.assertEqual(
            sorted(item['file'] for item in entry['images']),
            ['angle.webp', 'macro.webp', 'thumb.webp'],
        )
        for item in entry['images']:
            self.assertTrue((target / self.product.slug / item['file']).exists())
        self.assertTrue((target / self.product.slug / 'cover.webp').exists())

    def test_missing_manifest_is_a_clear_error(self):
        with self.assertRaises(CommandError):
            call_command('load_product_photos', '--source', self._tempdir())

"""Фотоконвеєр: відсів, дедуплікація, грейд, слід джерела.

Головна перевірка тут — **збіжність**: кадри з різними експозицією, балансом
білого й фоном мають вийти з конвеєра з однаковими тональними
характеристиками. Це не косметика, а сама суть етапу: каталог із тридцяти
різних зйомок виглядає як маркетплейс, і жодна верстка цього не виправляє.

Тому тести міряють числа, а не «виглядає добре»: розкид медіанної яскравості,
залишковий колірний відлив, межі палітри.
"""

import io
import statistics
from pathlib import Path

import numpy as np
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from PIL import Image

from shop.management.commands import _photos
from shop.models import ProductImage
from testing import ShopTestCase
from testing.factories import ProductFactory


def synthetic_bottle(
    size=(1200, 1500),
    exposure=1.0,
    tint=(1.0, 1.0, 1.0),
    background=(30, 28, 34),
):
    """Кадр «флакон на тлі» із заданою експозицією, відливом і фоном.

    Не фотографія, але має те, що конвеєру потрібно: світлий предмет у центрі,
    темніше тло, градієнт і шум. Саме на різниці цих параметрів між кадрами
    перевіряється зведення до однієї зйомки.
    """
    width, height = size
    rng = np.random.default_rng(7)

    array = np.zeros((height, width, 3), dtype=np.float32)
    array[:, :] = np.array(background, dtype=np.float32) / 255.0

    # Градієнт тла по двох осях: рівна заливка відсіялась би як «плаский кадр»,
    # і це правильно — у справжньому кадрі рівного тла не буває.
    ramp_y = np.linspace(0.75, 1.25, height, dtype=np.float32)[:, None, None]
    ramp_x = np.linspace(0.92, 1.08, width, dtype=np.float32)[None, :, None]
    array *= ramp_y * ramp_x

    # Предмет: світлий прямокутник із заокругленням у центрі.
    x0, x1 = int(width * 0.30), int(width * 0.70)
    y0, y1 = int(height * 0.22), int(height * 0.80)
    array[y0:y1, x0:x1] = np.array([0.72, 0.70, 0.66], dtype=np.float32)

    # Відблиск — щоб баланс білого мав за що зачепитись.
    array[y0 + 40 : y0 + 200, x0 + 40 : x0 + 140] = 0.95

    array *= np.array(tint, dtype=np.float32)
    array *= exposure

    # Зерно помітне навмисно: воно дає кадру ту кількість унікальних кольорів,
    # за якою відсів відрізняє фотографію від графіки.
    array += rng.normal(0.0, 0.030, array.shape).astype(np.float32)

    return Image.fromarray((np.clip(array, 0, 1) * 255).astype(np.uint8), mode='RGB')


def as_jpeg(image, quality=90):
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=quality)
    return buffer.getvalue()


class ScreeningTests(SimpleTestCase):
    """На вході сміття, і воно не має доходити до каталогу."""

    def test_valid_photo_passes(self):
        image, rejection = _photos.screen(as_jpeg(synthetic_bottle()))

        self.assertIsNone(rejection)
        self.assertIsNotNone(image)

    def test_html_instead_of_image_is_rejected(self):
        image, rejection = _photos.screen(b'<!DOCTYPE html><html><body>404</body></html>')

        self.assertIsNone(image)
        self.assertEqual(rejection.reason, 'не зображення')

    def test_small_image_is_rejected(self):
        image, rejection = _photos.screen(as_jpeg(synthetic_bottle(size=(600, 750))))

        self.assertIsNone(image)
        self.assertEqual(rejection.reason, 'замалий')

    def test_banner_proportions_are_rejected(self):
        image, rejection = _photos.screen(as_jpeg(synthetic_bottle(size=(3000, 1000))))

        self.assertIsNone(image)
        self.assertEqual(rejection.reason, 'банер')

    def test_low_key_studio_shot_on_black_is_accepted(self):
        """Предмет на придавленому до чорного тлі — це зйомка, а не заливка.

        Так знімають нуарну предметку: фон свідомо зрізаний у нуль, і один
        тон займає три чверті кадру. Фільтр заливки відсіював саме такі кадри
        — свічки, флакон на чорному, — хоча вони якраз у стилі каталогу.
        """
        rng = np.random.default_rng(7)
        pixels = np.zeros((1750, 1400, 3), dtype=np.uint8)
        # Предмет — чверть кадру з живою фактурою: шум дає тисячі кольорів.
        pixels[500:1250, 450:950] = rng.integers(40, 220, size=(750, 500, 3), dtype=np.uint8)

        image, rejection = _photos.screen(as_jpeg(Image.fromarray(pixels)))

        self.assertIsNone(rejection)
        self.assertIsNotNone(image)

    def test_white_logo_on_black_is_still_rejected(self):
        """Послаблення для чорного тла не пропускає графіку.

        Логотип на чорному має кілька кольорів — його ловить перевірка на
        кількість кольорів, а не на заливку.
        """
        flat = Image.new('RGB', (1400, 1400), (0, 0, 0))
        flat.paste(Image.new('RGB', (400, 400), (250, 250, 250)), (500, 500))

        image, rejection = _photos.screen(as_jpeg(flat))

        self.assertIsNone(image)
        self.assertIn(rejection.reason, {'плаский кадр', 'заливка'})

    def test_flat_logo_is_rejected(self):
        """Двоколірна картинка — це логотип, а не предметна зйомка."""
        flat = Image.new('RGB', (1400, 1400), (255, 255, 255))
        flat.paste(Image.new('RGB', (400, 400), (10, 10, 10)), (500, 500))

        image, rejection = _photos.screen(as_jpeg(flat))

        self.assertIsNone(image)
        self.assertIn(rejection.reason, {'плаский кадр', 'заливка'})


class PerceptualHashTests(SimpleTestCase):
    def test_same_image_survives_recompression(self):
        original = synthetic_bottle()
        recompressed = Image.open(io.BytesIO(as_jpeg(original, quality=55)))

        distance = _photos.hamming(_photos.dhash(original), _photos.dhash(recompressed))

        self.assertLessEqual(distance, _photos.DHASH_THRESHOLD)

    def test_same_image_survives_resize(self):
        original = synthetic_bottle()
        smaller = original.resize((700, 875), Image.LANCZOS)

        distance = _photos.hamming(_photos.dhash(original), _photos.dhash(smaller))

        self.assertLessEqual(distance, _photos.DHASH_THRESHOLD)

    def test_different_images_are_far_apart(self):
        """Два різні кадри не мають зійтись за хешем.

        Порівнюються саме горизонтально різні кадри: dHash дивиться на різницю
        між сусідніми пікселями в рядку, тож вертикальне віддзеркалення він
        цілком законно вважає тим самим зображенням.
        """
        left = synthetic_bottle()
        right = (
            synthetic_bottle().transpose(Image.FLIP_LEFT_RIGHT).rotate(8, resample=Image.BICUBIC)
        )

        distance = _photos.hamming(_photos.dhash(left), _photos.dhash(right))

        self.assertGreater(distance, _photos.DHASH_THRESHOLD)

    def test_is_duplicate_uses_the_threshold(self):
        value = _photos.dhash(synthetic_bottle())

        self.assertTrue(_photos.is_duplicate(value, [value]))
        self.assertFalse(_photos.is_duplicate(value, [~value & ((1 << 64) - 1)]))


class GradeConvergenceTests(SimpleTestCase):
    """Ядро етапу: різні джерела на вході — одна зйомка на виході."""

    # Кадри з навмисно різними експозицією, балансом білого й кольором тла —
    # рівно ті осі, по яких різняться знімки з різних джерел.
    SOURCES = [
        {'exposure': 0.55, 'tint': (1.20, 0.92, 0.86), 'background': (120, 40, 90)},
        {'exposure': 1.60, 'tint': (0.86, 1.00, 1.22), 'background': (30, 90, 120)},
        {'exposure': 1.00, 'tint': (1.00, 1.10, 0.80), 'background': (60, 110, 40)},
        {'exposure': 1.35, 'tint': (0.95, 0.95, 1.05), 'background': (200, 195, 190)},
        {'exposure': 0.75, 'tint': (1.05, 1.00, 0.95), 'background': (18, 16, 20)},
    ]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.inputs = [synthetic_bottle(**params) for params in cls.SOURCES]
        cls.outputs = [
            _photos.grade(_photos.crop_to_ratio(image), seed=index)
            for index, image in enumerate(cls.inputs)
        ]

    def spread(self, images, key):
        values = [_photos.measure(image)[key] for image in images]
        return max(values) - min(values)

    def test_brightness_spread_shrinks(self):
        before = self.spread(self.inputs, 'median_luma')
        after = self.spread(self.outputs, 'median_luma')

        self.assertLess(
            after,
            before / 3.0,
            f'Розкид яскравості мав впасти щонайменше втричі: {before:.3f} -> {after:.3f}',
        )

    def test_colour_cast_shrinks(self):
        before = statistics.mean(_photos.measure(i)['corner_cast'] for i in self.inputs)
        after = statistics.mean(_photos.measure(o)['corner_cast'] for o in self.outputs)

        self.assertLess(
            after,
            before / 3.0,
            f'Колірний відлив тла мав впасти щонайменше втричі: {before:.3f} -> {after:.3f}',
        )

    def test_output_brightness_is_consistent(self):
        values = [_photos.measure(o)['median_luma'] for o in self.outputs]

        self.assertLess(
            statistics.pstdev(values),
            0.05,
            f'Кадри однієї зйомки не можуть так різнитись: {[round(v, 3) for v in values]}',
        )

    def test_no_pure_black_or_white(self):
        """Вимога палітри: кадр живе між Нуаром і Кісткою."""
        for index, image in enumerate(self.outputs):
            with self.subTest(source=index):
                array = np.asarray(image, dtype=np.uint8)
                self.assertGreater(int(array.min()), 0, 'з’явився чистий чорний')
                self.assertLess(int(array.max()), 255, 'з’явився чистий білий')

    def test_output_matches_the_reference_range(self):
        """Фото мають лягти в діапазон рендерів B5, а не поруч із ним."""
        curve = _photos.REFERENCE_TONE_CURVE

        for index, image in enumerate(self.outputs):
            with self.subTest(source=index):
                measured = _photos.measure(image)
                self.assertGreaterEqual(measured['black_point'], float(curve[0]) - 0.02)
                self.assertLessEqual(measured['white_point'], float(curve[-1]) + 0.02)

    def test_grade_is_deterministic(self):
        """Той самий кадр і той самий seed — той самий результат."""
        first = _photos.grade(_photos.crop_to_ratio(self.inputs[0]), seed=3)
        second = _photos.grade(_photos.crop_to_ratio(self.inputs[0]), seed=3)

        self.assertEqual(np.asarray(first).tobytes(), np.asarray(second).tobytes())


class AsIsProcessingTests(SimpleTestCase):
    """Режим без грейду: кадри, відібрані під каталог вручну, лишаються собою.

    Грейд писався під синтетичні рендери з кольоровим тлом. На живих фото
    затемнення тла за маскою предмета малювало сірі овальні ореоли, а крива
    постеризувала мох і кавові зерна. Для відібраних кадрів він шкодить.
    """

    def test_ready_4_5_frame_is_not_recropped_or_toned(self):
        source = synthetic_bottle(size=(1200, 1500), tint=(1.2, 0.9, 0.7))

        result = _photos.process(source, graded=False)
        full = Image.open(io.BytesIO(result['full'])).convert('RGB')

        # Той самий кадр, лише перекодований: середній колір не зсунувся.
        before = np.asarray(source.convert('RGB'), dtype=np.float32).mean(axis=(0, 1))
        after = np.asarray(full, dtype=np.float32).mean(axis=(0, 1))
        self.assertLess(float(np.abs(before - after).max()), 3.0)
        self.assertEqual(full.size, _photos.FULL_SIZE)

    def test_graded_mode_still_changes_the_frame(self):
        """Звичайний режим не зачеплено: грейд і далі зводить кадр до палітри."""
        source = synthetic_bottle(size=(1200, 1500), tint=(1.2, 0.9, 0.7))

        result = _photos.process(source)
        full = Image.open(io.BytesIO(result['full'])).convert('RGB')

        before = np.asarray(source.convert('RGB'), dtype=np.float32).mean(axis=(0, 1))
        after = np.asarray(full, dtype=np.float32).mean(axis=(0, 1))
        self.assertGreater(float(np.abs(before - after).max()), 3.0)

    def test_non_4_5_frame_is_still_cropped(self):
        result = _photos.process(synthetic_bottle(size=(2000, 1400)), graded=False)

        full = Image.open(io.BytesIO(result['full']))
        self.assertEqual(full.size, _photos.FULL_SIZE)


class CropTests(SimpleTestCase):
    def test_output_is_four_by_five(self):
        cropped = _photos.crop_to_ratio(synthetic_bottle(size=(2000, 1500)))
        width, height = cropped.size

        self.assertAlmostEqual(width / height, _photos.ASPECT, places=2)

    def test_zoom_stays_inside_bounds(self):
        """Невдало визначена рамка не має заганяти кадр у надмірний зум."""
        source = synthetic_bottle(size=(1600, 2000))
        cropped = _photos.crop_to_ratio(source)

        share = cropped.size[1] / source.size[1]
        self.assertGreaterEqual(share, _photos.MIN_FRAME_SHARE - 0.01)

    def test_macro_crop_is_smaller_and_same_ratio(self):
        base = _photos.crop_to_ratio(synthetic_bottle())
        macro = _photos.macro_crop(base)

        self.assertLess(macro.size[0], base.size[0])
        self.assertAlmostEqual(macro.size[0] / macro.size[1], _photos.ASPECT, places=1)

    def test_process_returns_three_encoded_images(self):
        result = _photos.process(synthetic_bottle(), seed=1)

        self.assertEqual(set(result), {'full', 'thumb', 'macro'})
        for name, payload in result.items():
            with self.subTest(image=name):
                self.assertEqual(payload[:4], b'RIFF', 'очікували WebP')
                image = Image.open(io.BytesIO(payload))
                expected = _photos.THUMB_SIZE if name == 'thumb' else _photos.FULL_SIZE
                self.assertEqual(image.size, expected)


class UserAgentTests(SimpleTestCase):
    """Заголовок, з яким команда ходить у мережу, мусить бути латиницею."""

    def test_user_agent_is_encodable_as_an_http_header(self):
        """HTTP-заголовки — latin-1; кирилиця тут валила кожен запит.

        Решта тестів підміняє `requests.get`, і до кодування заголовка справа
        в них не доходить. Тому саме значення перевіряємо окремо.
        """
        from shop.management.commands.fetch_product_photos import USER_AGENT

        USER_AGENT.encode('latin-1')


class CommandTests(ShopTestCase):
    """Команда: слід джерела, дедуплікація між товарами, --dry-run, --limit."""

    def setUp(self):
        self.root = Path(self.mkdtemp())

    def mkdtemp(self):
        import tempfile

        path = tempfile.mkdtemp()
        self.addCleanup(__import__('shutil').rmtree, path, True)
        return path

    def put(self, slug, image=None, name='source.jpg'):
        folder = self.root / slug
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(as_jpeg(image or synthetic_bottle()))
        return folder / name

    def test_source_is_recorded_for_local_files(self):
        """Локальний шлях — теж джерело, і воно має лишитись у базі."""
        product = ProductFactory(slug='kedrova-tysha')
        self.put(product.slug)

        call_command('fetch_product_photos', from_folder=str(self.root), verbosity=0)

        image = ProductImage.objects.filter(product=product).first()
        self.assertTrue(image.source_url.startswith('file:///'))
        self.assertIn('source.jpg', image.source_query)
        self.assertEqual(len(image.source_hash), 16)

    def test_three_images_per_product(self):
        product = ProductFactory(slug='sandal-07')
        self.put(product.slug)

        call_command('fetch_product_photos', from_folder=str(self.root), verbosity=0)

        self.assertEqual(ProductImage.objects.filter(product=product).count(), 3)
        self.assertEqual(ProductImage.objects.filter(product=product, is_main=True).count(), 1)

    def test_cover_is_written(self):
        product = ProductFactory(slug='iris-siryi')
        self.put(product.slug)

        call_command('fetch_product_photos', from_folder=str(self.root), verbosity=0)

        product.refresh_from_db()
        self.assertTrue(product.cover)

    def test_dry_run_saves_nothing(self):
        product = ProductFactory(slug='ambra-1908')
        self.put(product.slug)

        call_command('fetch_product_photos', from_folder=str(self.root), dry_run=True, verbosity=0)

        self.assertEqual(ProductImage.objects.filter(product=product).count(), 0)

    def test_same_frame_is_not_used_twice(self):
        """Один знімок не може стояти у двох ароматів."""
        first = ProductFactory(slug='first-product')
        second = ProductFactory(slug='second-product')
        shared = synthetic_bottle()
        self.put(first.slug, shared)
        self.put(second.slug, shared)

        call_command('fetch_product_photos', from_folder=str(self.root), verbosity=0)

        with_photo = ProductImage.objects.exclude(source_url='').values_list(
            'product__slug', flat=True
        )
        self.assertEqual(len(set(with_photo)), 1, 'той самий кадр пішов у два товари')

    def test_limit_zero_does_nothing(self):
        product = ProductFactory(slug='limit-test')
        self.put(product.slug)

        call_command('fetch_product_photos', from_folder=str(self.root), limit=0, verbosity=0)

        self.assertEqual(ProductImage.objects.filter(product=product).count(), 0)

    def test_only_touches_one_product(self):
        target = ProductFactory(slug='target-product')
        other = ProductFactory(slug='other-product')
        self.put(target.slug)
        self.put(other.slug, synthetic_bottle().transpose(Image.FLIP_LEFT_RIGHT))

        call_command(
            'fetch_product_photos', from_folder=str(self.root), only=target.slug, verbosity=0
        )

        self.assertEqual(ProductImage.objects.filter(product=target).count(), 3)
        self.assertEqual(ProductImage.objects.filter(product=other).count(), 0)

    def test_rejected_hash_is_skipped(self):
        from shop import photo_rejects

        product = ProductFactory(slug='rejected-product')
        path = self.put(product.slug)
        value = _photos.dhash(Image.open(path))

        photo_rejects.REJECTED_HASHES[value] = 'тест'
        self.addCleanup(photo_rejects.REJECTED_HASHES.pop, value, None)

        call_command('fetch_product_photos', from_folder=str(self.root), verbosity=0)

        self.assertEqual(ProductImage.objects.filter(product=product).count(), 0)

    def test_missing_source_is_an_error(self):
        with self.assertRaises(CommandError):
            call_command('fetch_product_photos', verbosity=0)

    def test_unknown_slug_is_an_error(self):
        with self.assertRaises(CommandError):
            call_command(
                'fetch_product_photos',
                from_folder=str(self.root),
                only='nemaje-takoho',
                verbosity=0,
            )

    def test_renders_are_left_alone(self):
        """Товар без кандидатів зберігає рендер B5, а не лишається без фото."""
        product = ProductFactory(slug='no-candidates')
        ProductImage.objects.create(product=product, is_main=True, sort_order=0)
        self.put('kedrova-tysha')

        call_command('fetch_product_photos', from_folder=str(self.root), verbosity=0)

        self.assertEqual(ProductImage.objects.filter(product=product).count(), 1)
        self.assertEqual(ProductImage.objects.filter(product=product).first().source_url, '')


class PhotoSourcesPageTests(ShopTestCase):
    """Службова сторінка: у DEBUG відкрита, поза ним — 404."""

    @override_settings(DEBUG=True)
    def test_page_lists_sources(self):
        product = ProductFactory(name='Кедрова тиша')
        ProductImage.objects.create(
            product=product,
            is_main=True,
            source_url='https://example.com/bottle.jpg',
            source_query='vestige sandal eau de parfum bottle',
            source_hash='0123456789abcdef',
        )

        response = self.client.get(reverse('shop:photo_sources'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'https://example.com/bottle.jpg')
        self.assertContains(response, 'vestige sandal eau de parfum bottle')
        self.assertContains(response, 'Кедрова тиша')

    def test_page_is_hidden_without_debug(self):
        response = self.client.get(reverse('shop:photo_sources'))

        self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=True)
    def test_rendered_products_are_listed_explicitly(self):
        """Товари на рендері мають бути перелічені, а не губитись."""
        ProductFactory(name='Кава з кардамоном')

        response = self.client.get(reverse('shop:photo_sources'))

        self.assertContains(response, 'Лишились на рендері')
        self.assertContains(response, 'Кава з кардамоном')

    def test_reject_is_post_only(self):
        response = self.client.get(reverse('shop:photo_reject', args=[1]))

        self.assertIn(response.status_code, {404, 405})

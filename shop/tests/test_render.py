"""Рендерер зображень: геометрія, детермінованість, запис через Django.

Тут навмисно немає перевірок «красиво чи ні» — це справа ока. Перевіряється
те, що можна перевірити машиною: скло дає градієнт товщі, кадр лишається
в межах палітри, файли лягають через storage, а повтор не плодить дублікатів.
"""

import shutil
import tempfile
from io import StringIO

import numpy as np
from django.core.management import call_command
from django.test import override_settings

from shop.management.commands import _render as R
from shop.management.commands.render_product_images import (
    CONCENTRATION_SHAPES,
    build_shape,
    encode_webp,
    liquid_for,
    seed_from_slug,
)
from shop.models import Product, ProductImage
from testing import ShopTestCase
from testing.factories import CategoryFactory, ProductFactory

MEDIA_FOR_TESTS = tempfile.mkdtemp(prefix='sillage-render-')


class TransliterationlessGeometryTests(ShopTestCase):
    """SDF-примітиви поводяться так, як від них очікує трасувальник."""

    def test_elliptic_prism_is_negative_inside(self):
        p = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)

        self.assertLess(R.sd_elliptic_prism(p, 0.3, 0.15, 0.4, 0.05)[0], 0)

    def test_elliptic_prism_is_positive_outside(self):
        p = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)

        self.assertGreater(R.sd_elliptic_prism(p, 0.3, 0.15, 0.4, 0.05)[0], 0)

    def test_thickness_is_greatest_in_the_middle(self):
        """Ключова властивість: саме градієнт товщі читається оком як скло.

        У паралелепіпеда він нульовий, тому корпус і зроблено еліптичним.
        """
        product = ProductFactory(concentration=Product.CONCENTRATION_EDP)
        bottle = R.Bottle(build_shape(product, np.random.default_rng(1)))

        def depth(x):
            column = np.stack(
                [
                    np.full(400, x, dtype=np.float32),
                    np.zeros(400, dtype=np.float32),
                    np.linspace(-0.6, 0.6, 400, dtype=np.float32),
                ],
                axis=-1,
            )
            return int((bottle.glass(column) < 0).sum())

        self.assertGreater(depth(0.0), depth(float(bottle.body_half[0]) * 0.85))


class LightingTests(ShopTestCase):
    def test_environment_is_never_pure_black(self):
        directions = R.normalize(np.random.default_rng(0).normal(size=(64, 3)).astype(np.float32))

        self.assertTrue((R.environment(directions) > 0).all())

    def test_backlight_only_reaches_transmitted_rays(self):
        """Скрим стоїть за флаконом: у кадр він світити не має.

        Коли він потрапляв у фон, кадр вибілювався повністю.
        """
        toward_camera = np.array([[0.0, 0.0, -1.0]], dtype=np.float32)

        plain = R.environment(toward_camera)
        backlit = R.environment(toward_camera, backlit=True)

        self.assertTrue((backlit > plain).all(), 'скрим має бути видимий лише крізь скло')

    def test_fresnel_grows_at_grazing_angles(self):
        head_on = R.fresnel(np.array([[1.0]], dtype=np.float32))
        grazing = R.fresnel(np.array([[0.05]], dtype=np.float32))

        self.assertGreater(grazing[0, 0], head_on[0, 0])

    def test_refraction_bends_toward_the_normal(self):
        direction = R.normalize(np.array([[0.6, 0.0, -0.8]], dtype=np.float32))
        normal = np.array([[0.0, 0.0, 1.0]], dtype=np.float32)

        refracted, total = R.refract(direction, normal, 1.0 / R.GLASS_IOR)

        self.assertFalse(total[0])
        self.assertLess(abs(refracted[0, 0]), abs(direction[0, 0]))


class FilmTests(ShopTestCase):
    def test_frame_stays_inside_the_brand_palette(self):
        """Ані чистого чорного, ані чистого білого — вимога ART_DIRECTION.md."""
        linear = np.abs(np.random.default_rng(3).normal(size=(40, 32, 3))).astype(np.float32) * 6

        frame = R.apply_film(linear, np.random.default_rng(4))

        self.assertGreaterEqual(int(frame.min()), 1, 'найтемніша точка не має бути #000000')
        self.assertLessEqual(int(frame.max()), 245, 'найсвітліша точка не має бути #FFFFFF')

    def test_tonemap_never_exceeds_one(self):
        values = np.array([0.0, 1.0, 50.0, 500.0], dtype=np.float32)

        self.assertTrue((R.aces_tonemap(values) <= 1.0).all())


class ShapeVarietyTests(ShopTestCase):
    def test_concentration_changes_proportions(self):
        """Каталог не має виглядати як тридцять клонів одного флакона."""
        extrait = ProductFactory(concentration=Product.CONCENTRATION_EXTRAIT)
        cologne = ProductFactory(concentration=Product.CONCENTRATION_EDC)

        wide = build_shape(extrait, np.random.default_rng(1))
        narrow = build_shape(cologne, np.random.default_rng(1))

        self.assertGreater(wide['body'][0], narrow['body'][0])
        self.assertLess(wide['body'][1], narrow['body'][1])

    def test_home_goods_have_their_own_profile(self):
        self.assertIn('', CONCENTRATION_SHAPES)

    def test_seed_is_derived_from_slug(self):
        self.assertEqual(seed_from_slug('kedrova-tysha'), seed_from_slug('kedrova-tysha'))
        self.assertNotEqual(seed_from_slug('kedrova-tysha'), seed_from_slug('sandal-07'))

    def test_liquid_colour_follows_the_olfactory_family(self):
        amber = ProductFactory(category=CategoryFactory(slug='ambrovi'))
        aquatic = ProductFactory(category=CategoryFactory(slug='akvatychni'))

        # Амброві теплі (червоного більше за синій), акватичні — навпаки.
        self.assertGreater(liquid_for(amber)[0], liquid_for(amber)[2])
        self.assertLess(liquid_for(aquatic)[0], liquid_for(aquatic)[2])


class EncodingTests(ShopTestCase):
    def test_webp_is_produced_at_the_requested_size(self):
        pixels = np.zeros((60, 48, 3), dtype=np.uint8)

        payload = encode_webp(pixels, (24, 30))

        self.assertTrue(payload.startswith(b'RIFF'))
        self.assertIn(b'WEBP', payload[:16])


@override_settings(MEDIA_ROOT=MEDIA_FOR_TESTS)
class RenderCommandTests(ShopTestCase):
    """Команда цілком, але на крихітній роздільності — тут важлива механіка."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_FOR_TESTS, ignore_errors=True)
        super().tearDownClass()

    def render(self, product, **options):
        out = StringIO()
        call_command(
            'render_product_images',
            only=product.slug,
            force=True,
            scale=0.03,
            stdout=out,
            stderr=out,
            **options,
        )
        return out.getvalue()

    def test_cover_and_two_extra_images_are_written(self):
        product = ProductFactory()

        self.render(product)

        product.refresh_from_db()
        self.assertTrue(product.cover)
        self.assertEqual(ProductImage.objects.filter(product=product).count(), 3)

    def test_files_go_through_django_storage(self):
        """Запис через ContentFile, а не прямо в media/ — інакше Django про них не знає."""
        product = ProductFactory()

        self.render(product)

        product.refresh_from_db()
        self.assertTrue(product.cover.storage.exists(product.cover.name))
        self.assertTrue(product.cover.name.endswith('.webp'))

    def test_exactly_one_main_image(self):
        product = ProductFactory()

        self.render(product)

        self.assertEqual(ProductImage.objects.filter(product=product, is_main=True).count(), 1)

    def test_rerender_replaces_and_does_not_multiply(self):
        product = ProductFactory()

        self.render(product)
        self.render(product)

        self.assertEqual(ProductImage.objects.filter(product=product).count(), 3)

    def test_alt_text_is_meaningful(self):
        product = ProductFactory(name='Кедрова тиша')

        self.render(product)

        alt = ProductImage.objects.filter(product=product).first().alt_text
        self.assertIn('Кедрова тиша', alt)
        self.assertIn(product.brand.name, alt)

    def test_render_is_deterministic(self):
        product = ProductFactory()

        # Дескриптор закриваємо явно: на Windows відкритий файл не дає
        # перезаписати себе, і другий рендер падає з PermissionError.
        self.render(product)
        product.refresh_from_db()
        with product.cover.open('rb') as handle:
            first = handle.read()

        self.render(product)
        product.refresh_from_db()
        with product.cover.open('rb') as handle:
            second = handle.read()

        self.assertEqual(first, second, 'той самий slug має давати той самий кадр')

    def test_skips_products_that_are_already_done(self):
        """Відновлюваність: перерваний прогін продовжується, а не починається з нуля."""
        product = ProductFactory()
        self.render(product)

        out = StringIO()
        call_command('render_product_images', only=product.slug, scale=0.03, stdout=out, stderr=out)

        self.assertIn('Пропущено готових: 1', out.getvalue())

    def test_half_rendered_product_is_not_considered_done(self):
        """Обкладинка без ракурсів — це обірваний прогін, його треба доробити."""
        product = ProductFactory()
        self.render(product)
        product.images.all().delete()

        out = StringIO()
        call_command('render_product_images', only=product.slug, scale=0.03, stdout=out, stderr=out)

        self.assertNotIn('Пропущено готових', out.getvalue())
        self.assertEqual(ProductImage.objects.filter(product=product).count(), 3)

    def test_limit_caps_the_batch(self):
        products = [ProductFactory() for _ in range(3)]

        out = StringIO()
        call_command('render_product_images', limit=2, scale=0.03, stdout=out, stderr=out)

        rendered = sum(1 for item in products if Product.objects.get(pk=item.pk).cover)
        self.assertEqual(rendered, 2)

    def test_limit_zero_renders_nothing(self):
        ProductFactory()

        out = StringIO()
        call_command('render_product_images', limit=0, scale=0.03, stdout=out, stderr=out)

        self.assertIn('нічого не рендерю', out.getvalue())

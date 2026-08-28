"""Завантаження зображень через inline адмінки — і чи вони доходять до сайту.

Це та частина, яку найлегше «зробити на вигляд»: інлайн є, поля є, а файл
нікуди не лягає, бо загубився `enctype`, `MEDIA_ROOT` або `related_name`.
Тому тут ідемо справжнім POST-ом форми і потім перевіряємо сторінку товару.
"""

import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from shop.models import Product, ProductImage
from testing import ShopTestCase
from testing.factories import ProductFactory, UserFactory

MEDIA_FOR_TESTS = tempfile.mkdtemp(prefix='sillage-media-')


def make_image(name='flacon.webp', color=(22, 19, 27), size=(40, 50)):
    """Справжній файл зображення — Pillow перевіряє вміст, а не лише розширення."""
    buffer = io.BytesIO()
    Image.new('RGB', size, color).save(buffer, format='WEBP')
    buffer.seek(0)
    return SimpleUploadedFile(name, buffer.read(), content_type='image/webp')


@override_settings(MEDIA_ROOT=MEDIA_FOR_TESTS)
class ProductImageUploadTests(ShopTestCase):
    """Завантаження йде через ту саму форму, що й у живій адмінці."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_FOR_TESTS, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.staff = UserFactory(is_staff=True, is_superuser=True)
        self.client.force_login(self.staff)
        self.product = ProductFactory(name='Кедрова тиша')

    def _post_images(self, count=3, main_index=0):
        """POST форми товару з `count` зображень у інлайні."""
        data = {
            # Поля самого товару.
            'name': self.product.name,
            'slug': self.product.slug,
            'sku': self.product.sku,
            'brand': self.product.brand_id,
            'category': self.product.category_id,
            'short_description': '',
            'description': '',
            'concentration': self.product.concentration,
            'gender': self.product.gender,
            'volume_ml': self.product.volume_ml or '',
            'longevity_hours': '',
            'sillage': '',
            'perfumer': '',
            'year_released': '',
            'country': '',
            'price': self.product.price,
            'old_price': '',
            'stock': self.product.stock,
            'is_available': 'on',
            # Інлайн піраміди нот — порожній, але формсет має бути присутнім.
            'product_notes-TOTAL_FORMS': '0',
            'product_notes-INITIAL_FORMS': '0',
            'product_notes-MIN_NUM_FORMS': '0',
            'product_notes-MAX_NUM_FORMS': '1000',
            # Інлайн зображень.
            'images-TOTAL_FORMS': str(count),
            'images-INITIAL_FORMS': '0',
            'images-MIN_NUM_FORMS': '0',
            'images-MAX_NUM_FORMS': '1000',
        }

        for index in range(count):
            data[f'images-{index}-image'] = make_image(f'photo-{index}.webp')
            data[f'images-{index}-alt_text'] = ''
            data[f'images-{index}-sort_order'] = str(index)
            if index == main_index:
                data[f'images-{index}-is_main'] = 'on'

        return self.client.post(
            reverse('admin:shop_product_change', args=[self.product.pk]),
            data,
            follow=True,
        )

    def test_three_images_upload_through_the_inline(self):
        response = self._post_images(count=3)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProductImage.objects.filter(product=self.product).count(), 3)

    def test_files_land_in_media_products(self):
        self._post_images(count=1)

        image = ProductImage.objects.get(product=self.product)
        self.assertTrue(image.image.name.startswith('products/'))
        self.assertTrue(image.image.storage.exists(image.image.name))

    def test_alt_text_is_filled_from_product_name(self):
        """Порожній alt заповнюється назвою — інакше страждає доступність."""
        self._post_images(count=1)

        self.assertEqual(ProductImage.objects.get(product=self.product).alt_text, 'Кедрова тиша')

    def test_exactly_one_image_is_main(self):
        self._post_images(count=3, main_index=1)

        main = ProductImage.objects.filter(product=self.product, is_main=True)
        self.assertEqual(main.count(), 1)

    def test_uploaded_main_image_reaches_the_product_page(self):
        self._post_images(count=2)
        main = ProductImage.objects.get(product=self.product, is_main=True)

        response = self.client.get(self.product.get_absolute_url())

        self.assertContains(response, main.image.url)

    def test_main_image_is_used_by_the_admin_thumbnail(self):
        self._post_images(count=1)

        product = Product.objects.with_relations().get(pk=self.product.pk)

        self.assertIsNotNone(product.main_image)


@override_settings(MEDIA_ROOT=MEDIA_FOR_TESTS)
class MediaSettingsTests(ShopTestCase):
    """Дрібниці, без яких завантаження мовчки не працює."""

    def test_media_url_has_leading_slash(self):
        from django.conf import settings

        self.assertTrue(settings.MEDIA_URL.startswith('/'))

    def test_product_images_use_related_name_images(self):
        product = ProductFactory()

        self.assertTrue(hasattr(product, 'images'))

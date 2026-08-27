"""Дрібні борги з AUDIT.md, які видно користувачу або адміністратору."""

from django.apps import apps
from django.urls import reverse

from testing import ShopTestCase
from testing.factories import ProductFactory


class AppVerboseNameTests(ShopTestCase):
    """AUDIT #17: бічне меню адмінки було наполовину англійською."""

    def test_every_app_has_ukrainian_verbose_name(self):
        for label in ('accounts', 'shop', 'cart', 'orders', 'payments'):
            config = apps.get_app_config(label)
            with self.subTest(app=label):
                self.assertNotEqual(
                    config.verbose_name,
                    label.capitalize(),
                    f'AppConfig «{label}» лишився з дефолтною англійською назвою',
                )


class ImageAltTextTests(ShopTestCase):
    """AUDIT #20: поле alt_text існувало, а шаблони писали назву товару."""

    def _product_with_image(self, alt_text):
        product = ProductFactory()
        product.images.create(
            image='products/2026/01/01/test.webp',
            alt_text=alt_text,
            is_main=True,
        )
        return product

    def test_catalog_uses_alt_text(self):
        self._product_with_image('Флакон на чорному тлі')

        response = self.client.get(reverse('shop:product_list'))

        self.assertContains(response, 'Флакон на чорному тлі')

    def test_product_detail_uses_alt_text(self):
        product = self._product_with_image('Ковпачок крупним планом')

        response = self.client.get(product.get_absolute_url())

        self.assertContains(response, 'Ковпачок крупним планом')

    def test_falls_back_to_product_name_when_alt_is_empty(self):
        product = self._product_with_image('')

        response = self.client.get(product.get_absolute_url())

        self.assertContains(response, f'alt="{product.name}"')


class NoEmojiIconsTests(ShopTestCase):
    """AUDIT #22: емодзі рендеряться по-різному в різних ОС і не масштабуються."""

    def test_layout_has_no_emoji_icons(self):
        response = self.client.get(reverse('shop:product_list'))
        body = response.content.decode()

        for emoji in ('🛍️', '✅', '🔒'):
            with self.subTest(emoji=emoji):
                self.assertNotIn(emoji, body)

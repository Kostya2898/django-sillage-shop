"""Димові тести каталогу — заразом перевіряють, що каркас фабрик робочий."""

from django.urls import reverse

from testing import ShopTestCase
from testing.factories import CategoryFactory, ProductFactory


class CatalogTests(ShopTestCase):
    def test_product_list_opens(self):
        ProductFactory.create_batch(3)

        response = self.client.get(reverse('shop:product_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['products']), 3)

    def test_product_detail_opens(self):
        product = ProductFactory()

        response = self.client.get(product.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, product.name)

    def test_unavailable_product_is_hidden(self):
        product = ProductFactory(is_available=False)

        # assertLogs заразом ковтає очікуваний WARNING «Not Found» — щоб він
        # не засмічував вивід прогону.
        with self.assertLogs('django.request', level='WARNING'):
            response = self.client.get(product.get_absolute_url())

        self.assertEqual(response.status_code, 404)

    def test_category_filter_includes_subcategories(self):
        parent = CategoryFactory(name='Аромати', slug='aromaty')
        child = CategoryFactory(name='Деревні', slug='derevni', parent=parent)
        ProductFactory(category=child)
        ProductFactory()  # товар з іншої категорії — не має потрапити у вибірку

        response = self.client.get(parent.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['products']), 1)

    def test_search_matches_name(self):
        ProductFactory(name='Кедрова тиша')
        ProductFactory(name='Солоний камінь')

        response = self.client.get(reverse('shop:product_list'), {'q': 'Кедрова'})

        self.assertEqual(len(response.context['products']), 1)

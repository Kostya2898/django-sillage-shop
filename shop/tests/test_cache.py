"""Кеш каталогу: зміна даних мусить скидати його одразу, а не через TTL.

Кешований блок, який не скидається, — найпідступніша помилка кешування: у
тестах без кешу все правильно, а на сайті годину висить стара ціна. Тому
тут перевіряється саме інвалідація, а не лише те, що кеш «щось зберігає».
"""

import io

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from PIL import Image

from shop.cache import (
    BRANDS_KEY,
    CATALOG_CACHE_KEYS,
    HOME_FEATURED_KEY,
    invalidate_catalog_cache,
)
from shop.models import ProductImage
from shop.services import get_brands, get_facets, get_home_featured, get_navigation_tree
from testing import ShopTestCase
from testing.factories import BrandFactory, ProductFactory, ReviewFactory


class CatalogCacheTests(ShopTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.product = ProductFactory(name='Ірис Сірий', is_featured=True)

    def fill_cache(self):
        get_navigation_tree()
        get_facets()
        get_brands()
        get_home_featured()

    def cached_keys(self):
        return [key for key in CATALOG_CACHE_KEYS if cache.get(key) is not None]

    def test_second_read_does_not_touch_database(self):
        self.fill_cache()

        with self.assertNumQueries(0):
            self.fill_cache()

    def test_product_change_resets_cache_and_home_shows_new_name(self):
        self.assertEqual([p.name for p in get_home_featured()], ['Ірис Сірий'])
        self.fill_cache()
        self.assertEqual(len(self.cached_keys()), len(CATALOG_CACHE_KEYS))

        self.product.name = 'Ірис Попелястий'
        self.product.save()

        self.assertEqual(self.cached_keys(), [])
        self.assertEqual([p.name for p in get_home_featured()], ['Ірис Попелястий'])

    def test_deleted_product_leaves_home_immediately(self):
        get_home_featured()

        self.product.delete()

        self.assertIsNone(cache.get(HOME_FEATURED_KEY))
        self.assertEqual(get_home_featured(), [])

    def test_new_brand_appears_in_brand_list_without_waiting_for_ttl(self):
        get_brands()

        brand = BrandFactory(name='Новий дім')
        ProductFactory(brand=brand)

        self.assertIsNone(cache.get(BRANDS_KEY))
        self.assertIn('Новий дім', [b['name'] for b in get_brands()])

    def test_approved_review_resets_rating_on_home(self):
        """Рейтинг на картці головної — теж кешований."""
        get_home_featured()

        ReviewFactory(product=self.product, rating=4, is_approved=True)

        self.assertIsNone(cache.get(HOME_FEATURED_KEY))
        self.assertEqual(get_home_featured()[0].average_rating, 4)

    def test_new_product_photo_resets_home_cards(self):
        """Картки головної кешуються разом із головним фото.

        Без `ProductImage` серед моделей, що скидають кеш, нове фото
        з'являлося б на головній лише через чверть години.
        """
        get_home_featured()
        buffer = io.BytesIO()
        Image.new('RGB', (40, 50), (30, 30, 30)).save(buffer, format='WEBP')

        image = ProductImage(product=self.product, is_main=True)
        image.image.save('photo.webp', buffer, save=True)
        self.addCleanup(image.image.delete, False)

        self.assertIsNone(cache.get(HOME_FEATURED_KEY))

    def test_invalidate_catalog_cache_removes_every_key(self):
        self.fill_cache()

        invalidate_catalog_cache()

        self.assertEqual(self.cached_keys(), [])

    def test_home_page_renders_from_cache(self):
        """Головна з теплим кешем робить менше запитів, ніж із холодним."""
        url = reverse('shop:home')

        cold = self.count_queries(url)
        warm = self.count_queries(url)

        self.assertLess(warm, cold)

    def count_queries(self, url):
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.client.get(url).status_code, 200)
        return len(queries)

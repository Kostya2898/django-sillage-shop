"""Сид-команда: повнота каталогу, ідемпотентність, зачистка legacy-даних."""

from decimal import Decimal
from io import StringIO

from django.core.management import call_command

from orders.models import Order
from shop.models import Brand, Category, Note, Product, ProductNote, Review
from testing import ShopTestCase


def seed(**options):
    """Виклик команди з приглушеним виводом."""
    out = StringIO()
    call_command('seed_shop', stdout=out, stderr=out, **options)
    return out.getvalue()


class CatalogueContentTests(ShopTestCase):
    @classmethod
    def setUpTestData(cls):
        seed(flush=True)

    def test_thirty_products(self):
        self.assertEqual(Product.objects.count(), 30)

    def test_category_tree(self):
        self.assertEqual(Category.objects.count(), 16)
        self.assertEqual(Category.objects.filter(parent__isnull=True).count(), 3)
        self.assertEqual(Category.objects.filter(parent__isnull=False).count(), 13)

    def test_nine_brands(self):
        self.assertEqual(Brand.objects.count(), 9)

    def test_notes_have_families(self):
        self.assertGreaterEqual(Note.objects.count(), 40)
        self.assertFalse(Note.objects.filter(family='').exists())

    def test_every_product_has_real_texts(self):
        """Тексти справжні: жодних «Демонстраційний опис для товару…»."""
        for product in Product.objects.all():
            with self.subTest(product=product.slug):
                self.assertGreaterEqual(len(product.short_description), 40)
                self.assertGreaterEqual(len(product.description), 300)
                self.assertNotIn('Демонстраційний', product.description)

    def test_descriptions_have_several_paragraphs(self):
        for product in Product.objects.all():
            with self.subTest(product=product.slug):
                self.assertGreaterEqual(product.description.count('\n\n'), 2)

    def test_fragrances_have_a_note_pyramid(self):
        """У кожного аромату є всі три шари піраміди."""
        fragrances = Product.objects.filter(category__parent__slug='aromaty')
        self.assertEqual(fragrances.count(), 21)

        for product in fragrances:
            layers = set(
                ProductNote.objects.filter(product=product).values_list('layer', flat=True)
            )
            with self.subTest(product=product.slug):
                self.assertEqual(
                    layers, {ProductNote.LAYER_TOP, ProductNote.LAYER_HEART, ProductNote.LAYER_BASE}
                )

    def test_ui_states_are_covered(self):
        """Стани, потрібні фронтенду й адмінці, справді присутні."""
        self.assertEqual(Product.objects.filter(is_featured=True).count(), 6)
        self.assertEqual(Product.objects.filter(is_new=True).count(), 5)
        self.assertEqual(Product.objects.filter(old_price__isnull=False).count(), 4)
        self.assertEqual(Product.objects.filter(stock=0).count(), 3)
        self.assertEqual(Product.objects.filter(stock=2).count(), 2)

    def test_prices_are_within_the_declared_range(self):
        for product in Product.objects.all():
            with self.subTest(product=product.slug):
                self.assertGreaterEqual(product.price, Decimal('1200.00'))
                self.assertLessEqual(product.price, Decimal('9800.00'))

    def test_discounts_are_real_discounts(self):
        for product in Product.objects.filter(old_price__isnull=False):
            with self.subTest(product=product.slug):
                self.assertGreater(product.old_price, product.price)
                self.assertTrue(product.has_discount)

    def test_orders_and_reviews_exist(self):
        self.assertEqual(Order.objects.count(), 10)
        self.assertEqual(Review.objects.count(), 15)
        self.assertGreaterEqual(Order.objects.values('status').distinct().count(), 4)
        self.assertGreaterEqual(Review.objects.values('rating').distinct().count(), 3)

    def test_reviews_are_published(self):
        self.assertFalse(Review.objects.filter(is_approved=False).exists())


class MoneyIsDecimalTests(ShopTestCase):
    """Гроші ніколи не приїжджають рядком.

    Рядок у грошовому полі доходить до арифметики через float і дає копійчані
    розбіжності в підсумку замовлення — найгірший клас багів, бо тихий.
    """

    @classmethod
    def setUpTestData(cls):
        seed(flush=True, products=6, orders=0)

    def test_seed_data_uses_decimal(self):
        from shop.management.commands._products import PRODUCTS

        for item in PRODUCTS:
            with self.subTest(product=item['slug']):
                self.assertIsInstance(item['price'], Decimal)
                if item.get('old_price') is not None:
                    self.assertIsInstance(item['old_price'], Decimal)

    def test_discount_percent_works_without_the_string_guard(self):
        product = Product.objects.filter(old_price__isnull=False).first()
        if product is None:
            self.skipTest('серед перших шести товарів немає знижки')
        self.assertIsInstance(product.discount_percent, int)


class LegacyCleanupTests(ShopTestCase):
    """Бренд-заглушка з міграції B3 і legacy-товари мають зникнути."""

    def test_placeholder_brand_is_removed(self):
        placeholder = Brand.objects.create(name='Без бренду', slug='bez-brendu')
        category = Category.objects.create(name='Книги', slug='knyhy')
        Product.objects.create(
            name='Ноутбук Lenovo IdeaPad 3',
            slug='lenovo-ideapad-3',
            brand=placeholder,
            category=category,
            price=Decimal('21999.00'),
        )

        seed(flush=True)

        self.assertFalse(Brand.objects.filter(slug='bez-brendu').exists())
        self.assertFalse(Product.objects.filter(slug='lenovo-ideapad-3').exists())

    def test_no_legacy_products_in_the_catalogue(self):
        seed(flush=True)

        names = ' '.join(Product.objects.values_list('name', flat=True))
        for legacy in ('Ноутбук', 'Смартфон', 'Django для початківців', 'Чистий код'):
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, names)

    def test_brand_filter_has_no_placeholder(self):
        seed(flush=True)

        self.assertNotIn('Без бренду', list(Brand.objects.values_list('name', flat=True)))


class IdempotencyTests(ShopTestCase):
    """Повторний запуск без --flush нічого не дублює."""

    @classmethod
    def setUpTestData(cls):
        seed(flush=True)

    def test_second_run_keeps_the_same_counts(self):
        before = {
            'products': Product.objects.count(),
            'brands': Brand.objects.count(),
            'categories': Category.objects.count(),
            'notes': Note.objects.count(),
            'orders': Order.objects.count(),
            'reviews': Review.objects.count(),
        }

        seed()

        after = {
            'products': Product.objects.count(),
            'brands': Brand.objects.count(),
            'categories': Category.objects.count(),
            'notes': Note.objects.count(),
            'orders': Order.objects.count(),
            'reviews': Review.objects.count(),
        }
        self.assertEqual(before, after)

    def test_note_pyramid_is_not_duplicated(self):
        product = Product.objects.get(slug='kedrova-tysha')
        before = ProductNote.objects.filter(product=product).count()

        seed()

        self.assertEqual(ProductNote.objects.filter(product=product).count(), before)

    def test_slugs_stay_stable(self):
        before = sorted(Product.objects.values_list('slug', flat=True))

        seed()

        self.assertEqual(sorted(Product.objects.values_list('slug', flat=True)), before)


class PartialSeedTests(ShopTestCase):
    def test_products_limit_is_respected(self):
        seed(flush=True, products=5, orders=0)

        self.assertEqual(Product.objects.count(), 5)

    def test_orders_can_be_skipped(self):
        seed(flush=True, products=5, orders=0)

        self.assertEqual(Order.objects.count(), 0)


class FixtureTests(ShopTestCase):
    """Фікстура має піднімати каталог без жодного файлу в media/."""

    def test_fixture_loads_into_an_empty_database(self):
        call_command('loaddata', 'catalog.json', verbosity=0)

        self.assertEqual(Product.objects.count(), 30)
        self.assertEqual(Brand.objects.count(), 9)
        self.assertEqual(Category.objects.count(), 16)

    def test_fixture_carries_no_media_paths(self):
        call_command('loaddata', 'catalog.json', verbosity=0)

        self.assertFalse(Product.objects.exclude(cover='').exists())

    def test_fixture_keeps_the_note_pyramid(self):
        call_command('loaddata', 'catalog.json', verbosity=0)

        product = Product.objects.get(slug='kedrova-tysha')
        self.assertTrue(product.top_notes)
        self.assertTrue(product.heart_notes)
        self.assertTrue(product.base_notes)

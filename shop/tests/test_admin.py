"""Адмінка каталогу: щільність списку, фільтри, масові дії, експорт.

Адмінка — це той екран, який реально показують на захисті, і водночас
найлегше місце вбити базу зайвими запитами: кожен рядок списку може
непомітно потягнути бренд, категорію і фото окремими SELECT-ами.
"""

import codecs
import csv
import io

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from shop.admin import CategoryAdmin, PriceRangeFilter, ProductAdmin, ReviewAdmin, StockStateFilter
from shop.models import Category, Note, Product, ProductNote, Review
from testing import ShopTestCase
from testing.factories import (
    BrandFactory,
    CategoryFactory,
    NoteFactory,
    ProductFactory,
    ReviewFactory,
    UserFactory,
)

# Стеля з критеріїв приймання: список 50 товарів має вкластися в 15 запитів.
QUERY_BUDGET = 15


class AdminTestCase(ShopTestCase):
    """Спільне: залогінений staff і фабрика запитів для викликів дій."""

    def setUp(self):
        self.staff = UserFactory(is_staff=True, is_superuser=True)
        self.client.force_login(self.staff)

    def make_request(self, path='/admin/'):
        request = RequestFactory().post(path)
        request.user = self.staff
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        return request


class ProductListDensityTests(AdminTestCase):
    """Головний критерій: список із 50 товарів не має розвалювати базу."""

    def test_fifty_products_stay_under_fifteen_queries(self):
        brand = BrandFactory()
        category = CategoryFactory()
        for _ in range(50):
            ProductFactory(brand=brand, category=category)

        url = reverse('admin:shop_product_changelist')

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertLess(
            len(captured),
            QUERY_BUDGET,
            f'Список 50 товарів зробив {len(captured)} запитів при бюджеті {QUERY_BUDGET}',
        )

    def test_queryset_preloads_brand_and_category(self):
        ProductFactory()
        admin_instance = ProductAdmin(Product, AdminSite())

        queryset = admin_instance.get_queryset(self.make_request())
        product = queryset.first()

        with self.assertNumQueries(0):
            _ = product.brand.name
            _ = product.category.name


class ProductListColumnsTests(AdminTestCase):
    def test_discount_badge_shows_percent(self):
        product = ProductFactory(price=4900, old_price=6200)
        admin_instance = ProductAdmin(Product, AdminSite())

        badge = admin_instance.discount_badge(product)

        self.assertIn('6200', badge)
        # discount_percent округлює донизу: 1300/6200 = 20.96%.
        self.assertIn('−20%', badge)

    def test_discount_badge_is_empty_without_old_price(self):
        admin_instance = ProductAdmin(Product, AdminSite())

        self.assertIn('—', admin_instance.discount_badge(ProductFactory(old_price=None)))

    def test_stock_state_marks_empty_stock(self):
        admin_instance = ProductAdmin(Product, AdminSite())

        self.assertIn('немає', admin_instance.stock_state(ProductFactory(stock=0)))

    def test_stock_state_marks_low_stock(self):
        admin_instance = ProductAdmin(Product, AdminSite())

        self.assertIn('закінчується', admin_instance.stock_state(ProductFactory(stock=3)))

    def test_stock_state_is_calm_when_enough(self):
        admin_instance = ProductAdmin(Product, AdminSite())

        self.assertIn('достатньо', admin_instance.stock_state(ProductFactory(stock=40)))

    def test_thumbnail_falls_back_to_dash(self):
        admin_instance = ProductAdmin(Product, AdminSite())

        self.assertIn('—', admin_instance.thumbnail(ProductFactory()))


class CustomFiltersTests(AdminTestCase):
    def test_price_range_filter_splits_the_catalogue(self):
        ProductFactory(price=1400)
        ProductFactory(price=3100)
        ProductFactory(price=5400)
        ProductFactory(price=8600)

        url = reverse('admin:shop_product_changelist')
        counts = {}
        for key in PriceRangeFilter.RANGES:
            response = self.client.get(url, {'price_range': key})
            counts[key] = response.context['cl'].result_count

        self.assertEqual(counts, {'budget': 1, 'mid': 1, 'high': 1, 'lux': 1})

    def test_stock_filter_finds_what_is_running_out(self):
        ProductFactory(stock=0)
        ProductFactory(stock=3)
        ProductFactory(stock=40)

        url = reverse('admin:shop_product_changelist')

        self.assertEqual(self.client.get(url, {'stock_state': 'out'}).context['cl'].result_count, 1)
        self.assertEqual(self.client.get(url, {'stock_state': 'low'}).context['cl'].result_count, 1)
        self.assertEqual(
            self.client.get(url, {'stock_state': 'in_stock'}).context['cl'].result_count, 2
        )

    def test_low_stock_threshold_is_shared_with_the_column(self):
        self.assertEqual(StockStateFilter.LOW_STOCK_THRESHOLD, 5)


class ProductSearchTests(AdminTestCase):
    def test_search_by_sku(self):
        product = ProductFactory()

        response = self.client.get(reverse('admin:shop_product_changelist'), {'q': product.sku})

        self.assertEqual(response.context['cl'].result_count, 1)

    def test_search_by_brand_name(self):
        brand = BrandFactory(name='Atelier Noir')
        ProductFactory(brand=brand)
        ProductFactory()

        response = self.client.get(reverse('admin:shop_product_changelist'), {'q': 'Atelier'})

        self.assertEqual(response.context['cl'].result_count, 1)

    def test_search_by_note_does_not_duplicate_rows(self):
        """Два збіги по M2M дали б той самий товар двічі без distinct."""
        product = ProductFactory()
        for name in ('Ветивер гаїтянський', 'Ветивер димчастий'):
            note = NoteFactory(name=name, family=Note.FAMILY_WOODY)
            ProductNote.objects.create(product=product, note=note, layer=ProductNote.LAYER_HEART)

        response = self.client.get(reverse('admin:shop_product_changelist'), {'q': 'Ветивер'})

        self.assertEqual(response.context['cl'].result_count, 1)


class AutocompleteTests(AdminTestCase):
    """Autocomplete у формі товару тягне бренди й ноти окремим endpoint-ом."""

    def _autocomplete(self, model, field):
        return self.client.get(
            reverse('admin:autocomplete'),
            {
                'app_label': 'shop',
                'model_name': 'product',
                'field_name': field,
                'term': model,
            },
        )

    def test_brand_autocomplete_returns_results(self):
        BrandFactory(name='Maison Ferrant')

        response = self._autocomplete('Maison', 'brand')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['results']), 1)

    def test_category_autocomplete_returns_results(self):
        CategoryFactory(name='Деревні')

        response = self._autocomplete('Деревні', 'category')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['results']), 1)

    def test_note_autocomplete_serves_the_pyramid_inline(self):
        NoteFactory(name='Бергамот', family=Note.FAMILY_CITRUS)

        response = self.client.get(
            reverse('admin:autocomplete'),
            {
                'app_label': 'shop',
                'model_name': 'productnote',
                'field_name': 'note',
                'term': 'Бергамот',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['results']), 1)


class BulkActionsTests(AdminTestCase):
    def _run(self, action, products):
        admin_instance = ProductAdmin(Product, AdminSite())
        queryset = Product.objects.filter(pk__in=[p.pk for p in products])
        return getattr(admin_instance, action)(self.make_request(), queryset)

    def test_make_featured(self):
        products = [ProductFactory(is_featured=False) for _ in range(3)]

        self._run('make_featured', products)

        self.assertEqual(Product.objects.filter(is_featured=True).count(), 3)

    def test_unmake_featured(self):
        products = [ProductFactory(is_featured=True) for _ in range(2)]

        self._run('unmake_featured', products)

        self.assertEqual(Product.objects.filter(is_featured=True).count(), 0)

    def test_mark_as_new(self):
        products = [ProductFactory(is_new=False) for _ in range(2)]

        self._run('mark_as_new', products)

        self.assertEqual(Product.objects.filter(is_new=True).count(), 2)

    def test_withdraw_from_sale(self):
        products = [ProductFactory(is_available=True) for _ in range(2)]

        self._run('withdraw_from_sale', products)

        self.assertEqual(Product.objects.filter(is_available=False).count(), 2)

    def test_action_reports_how_many_were_touched(self):
        products = [ProductFactory(is_featured=False), ProductFactory(is_featured=True)]
        admin_instance = ProductAdmin(Product, AdminSite())
        request = self.make_request()

        admin_instance.make_featured(
            request, Product.objects.filter(pk__in=[p.pk for p in products])
        )

        texts = [str(message) for message in request._messages]
        self.assertIn('Оновлено товарів: 1', texts)


class CsvExportTests(AdminTestCase):
    def _export(self, products):
        admin_instance = ProductAdmin(Product, AdminSite())
        queryset = Product.objects.filter(pk__in=[p.pk for p in products])
        return admin_instance.export_csv(self.make_request(), queryset)

    def test_response_is_a_csv_attachment(self):
        response = self._export([ProductFactory()])

        self.assertIn('text/csv', response['Content-Type'])
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('.csv', response['Content-Disposition'])

    def test_starts_with_bom_so_excel_reads_cyrillic(self):
        response = self._export([ProductFactory()])

        self.assertTrue(
            response.content.startswith(codecs.BOM_UTF8),
            'Без BOM Excel показує кирилицю кракозябрами',
        )

    def test_cyrillic_survives_the_round_trip(self):
        brand = BrandFactory(name='Ambre Rouge')
        product = ProductFactory(name='Амброве серце', brand=brand, price=6200)

        response = self._export([product])
        body = response.content.decode('utf-8-sig')
        rows = list(csv.reader(io.StringIO(body), delimiter=';'))

        self.assertEqual(rows[0][0], 'Артикул')
        self.assertIn('Амброве серце', rows[1])
        self.assertIn('Ambre Rouge', rows[1])

    def test_export_covers_every_selected_product(self):
        products = [ProductFactory() for _ in range(3)]

        body = self._export(products).content.decode('utf-8-sig')
        rows = list(csv.reader(io.StringIO(body), delimiter=';'))

        # Заголовок плюс три товари; порожній хвіст від writer ігноруємо.
        self.assertEqual(len([row for row in rows if row]), 4)


class CategoryAdminTests(AdminTestCase):
    def test_tree_shows_nesting(self):
        parent = CategoryFactory(name='Аромати')
        child = CategoryFactory(name='Деревні', parent=parent)
        admin_instance = CategoryAdmin(Category, AdminSite())

        self.assertIn('<strong>Аромати</strong>', admin_instance.tree_name(parent))
        self.assertIn('└─', admin_instance.tree_name(child))

    def test_product_counter_comes_from_annotate(self):
        category = CategoryFactory()
        ProductFactory(category=category)
        ProductFactory(category=category)
        admin_instance = CategoryAdmin(Category, AdminSite())

        row = admin_instance.get_queryset(self.make_request()).get(pk=category.pk)

        with self.assertNumQueries(0):
            self.assertEqual(admin_instance.products_total(row), 2)

    def test_deactivating_a_branch_takes_children_with_it(self):
        parent = CategoryFactory(name='Дім')
        child = CategoryFactory(name='Свічки', parent=parent)
        admin_instance = CategoryAdmin(Category, AdminSite())

        admin_instance.deactivate_branch(self.make_request(), Category.objects.filter(pk=parent.pk))

        parent.refresh_from_db()
        child.refresh_from_db()
        self.assertFalse(parent.is_active)
        self.assertFalse(child.is_active, 'Підкатегорія мала вимкнутись разом із гілкою')

    def test_activating_a_branch_brings_children_back(self):
        parent = CategoryFactory(is_active=False)
        child = CategoryFactory(parent=parent, is_active=False)
        admin_instance = CategoryAdmin(Category, AdminSite())

        admin_instance.deactivate_branch(self.make_request(), Category.objects.filter(pk=parent.pk))
        admin_instance.activate_branch(self.make_request(), Category.objects.filter(pk=parent.pk))

        parent.refresh_from_db()
        child.refresh_from_db()
        self.assertTrue(parent.is_active)
        self.assertTrue(child.is_active)


class ReviewModerationTests(AdminTestCase):
    def test_approve_publishes_the_review(self):
        review = ReviewFactory(is_approved=False)
        admin_instance = ReviewAdmin(Review, AdminSite())

        admin_instance.approve(self.make_request(), Review.objects.filter(pk=review.pk))

        review.refresh_from_db()
        self.assertTrue(review.is_approved)

    def test_reject_hides_the_review(self):
        review = ReviewFactory(is_approved=True)
        admin_instance = ReviewAdmin(Review, AdminSite())

        admin_instance.reject(self.make_request(), Review.objects.filter(pk=review.pk))

        review.refresh_from_db()
        self.assertFalse(review.is_approved)

    def test_author_and_product_are_locked_after_creation(self):
        review = ReviewFactory()
        admin_instance = ReviewAdmin(Review, AdminSite())

        readonly = admin_instance.get_readonly_fields(self.make_request(), obj=review)

        self.assertIn('user', readonly)
        self.assertIn('product', readonly)

    def test_author_and_product_are_editable_on_creation(self):
        admin_instance = ReviewAdmin(Review, AdminSite())

        readonly = admin_instance.get_readonly_fields(self.make_request(), obj=None)

        self.assertNotIn('user', readonly)

    def test_excerpt_is_trimmed(self):
        review = ReviewFactory(text='я' * 200)
        admin_instance = ReviewAdmin(Review, AdminSite())

        self.assertLessEqual(len(admin_instance.excerpt(review)), 81)


class ModerationReachesTheSiteTests(ShopTestCase):
    """Схвалений відгук має зʼявитись на сторінці товару, несхвалений — ні."""

    def test_unapproved_review_is_hidden(self):
        review = ReviewFactory(is_approved=False, text='Поки що на модерації')

        response = self.client.get(review.product.get_absolute_url())

        self.assertNotContains(response, 'Поки що на модерації')

    def test_approved_review_is_visible(self):
        review = ReviewFactory(is_approved=True, text='Пахне як бібліотека')

        response = self.client.get(review.product.get_absolute_url())

        self.assertContains(response, 'Пахне як бібліотека')

    def test_moderation_makes_the_review_appear(self):
        review = ReviewFactory(is_approved=False, text='Чекає на схвалення')
        url = review.product.get_absolute_url()
        self.assertNotContains(self.client.get(url), 'Чекає на схвалення')

        staff = UserFactory(is_staff=True, is_superuser=True)
        request = RequestFactory().post('/admin/')
        request.user = staff
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        ReviewAdmin(Review, AdminSite()).approve(request, Review.objects.filter(pk=review.pk))

        self.assertContains(self.client.get(url), 'Чекає на схвалення')

    def test_rating_summary_is_shown(self):
        product = ProductFactory()
        ReviewFactory(product=product, rating=5, is_approved=True)
        ReviewFactory(product=product, rating=3, is_approved=True)

        response = self.client.get(product.get_absolute_url())

        # Саме значення перевіряємо в контексті: у шаблоні українська локаль
        # покаже «4,0» через кому, і прив'язуватись до цього не варто.
        self.assertEqual(response.context['product'].average_rating, 4.0)
        self.assertEqual(response.context['product'].reviews_count, 2)
        self.assertContains(response, 'Відгуки')


class AdminBrandingTests(AdminTestCase):
    def test_panel_is_branded(self):
        response = self.client.get(reverse('admin:index'))

        self.assertContains(response, 'SILLAGE')
        self.assertContains(response, 'панель керування')


class AdminPagesOpenTests(AdminTestCase):
    """Кожен список і форма мають відкриватись — тут ловляться описки в admin.py."""

    def test_changelists_open(self):
        BrandFactory()
        NoteFactory()
        ProductFactory()
        ReviewFactory()

        for model in ('brand', 'category', 'note', 'product', 'review'):
            with self.subTest(model=model):
                url = reverse(f'admin:shop_{model}_changelist')
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_product_change_form_opens_with_inlines(self):
        product = ProductFactory()

        response = self.client.get(reverse('admin:shop_product_change', args=[product.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ольфакторика')
        self.assertContains(response, 'Службове')

    def test_add_form_opens(self):
        for model in ('brand', 'category', 'note', 'product'):
            with self.subTest(model=model):
                url = reverse(f'admin:shop_{model}_add')
                self.assertEqual(self.client.get(url).status_code, 200)

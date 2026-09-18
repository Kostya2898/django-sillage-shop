"""Каталог: головна, фільтри, сортування, пошук, пагінація, бюджет запитів."""

import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from cart.services import NBSP
from shop.models import Note, Product, ProductNote
from shop.services import SORT_OPTIONS, build_facets, get_facets
from shop.templatetags.catalogue import money, money_amount
from testing import ShopTestCase
from testing.factories import (
    BrandFactory,
    CategoryFactory,
    NoteFactory,
    ProductFactory,
    ProductNoteFactory,
)

# Стеля з вимоги: сторінка каталогу має вкладатись у пʼять SQL-запитів.
QUERY_BUDGET = 5


class CatalogueTestCase(ShopTestCase):
    """Кеш фасетів між тестами треба скидати — інакше вони течуть один в одного."""

    def setUp(self):
        cache.clear()

    def catalogue(self, **params):
        return self.client.get(reverse('shop:product_list'), params)


class HomePageTests(CatalogueTestCase):
    def test_home_opens(self):
        response = self.client.get(reverse('shop:home'))

        self.assertEqual(response.status_code, 200)

    def test_home_shows_featured(self):
        ProductFactory(name='Кураторський', is_featured=True)
        ProductFactory(name='Звичайний', is_featured=False)

        response = self.client.get(reverse('shop:home'))

        self.assertContains(response, 'Кураторський')
        self.assertNotContains(response, 'Звичайний')

    def test_home_shows_new_arrivals(self):
        ProductFactory(name='Свіжий аромат', is_new=True)

        self.assertContains(self.client.get(reverse('shop:home')), 'Свіжий аромат')

    def test_home_lists_root_categories(self):
        root = CategoryFactory(name='Аромати')
        CategoryFactory(name='Деревні', parent=root)

        response = self.client.get(reverse('shop:home'))

        self.assertContains(response, 'Аромати')
        self.assertContains(response, 'Деревні')

    def test_catalogue_moved_off_the_root_url(self):
        """Головна і каталог — різні сторінки, і це навмисно."""
        self.assertEqual(reverse('shop:home'), '/')
        self.assertEqual(reverse('shop:product_list'), '/catalogue/')


class FilterTests(CatalogueTestCase):
    def setUp(self):
        super().setUp()
        self.woody = CategoryFactory(name='Деревні', slug='derevni')
        self.floral = CategoryFactory(name='Квіткові', slug='kvitkovi')
        self.noir = BrandFactory(name='Atelier Noir', slug='atelier-noir')
        self.lume = BrandFactory(name='Casa Lume', slug='casa-lume')

        self.cedar = ProductFactory(
            name='Кедрова тиша',
            category=self.woody,
            brand=self.noir,
            price=Decimal('4200.00'),
            concentration=Product.CONCENTRATION_EDP,
            gender=Product.GENDER_UNISEX,
            stock=10,
        )
        self.rose = ProductFactory(
            name='Троянда о шостій',
            category=self.floral,
            brand=self.lume,
            price=Decimal('1500.00'),
            concentration=Product.CONCENTRATION_EDT,
            gender=Product.GENDER_FEMININE,
            stock=0,
        )

    def test_filter_by_brand(self):
        response = self.catalogue(brand='atelier-noir')

        self.assertEqual(response.context['total'], 1)
        self.assertContains(response, 'Кедрова тиша')

    def test_filter_by_several_brands(self):
        response = self.catalogue(brand=['atelier-noir', 'casa-lume'])

        self.assertEqual(response.context['total'], 2)

    def test_filter_by_concentration(self):
        self.assertEqual(self.catalogue(concentration='edp').context['total'], 1)

    def test_filter_by_gender(self):
        self.assertEqual(self.catalogue(gender='feminine').context['total'], 1)

    def test_filter_by_price_range(self):
        self.assertEqual(self.catalogue(price_min='2000').context['total'], 1)
        self.assertEqual(self.catalogue(price_max='2000').context['total'], 1)

    def test_reversed_price_range_is_swapped_not_empty(self):
        """Переплутані межі — помилка користувача, а не привід показати нуль."""
        response = self.catalogue(price_min='9000', price_max='1000')

        self.assertEqual(response.context['total'], 2)

    def test_garbage_price_is_ignored(self):
        self.assertEqual(self.catalogue(price_min='отака').context['total'], 2)

    def test_filter_in_stock_only(self):
        self.assertEqual(self.catalogue(in_stock='1').context['total'], 1)

    def test_filter_by_note(self):
        note = NoteFactory(name='Ветивер', slug='vetyver', family=Note.FAMILY_WOODY)
        ProductNoteFactory(product=self.cedar, note=note, layer=ProductNote.LAYER_HEART)

        self.assertEqual(self.catalogue(note='vetyver').context['total'], 1)

    def test_note_filter_does_not_duplicate_products(self):
        """Дві збіжні ноти не мають подвоїти товар у сітці."""
        for name in ('Ветивер гаїтянський', 'Ветивер димчастий'):
            note = NoteFactory(name=name, family=Note.FAMILY_WOODY)
            ProductNoteFactory(product=self.cedar, note=note, layer=ProductNote.LAYER_BASE)

        response = self.catalogue(note=[n.slug for n in Note.objects.all()])

        self.assertEqual(response.context['total'], 1)

    def test_category_filter_covers_the_whole_branch(self):
        root = CategoryFactory(name='Аромати', slug='aromaty')
        self.woody.parent = root
        self.woody.save()

        response = self.client.get(reverse('shop:product_list_by_category', args=['aromaty']))

        self.assertEqual(response.context['total'], 1)

    def test_combined_filters_narrow_together(self):
        response = self.catalogue(brand='atelier-noir', concentration='edp', in_stock='1')

        self.assertEqual(response.context['total'], 1)

    def test_reset_link_appears_only_when_filtered(self):
        self.assertFalse(self.catalogue().context['catalogue'].is_filtered)
        self.assertTrue(self.catalogue(brand='atelier-noir').context['catalogue'].is_filtered)

    def test_active_count_reflects_chosen_filters(self):
        response = self.catalogue(brand='atelier-noir', gender='unisex', in_stock='1')

        self.assertEqual(response.context['catalogue'].active_count, 3)


class SearchTests(CatalogueTestCase):
    def setUp(self):
        super().setUp()
        self.brand = BrandFactory(name='Nord Botanica')
        self.product = ProductFactory(
            name='Солоний камінь', brand=self.brand, short_description='Мокрий камінь у припливі'
        )
        ProductFactory(name='Тепла кімната')

    def test_search_by_name(self):
        self.assertEqual(self.catalogue(q='Солоний').context['total'], 1)

    def test_search_by_brand(self):
        self.assertEqual(self.catalogue(q='Botanica').context['total'], 1)

    def test_search_by_note(self):
        note = NoteFactory(name='Морська сіль', family=Note.FAMILY_AQUATIC)
        ProductNoteFactory(product=self.product, note=note, layer=ProductNote.LAYER_TOP)

        self.assertEqual(self.catalogue(q='Морська').context['total'], 1)

    def test_search_by_short_description(self):
        self.assertEqual(self.catalogue(q='припливі').context['total'], 1)

    def test_empty_result_is_not_a_dead_end(self):
        """Порожній екран — антипатерн: показуємо, що робити далі."""
        response = self.catalogue(q='чогонемає')

        self.assertEqual(response.context['total'], 0)
        self.assertContains(response, 'Скинути всі фільтри')

    def test_empty_result_suggests_featured(self):
        ProductFactory(name='Рятівний вибір', is_featured=True)

        response = self.catalogue(q='чогонемає')

        self.assertContains(response, 'Рятівний вибір')


class LiveSearchTests(CatalogueTestCase):
    def setUp(self):
        super().setUp()
        ProductFactory(name='Кедрова тиша')
        ProductFactory(name='Кава з кардамоном')

    def suggest(self, term):
        return self.client.get(reverse('shop:product_search'), {'q': term})

    def test_returns_json(self):
        response = self.suggest('Кедрова')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_finds_by_prefix(self):
        payload = self.suggest('Кедр').json()

        self.assertEqual(payload['count'], 1)
        self.assertEqual(payload['results'][0]['name'], 'Кедрова тиша')

    def test_result_carries_what_the_dropdown_needs(self):
        item = self.suggest('Кедр').json()['results'][0]

        for key in ('name', 'brand', 'price', 'url', 'image'):
            self.assertIn(key, item)

    def test_short_term_returns_nothing(self):
        """Один символ — це ще не запит: інакше вантажимо базу на кожну літеру."""
        self.assertEqual(self.suggest('К').json()['count'], 0)

    def test_unknown_term_returns_empty_list(self):
        payload = self.suggest('чогонемає').json()

        self.assertEqual(payload['count'], 0)
        self.assertEqual(payload['results'], [])


class SortTests(CatalogueTestCase):
    def setUp(self):
        super().setUp()
        self.cheap = ProductFactory(name='Дешевий', price=Decimal('1200.00'), sold_count=1)
        self.dear = ProductFactory(name='Дорогий', price=Decimal('8600.00'), sold_count=90)

    def names(self, **params):
        return [p.name for p in self.catalogue(**params).context['products']]

    def test_sort_by_price_ascending(self):
        self.assertEqual(self.names(sort='price')[0], 'Дешевий')

    def test_sort_by_price_descending(self):
        self.assertEqual(self.names(sort='-price')[0], 'Дорогий')

    def test_sort_by_popularity(self):
        self.assertEqual(self.names(sort='popular')[0], 'Дорогий')

    def test_unknown_sort_falls_back_to_default(self):
        response = self.catalogue(sort='; DROP TABLE')

        self.assertEqual(response.context['state']['sort'], 'featured')

    def test_every_sort_option_works(self):
        for key in SORT_OPTIONS:
            with self.subTest(sort=key):
                self.assertEqual(self.catalogue(sort=key).status_code, 200)


class PaginationTests(CatalogueTestCase):
    def setUp(self):
        super().setUp()
        self.brand = BrandFactory(slug='atelier-noir')
        for index in range(20):
            ProductFactory(name=f'Аромат {index:02d}', brand=self.brand)

    def test_pagination_splits_results(self):
        first = self.catalogue()
        self.assertEqual(len(first.context['products']), 12)
        self.assertTrue(first.context['page'].has_next())

    def test_second_page_has_the_rest(self):
        self.assertEqual(len(self.catalogue(page=2).context['products']), 8)

    def test_pagination_keeps_filters(self):
        """Перехід на другу сторінку не має скидати вибраний бренд."""
        response = self.catalogue(brand='atelier-noir', sort='price', page=2)
        html = response.content.decode()

        self.assertEqual(response.context['total'], 20)
        self.assertIn('brand=atelier-noir', html)
        self.assertIn('sort=price', html)

    def test_out_of_range_page_falls_back(self):
        self.assertEqual(self.catalogue(page=999).status_code, 200)


class JsonFragmentTests(CatalogueTestCase):
    def test_format_json_returns_only_the_grid(self):
        ProductFactory(name='Кедрова тиша')

        response = self.catalogue(format='json')
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('catalogue-grid', html)
        self.assertIn('Кедрова тиша', html)
        # Фрагмент — саме фрагмент: без шапки, підвалу і <html>.
        self.assertNotIn('<html', html)
        self.assertNotIn('site-search-input', html)


class FacetTests(CatalogueTestCase):
    def test_facets_count_only_available_products(self):
        brand = BrandFactory(name='Vestige', slug='vestige')
        ProductFactory(brand=brand, is_available=True)
        ProductFactory(brand=brand, is_available=False)

        facets = build_facets()
        entry = next(b for b in facets['brands'] if b['slug'] == 'vestige')

        self.assertEqual(entry['product_count'], 1)

    def test_brands_without_products_are_hidden(self):
        BrandFactory(name='Порожній', slug='porozhniy')

        self.assertNotIn('porozhniy', [b['slug'] for b in build_facets()['brands']])

    def test_inactive_subcategories_are_hidden(self):
        """Вимкнена підкатегорія не має висіти в меню й вести на 404."""
        root = CategoryFactory(name='Аромати', slug='aromaty')
        CategoryFactory(name='Прихована', slug='prykhovana', parent=root, is_active=False)

        tree = build_facets()['categories']
        children = next(c for c in tree if c['slug'] == 'aromaty')['children']

        self.assertEqual(children, [])

    def test_facets_are_cached(self):
        get_facets()

        with self.assertNumQueries(0):
            get_facets()

    def test_saving_a_product_resets_the_cache(self):
        """Лічильники у фасетах застарівають від будь-якої зміни каталогу."""
        get_facets()
        brand = BrandFactory(name='Новий', slug='novyi')
        ProductFactory(brand=brand)

        self.assertIn('novyi', [b['slug'] for b in get_facets()['brands']])


class QueryBudgetTests(CatalogueTestCase):
    """Головний критерій оптимізації: каталог не має розвалювати базу."""

    def setUp(self):
        super().setUp()
        brand = BrandFactory()
        category = CategoryFactory()
        for index in range(30):
            ProductFactory(name=f'Аромат {index:02d}', brand=brand, category=category)
        # Кеш фасетів прогріваємо окремо: бюджет міряємо для звичайного
        # відвідувача, який приходить на вже теплий кеш.
        get_facets()

    def test_catalogue_fits_the_budget(self):
        with CaptureQueriesContext(connection) as captured:
            response = self.catalogue()

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(captured),
            QUERY_BUDGET,
            f'Каталог зробив {len(captured)} запитів при бюджеті {QUERY_BUDGET}',
        )

    def test_filtered_catalogue_fits_the_budget(self):
        with CaptureQueriesContext(connection) as captured:
            self.catalogue(sort='price', in_stock='1')

        self.assertLessEqual(len(captured), QUERY_BUDGET)

    def test_no_n_plus_one_on_brand_and_category(self):
        response = self.catalogue()

        with self.assertNumQueries(0):
            for product in response.context['products']:
                _ = product.brand.name
                _ = product.category.name


class ProductDetailTests(CatalogueTestCase):
    def test_similar_products_share_notes(self):
        """«Схожі за нотами», а не «схожі за категорією» — інакше в підбірку
        потрапляє вся категорія без розбору."""
        note = NoteFactory(name='Ірис', family=Note.FAMILY_FLORAL)
        base = ProductFactory(name='Основний')
        sibling = ProductFactory(name='Схожий')
        ProductFactory(name='Несхожий')

        ProductNoteFactory(product=base, note=note, layer=ProductNote.LAYER_HEART)
        ProductNoteFactory(product=sibling, note=note, layer=ProductNote.LAYER_BASE)

        response = self.client.get(base.get_absolute_url())
        names = [p.name for p in response.context['related_products']]

        self.assertIn('Схожий', names)
        self.assertNotIn('Несхожий', names)

    def test_view_counter_increments(self):
        product = ProductFactory(views_count=0)

        self.client.get(product.get_absolute_url())

        product.refresh_from_db()
        self.assertEqual(product.views_count, 1)

    def test_breadcrumbs_follow_the_tree(self):
        root = CategoryFactory(name='Аромати')
        child = CategoryFactory(name='Деревні', parent=root)
        product = ProductFactory(category=child)

        crumbs = [
            c.name for c in self.client.get(product.get_absolute_url()).context['breadcrumbs']
        ]

        self.assertEqual(crumbs, ['Аромати', 'Деревні'])


def _price_templates():
    """Шаблони, у яких може зустрітись ціна — разом із листами та PDF."""
    root = Path(settings.BASE_DIR) / 'templates'
    return sorted([*root.rglob('*.html'), *root.rglob('*.txt')])


class MoneyFormatTests(CatalogueTestCase):
    """Ціна на всьому сайті виглядає однаково: «1 800 ₴».

    Формат тримається тестом, бо ламається тихо: шаблон, який рендерить
    ціну повз фільтр, у коді виглядає нормально — і дає «1800,00 грн» на екрані.
    """

    def test_money_gives_non_breaking_spaces_and_hryvnia(self):
        self.assertEqual(money(Decimal('1800.00')), f'1{NBSP}800{NBSP}₴')

    def test_money_has_no_kopecks_and_no_ordinary_space(self):
        rendered = money(Decimal('1800.49'))

        self.assertEqual(rendered, f'1{NBSP}800{NBSP}₴')
        self.assertNotIn(' ', rendered)
        self.assertNotIn(',', rendered)

    def test_money_amount_has_no_currency_sign(self):
        self.assertEqual(money_amount(Decimal('1800.00')), f'1{NBSP}800')

    def test_product_page_shows_the_site_format(self):
        product = ProductFactory(price=Decimal('1800.00'))

        response = self.client.get(product.get_absolute_url())

        self.assertContains(response, f'1{NBSP}800{NBSP}₴')
        self.assertNotContains(response, '1800,00')

    def test_no_template_says_hryvnia_in_words(self):
        offenders = [
            str(path.relative_to(settings.BASE_DIR))
            for path in _price_templates()
            if 'грн' in path.read_text(encoding='utf-8')
        ]

        self.assertEqual(offenders, [], f'«грн» замість ₴: {offenders}')

    def test_no_template_doubles_the_currency_sign(self):
        """Фільтр додає ₴ сам — ручний символ поряд дав би «1 800 ₴ ₴»."""
        offenders = []

        for path in _price_templates():
            source = path.read_text(encoding='utf-8')
            for match in re.finditer(r'\|\s*money\s*\}\}[  ]*₴', source):
                line = source[: match.start()].count('\n') + 1
                offenders.append(f'{path.relative_to(settings.BASE_DIR)}:{line}')

        self.assertEqual(offenders, [], f'Подвоєна гривня: {offenders}')

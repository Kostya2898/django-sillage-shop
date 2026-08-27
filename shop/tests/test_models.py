"""Моделі каталогу: slug-и, знижки, дерево категорій, ноти, зображення, рейтинг."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from shop.models import (
    Brand,
    Note,
    Product,
    ProductImage,
    ProductNote,
    Review,
    validate_image_size,
)
from shop.utils import transliterate, ukrainian_slugify
from testing import ShopTestCase
from testing.factories import (
    BrandFactory,
    CategoryFactory,
    NoteFactory,
    ProductFactory,
    UserFactory,
)


class SlugTransliterationTests(TestCase):
    """Кирилиця не має перетворюватись на порожній slug."""

    def test_django_slugify_alone_would_return_empty(self):
        """Фіксуємо причину, заради якої взагалі потрібна транслітерація."""
        from django.utils.text import slugify

        self.assertEqual(slugify('Амброве серце'), '')

    def test_required_example_from_the_task(self):
        self.assertEqual(ukrainian_slugify('Амброве серце'), 'ambrove-sertse')

    def test_matches_slugs_fixed_in_data_plan(self):
        cases = {
            'Кедрова тиша': 'kedrova-tysha',
            'Ветивер Обскюр': 'vetyver-obskiur',
            'Тубероза після дощу': 'tuberoza-pislia-doshchu',
            'Шкіряна палітурка': 'shkiriana-paliturka',
            'Інжирне варення': 'inzhyrne-varennia',
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(ukrainian_slugify(name), expected)

    def test_word_initial_letters_follow_the_standard(self):
        """КМУ №55: на початку слова «я» → ya, усередині → ia."""
        self.assertEqual(transliterate('Ялинка'), 'Yalynka')
        self.assertEqual(transliterate('після'), 'pislia')
        self.assertEqual(transliterate('Їжак'), 'Yizhak')

    def test_apostrophe_is_dropped(self):
        self.assertEqual(ukrainian_slugify('Фʼйорд'), 'fiord')

    def test_latin_names_survive_untouched(self):
        self.assertEqual(ukrainian_slugify('Discovery Set'), 'discovery-set')


class ProductSlugTests(ShopTestCase):
    def test_slug_is_generated_from_cyrillic_name(self):
        product = ProductFactory(name='Амброве серце', slug='')

        self.assertEqual(product.slug, 'ambrove-sertse')

    def test_duplicate_names_get_numeric_suffixes(self):
        first = ProductFactory(name='Кедрова тиша', slug='')
        second = ProductFactory(name='Кедрова тиша', slug='')
        third = ProductFactory(name='Кедрова тиша', slug='')

        self.assertEqual(first.slug, 'kedrova-tysha')
        self.assertEqual(second.slug, 'kedrova-tysha-2')
        self.assertEqual(third.slug, 'kedrova-tysha-3')

    def test_slug_survives_repeated_save(self):
        """Повторне збереження не має нарощувати суфікс."""
        product = ProductFactory(name='Солоний камінь', slug='')
        original = product.slug

        product.save()
        product.save()

        self.assertEqual(product.slug, original)

    def test_explicit_slug_is_respected(self):
        product = ProductFactory(name='Амброве серце', slug='my-own-slug')

        self.assertEqual(product.slug, 'my-own-slug')

    def test_slug_is_unique_at_database_level(self):
        ProductFactory(slug='taken-slug')

        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductFactory(slug='taken-slug')

    def test_sku_is_generated_and_unique(self):
        first = ProductFactory(name='Кедрова тиша', sku='')
        second = ProductFactory(name='Кедрова тиша', sku='')

        self.assertTrue(first.sku.startswith('SLG-'))
        self.assertNotEqual(first.sku, second.sku)


class CategorySlugAndTreeTests(ShopTestCase):
    def setUp(self):
        self.aromas = CategoryFactory(name='Аромати', slug='')
        self.woody = CategoryFactory(name='Деревні', slug='', parent=self.aromas)
        self.floral = CategoryFactory(name='Квіткові', slug='', parent=self.aromas)
        self.rare = CategoryFactory(name='Рідкісні', slug='', parent=self.woody)

    def test_category_slug_is_transliterated(self):
        self.assertEqual(self.aromas.slug, 'aromaty')
        self.assertEqual(self.woody.slug, 'derevni')

    def test_get_children_returns_direct_children_only(self):
        children = set(self.aromas.get_children())

        self.assertEqual(children, {self.woody, self.floral})

    def test_get_children_skips_inactive(self):
        self.floral.is_active = False
        self.floral.save()

        self.assertEqual(set(self.aromas.get_children()), {self.woody})

    def test_get_descendants_walks_the_whole_branch(self):
        descendants = set(self.aromas.get_descendants())

        self.assertEqual(descendants, {self.woody, self.floral, self.rare})

    def test_get_descendants_can_include_self(self):
        descendants = self.aromas.get_descendants(include_self=True)

        self.assertIn(self.aromas, descendants)
        self.assertEqual(len(descendants), 4)

    def test_leaf_has_no_descendants(self):
        self.assertEqual(self.rare.get_descendants(), [])

    def test_get_ancestors_is_ordered_from_the_root(self):
        self.assertEqual(self.rare.get_ancestors(), [self.aromas, self.woody])

    def test_get_ancestors_with_self_is_a_breadcrumb(self):
        self.assertEqual(
            self.rare.get_ancestors(include_self=True),
            [self.aromas, self.woody, self.rare],
        )

    def test_root_has_no_ancestors(self):
        self.assertEqual(self.aromas.get_ancestors(), [])

    def test_product_count_covers_the_whole_branch(self):
        ProductFactory(category=self.woody)
        ProductFactory(category=self.rare)
        ProductFactory(category=self.floral, is_available=False)

        self.assertEqual(self.aromas.product_count, 2)
        self.assertEqual(self.woody.product_count, 2)
        self.assertEqual(self.rare.product_count, 1)


class DiscountTests(ShopTestCase):
    def test_no_discount_without_old_price(self):
        product = ProductFactory(price=Decimal('4200.00'), old_price=None)

        self.assertFalse(product.has_discount)
        self.assertEqual(product.discount_percent, 0)

    def test_discount_percent_is_rounded_down(self):
        product = ProductFactory(price=Decimal('4900.00'), old_price=Decimal('6200.00'))

        self.assertTrue(product.has_discount)
        self.assertEqual(product.discount_percent, 20)

    def test_old_price_lower_than_price_is_not_a_discount(self):
        """Захист від помилки контент-менеджера: «знижка» вгору не рахується."""
        product = ProductFactory(price=Decimal('5000.00'), old_price=Decimal('4000.00'))

        self.assertFalse(product.has_discount)
        self.assertEqual(product.discount_percent, 0)

    def test_equal_prices_are_not_a_discount(self):
        product = ProductFactory(price=Decimal('5000.00'), old_price=Decimal('5000.00'))

        self.assertFalse(product.has_discount)


class ProductImageTests(ShopTestCase):
    def test_only_one_main_image_per_product(self):
        product = ProductFactory()
        ProductImage.objects.create(product=product, image='a.webp', is_main=True)

        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductImage.objects.create(product=product, image='b.webp', is_main=True)

    def test_secondary_images_are_unlimited(self):
        product = ProductFactory()
        ProductImage.objects.create(product=product, image='a.webp', is_main=True)
        ProductImage.objects.create(product=product, image='b.webp', is_main=False)
        ProductImage.objects.create(product=product, image='c.webp', is_main=False)

        self.assertEqual(product.images.count(), 3)

    def test_different_products_may_each_have_a_main_image(self):
        first = ProductFactory()
        second = ProductFactory()

        ProductImage.objects.create(product=first, image='a.webp', is_main=True)
        ProductImage.objects.create(product=second, image='b.webp', is_main=True)

        self.assertEqual(ProductImage.objects.filter(is_main=True).count(), 2)

    def test_alt_text_falls_back_to_product_name(self):
        product = ProductFactory(name='Кедрова тиша')
        image = ProductImage.objects.create(product=product, image='a.webp')

        self.assertEqual(image.alt_text, 'Кедрова тиша')

    def test_explicit_alt_text_is_kept(self):
        product = ProductFactory()
        image = ProductImage.objects.create(
            product=product, image='a.webp', alt_text='Флакон на чорному тлі'
        )

        self.assertEqual(image.alt_text, 'Флакон на чорному тлі')

    def test_oversized_file_is_rejected(self):
        class FakeFile:
            size = 6 * 1024 * 1024

        with self.assertRaises(ValidationError):
            validate_image_size(FakeFile())

    def test_file_within_limit_passes(self):
        class FakeFile:
            size = 1024

        validate_image_size(FakeFile())  # не має підняти виняток


class NotePyramidTests(ShopTestCase):
    def setUp(self):
        self.product = ProductFactory(name='Ветивер Обскюр')
        self.pepper = NoteFactory(name='Чорний перець', family=Note.FAMILY_SPICY)
        self.vetiver = NoteFactory(name='Ветивер', family=Note.FAMILY_WOODY)
        self.iris = NoteFactory(name='Ірис', family=Note.FAMILY_FLORAL)
        self.moss = NoteFactory(name='Дубовий мох', family=Note.FAMILY_WOODY)

        ProductNote.objects.create(
            product=self.product, note=self.pepper, layer=ProductNote.LAYER_TOP, position=1
        )
        ProductNote.objects.create(
            product=self.product, note=self.vetiver, layer=ProductNote.LAYER_HEART, position=1
        )
        ProductNote.objects.create(
            product=self.product, note=self.iris, layer=ProductNote.LAYER_HEART, position=2
        )
        ProductNote.objects.create(
            product=self.product, note=self.moss, layer=ProductNote.LAYER_BASE, position=1
        )

    def test_pyramid_splits_into_three_layers(self):
        self.assertEqual(self.product.top_notes, [self.pepper])
        self.assertEqual(self.product.heart_notes, [self.vetiver, self.iris])
        self.assertEqual(self.product.base_notes, [self.moss])

    def test_position_defines_order_within_a_layer(self):
        self.assertEqual(
            [note.name for note in self.product.heart_notes],
            ['Ветивер', 'Ірис'],
        )

    def test_same_note_may_repeat_in_another_layer(self):
        """Ветивер у серці й у базі — нормальна композиція."""
        ProductNote.objects.create(
            product=self.product, note=self.vetiver, layer=ProductNote.LAYER_BASE, position=2
        )

        self.assertIn(self.vetiver, self.product.base_notes)

    def test_same_note_cannot_repeat_within_one_layer(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductNote.objects.create(
                product=self.product,
                note=self.vetiver,
                layer=ProductNote.LAYER_HEART,
                position=9,
            )

    def test_m2m_gives_all_notes_of_the_product(self):
        self.assertEqual(self.product.notes.count(), 4)

    def test_note_knows_its_products(self):
        self.assertIn(self.product, self.vetiver.products.all())


class ReviewTests(ShopTestCase):
    def test_one_review_per_user_per_product(self):
        user = UserFactory()
        product = ProductFactory()
        Review.objects.create(user=user, product=product, rating=5, text='Чудово')

        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(user=user, product=product, rating=3, text='Передумав')

    def test_reviews_are_hidden_until_moderated(self):
        review = Review.objects.create(
            user=UserFactory(), product=ProductFactory(), rating=5, text='Чудово'
        )

        self.assertFalse(review.is_approved)

    def test_rating_outside_one_to_five_is_invalid(self):
        review = Review(user=UserFactory(), product=ProductFactory(), rating=6, text='?')

        with self.assertRaises(ValidationError):
            review.full_clean()


class ProductQuerySetTests(ShopTestCase):
    def setUp(self):
        self.brand = BrandFactory(name='Nord Botanica')
        self.category = CategoryFactory(name='Деревні')
        self.product = ProductFactory(brand=self.brand, category=self.category, is_featured=True)
        ProductImage.objects.create(product=self.product, image='main.webp', is_main=True)
        ProductImage.objects.create(product=self.product, image='second.webp')

    def test_available_hides_unavailable(self):
        ProductFactory(is_available=False)

        self.assertEqual(Product.objects.available().count(), 1)

    def test_featured_returns_only_curated(self):
        ProductFactory(is_featured=False)

        self.assertEqual(list(Product.objects.featured()), [self.product])

    def test_in_stock_excludes_zero_stock(self):
        ProductFactory(stock=0)

        self.assertEqual(Product.objects.in_stock().count(), 1)

    def test_with_relations_and_rating_take_few_queries(self):
        """Ціль з ТЗ: товар з брендом, категорією, фото і рейтингом за 2–3 запити."""
        ProductFactory.create_batch(5, brand=self.brand, category=self.category)

        with self.assertNumQueries(2):
            products = list(Product.objects.with_relations().with_rating())
            # Складаємо все, що знадобиться картці каталогу: якщо котресь із
            # цього не префетчилось, лічильник запитів одразу підскочить.
            touched = [
                (
                    product.brand.name,
                    product.category.name,
                    product.main_images,
                    product.average_rating,
                    product.reviews_count,
                )
                for product in products
            ]

        self.assertEqual(len(touched), 6)

    def test_with_rating_counts_only_approved_reviews(self):
        Review.objects.create(
            user=UserFactory(), product=self.product, rating=5, text='ок', is_approved=True
        )
        Review.objects.create(
            user=UserFactory(), product=self.product, rating=1, text='ні', is_approved=False
        )

        annotated = Product.objects.with_rating().get(pk=self.product.pk)
        self.assertEqual(annotated.reviews_count, 1)
        self.assertEqual(annotated.average_rating, 5.0)

    def test_product_without_reviews_has_no_rating(self):
        annotated = Product.objects.with_rating().get(pk=self.product.pk)

        self.assertIsNone(annotated.average_rating)
        self.assertEqual(annotated.reviews_count, 0)

    def test_main_image_prefers_cover(self):
        self.product.cover = 'cover.webp'
        self.product.save(update_fields=['cover'])

        self.assertEqual(self.product.main_image.name, 'cover.webp')

    def test_main_image_falls_back_to_flagged_image(self):
        self.assertEqual(self.product.main_image.name, 'main.webp')


class BrandTests(ShopTestCase):
    def test_brand_slug_is_transliterated(self):
        brand = Brand.objects.create(name='Ательє Нуар')

        self.assertEqual(brand.slug, 'atelie-nuar')

    def test_products_are_protected_from_brand_deletion(self):
        """Бренд не можна знести разом із його товарами — on_delete=PROTECT."""
        from django.db.models import ProtectedError

        brand = BrandFactory()
        ProductFactory(brand=brand)

        with self.assertRaises(ProtectedError):
            brand.delete()


class CategoryProtectionTests(ShopTestCase):
    def test_category_with_products_cannot_be_deleted(self):
        from django.db.models import ProtectedError

        category = CategoryFactory()
        ProductFactory(category=category)

        with self.assertRaises(ProtectedError):
            category.delete()

"""Адмінка каталогу: бренди, категорії, товари з нотами, відгуки.

Адмінка тут — робочий інструмент контент-менеджера, а не дефолт «як вийшло».
Тому: щільний список із мініатюрами й станом складу, групування полів за
змістом, масові дії замість редагування по одному, і жодного зайвого запиту
в базу на рендер списку.
"""

import codecs
import csv

from django.contrib import admin
from django.db.models import Count
from django.http import HttpResponse
from django.utils.html import format_html
from django.utils.text import Truncator

from .models import Brand, Category, Note, Product, ProductImage, ProductNote, Review

# Кольори станів. Беремо з палітри SILLAGE (PROJECT_VISION.md), щоб адмінка
# не заводила власного набору кольорів: латунь — попередження, вуглиста
# троянда — проблема.
COLOR_DANGER = '#b8615a'
COLOR_WARNING = '#a8842f'
COLOR_MUTED = '#6c757d'

THUMBNAIL_SIZE = 75


def _thumbnail(image, size=THUMBNAIL_SIZE, radius=4):
    """Мініатюра для списку. `format_html` екранує URL — mark_safe не потрібен."""
    if not image:
        return format_html('<span style="color:{}">—</span>', COLOR_MUTED)

    return format_html(
        '<img src="{}" style="width:{}px;height:{}px;object-fit:cover;'
        'border-radius:{}px;background:#16131b" alt="">',
        image.url,
        size,
        size,
        radius,
    )


# ---------------------------------------------------------------------------
# Власні фільтри
# ---------------------------------------------------------------------------


class PriceRangeFilter(admin.SimpleListFilter):
    """Ціновий діапазон — швидше, ніж вводити межі руками щоразу."""

    title = 'Ціновий діапазон'
    parameter_name = 'price_range'

    RANGES = {
        'budget': ('до 2 000 ₴', {'price__lt': 2000}),
        'mid': ('2 000 – 4 000 ₴', {'price__gte': 2000, 'price__lt': 4000}),
        'high': ('4 000 – 7 000 ₴', {'price__gte': 4000, 'price__lt': 7000}),
        'lux': ('понад 7 000 ₴', {'price__gte': 7000}),
    }

    def lookups(self, request, model_admin):
        return [(key, label) for key, (label, _) in self.RANGES.items()]

    def queryset(self, request, queryset):
        selected = self.RANGES.get(self.value())
        return queryset.filter(**selected[1]) if selected else queryset


class StockStateFilter(admin.SimpleListFilter):
    """Наявність: що закінчується — важливіше, ніж що просто є."""

    title = 'Наявність'
    parameter_name = 'stock_state'

    LOW_STOCK_THRESHOLD = 5

    def lookups(self, request, model_admin):
        return [
            ('in_stock', 'Є на складі'),
            ('low', f'Закінчується (менше {self.LOW_STOCK_THRESHOLD})'),
            ('out', 'Немає'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'in_stock':
            return queryset.filter(stock__gt=0)
        if self.value() == 'low':
            return queryset.filter(stock__gt=0, stock__lt=self.LOW_STOCK_THRESHOLD)
        if self.value() == 'out':
            return queryset.filter(stock=0)
        return queryset


# ---------------------------------------------------------------------------
# Бренди, категорії, ноти
# ---------------------------------------------------------------------------


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    """Парфумерні доми. `search_fields` тут потрібні для autocomplete у товарі."""

    list_display = [
        'logo_preview',
        'name',
        'country',
        'founded_year',
        'products_total',
        'is_active',
    ]
    list_display_links = ['name']
    list_filter = ['is_active', 'country']
    list_editable = ['is_active']
    search_fields = ['name', 'country', 'description']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['sort_order', 'name']

    def get_queryset(self, request):
        # Лічильник агрегатом, а не obj.products.count() на кожен рядок.
        return super().get_queryset(request).annotate(_products_total=Count('products'))

    @admin.display(description='Логотип')
    def logo_preview(self, obj):
        return _thumbnail(obj.logo, size=48)

    @admin.display(description='Товарів', ordering='_products_total')
    def products_total(self, obj):
        return obj._products_total


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Дерево категорій. Вкладеність показана відступом, бо рівнів усього два."""

    list_display = ['tree_name', 'products_total', 'sort_order', 'is_featured', 'is_active']
    list_display_links = ['tree_name']
    list_filter = ['is_active', 'is_featured', 'parent']
    list_editable = ['sort_order', 'is_featured', 'is_active']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    actions = ['activate_branch', 'deactivate_branch']
    # Корені (parent=NULL) ідуть першими, далі — діти, згруповані за батьком.
    ordering = ['parent__sort_order', 'parent__name', 'sort_order', 'name']

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related('parent')
            .annotate(_products_total=Count('products'))
        )

    @admin.display(description='Категорія')
    def tree_name(self, obj):
        if obj.parent_id is None:
            return format_html('<strong>{}</strong>', obj.name)
        return format_html('<span style="color:{}">└─</span> {}', COLOR_MUTED, obj.name)

    @admin.display(description='Товарів', ordering='_products_total')
    def products_total(self, obj):
        return obj._products_total

    @admin.action(description='Активувати гілку (з підкатегоріями)')
    def activate_branch(self, request, queryset):
        self._switch_branch(request, queryset, True)

    @admin.action(description='Деактивувати гілку (з підкатегоріями)')
    def deactivate_branch(self, request, queryset):
        self._switch_branch(request, queryset, False)

    def _switch_branch(self, request, queryset, is_active):
        """Вмикає або вимикає обрані категорії разом з усіма нащадками.

        Свідомо не через `get_descendants()`: той метод віддає лише активні
        гілки, і ввімкнути назад вимкнене дерево ним було б неможливо —
        діти лишились би прихованими назавжди.
        """
        touched = set()
        for category in queryset:
            touched.add(category.pk)
            touched.update(self._all_descendant_ids(category))

        updated = Category.objects.filter(pk__in=touched).update(is_active=is_active)
        verb = 'Активовано' if is_active else 'Деактивовано'
        self.message_user(request, f'{verb} категорій: {updated}')

    def _all_descendant_ids(self, category):
        """Усі нащадки, незалежно від їхнього `is_active`."""
        ids = set()
        for child in category.children.all():
            ids.add(child.pk)
            ids.update(self._all_descendant_ids(child))
        return ids


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    """Ольфакторні ноти. `search_fields` живлять autocomplete у піраміді товару."""

    list_display = ['name', 'family', 'products_total']
    list_filter = ['family']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_products_total=Count('products'))

    @admin.display(description='Ароматів', ordering='_products_total')
    def products_total(self, obj):
        return obj._products_total


# ---------------------------------------------------------------------------
# Товар
# ---------------------------------------------------------------------------


class ProductImageInline(admin.TabularInline):
    """Галерея товару з прев'ю прямо в рядку."""

    model = ProductImage
    extra = 1
    fields = ['preview', 'image', 'alt_text', 'is_main', 'sort_order']
    readonly_fields = ['preview']
    ordering = ['-is_main', 'sort_order']

    @admin.display(description='Превʼю')
    def preview(self, obj):
        return _thumbnail(obj.image, size=60)


class ProductNoteInline(admin.TabularInline):
    """Піраміда аромату: тут і тільки тут вона наповнюється."""

    model = ProductNote
    extra = 3
    autocomplete_fields = ['note']
    fields = ['note', 'layer', 'position']
    ordering = ['layer', 'position']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'thumbnail',
        'name',
        'brand',
        'category',
        'concentration',
        'volume_ml',
        'price',
        'discount_badge',
        'stock',
        'stock_state',
        'is_featured',
        'is_available',
    ]
    list_display_links = ['name']
    list_editable = ['price', 'stock', 'is_featured', 'is_available']
    list_filter = [
        PriceRangeFilter,
        StockStateFilter,
        'brand',
        'category',
        'concentration',
        'gender',
        'is_featured',
        'is_new',
        'is_available',
        'created_at',
    ]
    search_fields = ['name', 'sku', 'brand__name', 'notes__name']
    autocomplete_fields = ['brand', 'category']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = [
        'cover_preview',
        'views_count',
        'sold_count',
        'created_at',
        'modified_at',
    ]
    inlines = [ProductNoteInline, ProductImageInline]
    actions = [
        'make_featured',
        'unmake_featured',
        'mark_as_new',
        'withdraw_from_sale',
        'export_csv',
    ]
    list_per_page = 50

    fieldsets = (
        ('Основне', {'fields': ('name', 'brand', 'category', 'short_description', 'description')}),
        (
            'Ольфакторика',
            {
                'fields': (
                    'concentration',
                    'gender',
                    'volume_ml',
                    'longevity_hours',
                    'sillage',
                    'perfumer',
                    'year_released',
                    'country',
                ),
                'description': 'Самі ноти додаються нижче, у піраміді аромату.',
            },
        ),
        ('Ціна і склад', {'fields': ('price', 'old_price', 'stock')}),
        (
            'Публікація',
            {'fields': ('cover', 'cover_preview', 'is_featured', 'is_new', 'is_available')},
        ),
        (
            'Службове',
            {
                'classes': ('collapse',),
                'fields': ('slug', 'sku', 'views_count', 'sold_count', 'created_at', 'modified_at'),
            },
        ),
    )

    def get_queryset(self, request):
        """Бренд, категорія і головне фото — одним заходом.

        Без цього список із 50 товарів робив би сотні запитів: по одному
        на бренд, категорію і фото кожного рядка.
        """
        return super().get_queryset(request).with_relations()

    def get_search_results(self, request, queryset, search_term):
        results, _ = super().get_search_results(request, queryset, search_term)
        # Пошук іде через M2M `notes`, тож без distinct товар з двома
        # збіжними нотами приїхав би у список двічі.
        return results, True

    # --- колонки списку ---

    @admin.display(description='Фото')
    def thumbnail(self, obj):
        return _thumbnail(obj.main_image)

    @admin.display(description='Знижка')
    def discount_badge(self, obj):
        if not obj.has_discount:
            return format_html('<span style="color:{}">—</span>', COLOR_MUTED)
        return format_html(
            '<span style="color:{};text-decoration:line-through">{} ₴</span>'
            '<br><strong style="color:{}">−{}%</strong>',
            COLOR_MUTED,
            obj.old_price,
            COLOR_DANGER,
            obj.discount_percent,
        )

    @admin.display(description='Стан складу')
    def stock_state(self, obj):
        if obj.stock == 0:
            return format_html('<strong style="color:{}">немає</strong>', COLOR_DANGER)
        if obj.stock < StockStateFilter.LOW_STOCK_THRESHOLD:
            return format_html('<strong style="color:{}">закінчується</strong>', COLOR_WARNING)
        return format_html('<span style="color:{}">достатньо</span>', COLOR_MUTED)

    @admin.display(description='Поточна обкладинка')
    def cover_preview(self, obj):
        return _thumbnail(obj.cover, size=220, radius=8)

    # --- масові дії ---

    def _report(self, request, updated):
        self.message_user(request, f'Оновлено товарів: {updated}')

    @admin.action(description='Додати до кураторського вибору')
    def make_featured(self, request, queryset):
        self._report(request, queryset.filter(is_featured=False).update(is_featured=True))

    @admin.action(description='Прибрати з кураторського вибору')
    def unmake_featured(self, request, queryset):
        self._report(request, queryset.filter(is_featured=True).update(is_featured=False))

    @admin.action(description='Позначити як новинку')
    def mark_as_new(self, request, queryset):
        self._report(request, queryset.filter(is_new=False).update(is_new=True))

    @admin.action(description='Зняти з продажу')
    def withdraw_from_sale(self, request, queryset):
        self._report(request, queryset.filter(is_available=True).update(is_available=False))

    @admin.action(description='Експортувати вибране у CSV')
    def export_csv(self, request, queryset):
        """CSV, який відкривається в Excel без танців із кодуванням.

        Excel вважає CSV однобайтовим, поки не побачить BOM на початку —
        без нього кирилиця перетворюється на кракозябри.
        """
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="sillage-products.csv"'
        response.write(codecs.BOM_UTF8.decode('utf-8'))

        writer = csv.writer(response, delimiter=';')
        writer.writerow(
            [
                'Артикул',
                'Назва',
                'Бренд',
                'Категорія',
                'Обʼєм, мл',
                'Концентрація',
                'Ціна',
                'Стара ціна',
                'Залишок',
                'Доступний',
                'Кураторський вибір',
            ]
        )

        for product in queryset.select_related('brand', 'category'):
            writer.writerow(
                [
                    product.sku,
                    product.name,
                    product.brand.name,
                    product.category.name,
                    product.volume_ml or '',
                    product.get_concentration_display(),
                    product.price,
                    product.old_price or '',
                    product.stock,
                    'так' if product.is_available else 'ні',
                    'так' if product.is_featured else 'ні',
                ]
            )

        self.message_user(request, f'Експортовано товарів: {queryset.count()}')
        return response


# ---------------------------------------------------------------------------
# Відгуки
# ---------------------------------------------------------------------------


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """Модерація відгуків: усе, що потрібно — рейтинг, уривок і дві кнопки."""

    list_display = [
        'product',
        'user',
        'rating_stars',
        'excerpt',
        'is_verified_purchase',
        'is_approved',
        'created_at',
    ]
    list_display_links = ['product']
    list_editable = ['is_approved']
    list_filter = ['is_approved', 'rating', 'is_verified_purchase', 'created_at']
    search_fields = ['product__name', 'user__username', 'user__email', 'title', 'text']
    readonly_fields = ['created_at', 'updated_at']
    actions = ['approve', 'reject']
    date_hierarchy = 'created_at'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('product', 'user')

    def get_readonly_fields(self, request, obj=None):
        """Автора й товар після створення не міняють — це підміна відгуку."""
        if obj is None:
            return self.readonly_fields
        return [*self.readonly_fields, 'user', 'product']

    @admin.display(description='Оцінка', ordering='rating')
    def rating_stars(self, obj):
        filled = '★' * obj.rating
        empty = '☆' * (Review.RATING_MAX - obj.rating)
        return format_html('<span title="{}/5">{}{}</span>', obj.rating, filled, empty)

    @admin.display(description='Уривок')
    def excerpt(self, obj):
        return Truncator(obj.text).chars(80)

    @admin.action(description='Схвалити')
    def approve(self, request, queryset):
        updated = queryset.filter(is_approved=False).update(is_approved=True)
        self.message_user(request, f'Опубліковано відгуків: {updated}')

    @admin.action(description='Відхилити')
    def reject(self, request, queryset):
        updated = queryset.filter(is_approved=True).update(is_approved=False)
        self.message_user(request, f'Знято з публікації: {updated}')

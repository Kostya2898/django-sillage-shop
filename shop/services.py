"""Логіка каталогу: фільтри, сортування, фасети.

Живе окремо від view з двох причин. По-перше, правило проєкту: бізнес-логіка,
довша за 15 рядків, не сидить у view. По-друге, той самий код обслуговує і
звичайний рендер сторінки, і JSON-відповідь для фільтрів без перезавантаження —
дублювати його у двох місцях означало б рано чи пізно їх розсинхронити.
"""

from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.db.models import Count, Q

from .models import Brand, Category, Note, Product

# Скільки товарів на сторінці каталогу.
PRODUCTS_PER_PAGE = 12

# Скільки підказок віддає живий пошук.
SEARCH_SUGGESTIONS = 6

FACETS_CACHE_KEY = 'shop:catalogue-facets'
FACETS_CACHE_TIMEOUT = 60 * 15

# Дерево для мега-меню. Окремий ключ, а не частина фасетів: меню є на кожній
# сторінці сайту, а фасети потрібні лише каталогу — тягнути повний набір
# брендів і нот у підвал і на checkout немає сенсу.
NAV_CACHE_KEY = 'shop:navigation-tree'
NAV_CACHE_TIMEOUT = 60 * 15

# Скільком ароматам показувати дорогу, коли пошук нічого не знайшов.
FALLBACK_SUGGESTIONS = 3

# Порядок сортування: значення в URL → (підпис, поля для order_by).
SORT_OPTIONS = {
    'featured': ('Спершу кураторський вибір', ['-is_featured', 'name']),
    'new': ('Спершу новинки', ['-is_new', '-created_at']),
    'price': ('Ціна: від дешевших', ['price', 'name']),
    '-price': ('Ціна: від дорожчих', ['-price', 'name']),
    'popular': ('Найпопулярніші', ['-sold_count', '-views_count']),
    'name': ('За назвою', ['name']),
}
DEFAULT_SORT = 'featured'


def _decimal_or_none(raw):
    """Ціна з GET-параметра. Сміття мовчки ігнорується, а не валить сторінку."""
    if not raw:
        return None
    try:
        value = Decimal(str(raw).replace(',', '.'))
    except (InvalidOperation, ValueError):
        return None
    return value if value >= 0 else None


class CatalogueQuery:
    """Розібраний запит каталогу: що фільтруємо, як сортуємо, що показати в UI.

    Створюється з `request.GET` і далі сам знає і як побудувати queryset,
    і як розповісти шаблону про поточний стан фільтрів.
    """

    def __init__(self, params, category=None):
        self.params = params
        self.category = category

        self.query = (params.get('q') or '').strip()
        self.brands = params.getlist('brand')
        self.notes = params.getlist('note')
        self.concentrations = params.getlist('concentration')
        self.genders = params.getlist('gender')
        self.price_min = _decimal_or_none(params.get('price_min'))
        self.price_max = _decimal_or_none(params.get('price_max'))
        self.in_stock = params.get('in_stock') in ('1', 'true', 'on')
        self.sort = params.get('sort') if params.get('sort') in SORT_OPTIONS else DEFAULT_SORT

        # Порожні межі ціни, введені навпаки, міняємо місцями, а не показуємо
        # користувачу порожній каталог і незрозуміле «нічого не знайдено».
        if self.price_min is not None and self.price_max is not None:
            if self.price_min > self.price_max:
                self.price_min, self.price_max = self.price_max, self.price_min

    # --- побудова вибірки -------------------------------------------------

    def queryset(self):
        """Готовий queryset каталогу з усіма застосованими фільтрами."""
        products = Product.objects.available().with_relations().with_rating()

        if self.category is not None:
            # Уся гілка категорії, а не лише вона сама.
            branch = self.category.get_descendants(include_self=True)
            products = products.filter(category__in=branch)

        if self.query:
            products = products.filter(
                Q(name__icontains=self.query)
                | Q(short_description__icontains=self.query)
                | Q(description__icontains=self.query)
                | Q(brand__name__icontains=self.query)
                | Q(notes__name__icontains=self.query)
            ).distinct()

        if self.brands:
            products = products.filter(brand__slug__in=self.brands)

        if self.notes:
            # distinct обовʼязковий: товар із двома збіжними нотами інакше
            # приїхав би у список двічі.
            products = products.filter(notes__slug__in=self.notes).distinct()

        if self.concentrations:
            products = products.filter(concentration__in=self.concentrations)

        if self.genders:
            products = products.filter(gender__in=self.genders)

        if self.price_min is not None:
            products = products.filter(price__gte=self.price_min)

        if self.price_max is not None:
            products = products.filter(price__lte=self.price_max)

        if self.in_stock:
            products = products.filter(stock__gt=0)

        return products.order_by(*SORT_OPTIONS[self.sort][1])

    # --- стан для шаблону -------------------------------------------------

    @property
    def is_filtered(self):
        """Чи застосовано хоч один фільтр — від цього залежить кнопка «скинути»."""
        return any(
            [
                self.query,
                self.brands,
                self.notes,
                self.concentrations,
                self.genders,
                self.price_min is not None,
                self.price_max is not None,
                self.in_stock,
                self.category is not None,
            ]
        )

    @property
    def active_count(self):
        """Скільки фільтрів увімкнено — показуємо числом біля кнопки на мобільному."""
        return sum(
            [
                len(self.brands),
                len(self.notes),
                len(self.concentrations),
                len(self.genders),
                1 if self.price_min is not None else 0,
                1 if self.price_max is not None else 0,
                1 if self.in_stock else 0,
            ]
        )

    def as_state(self):
        """Поточні значення фільтрів — щоб шаблон міг відмітити обрані пункти."""
        return {
            'q': self.query,
            'brands': set(self.brands),
            'notes': set(self.notes),
            'concentrations': set(self.concentrations),
            'genders': set(self.genders),
            'price_min': self.price_min,
            'price_max': self.price_max,
            'in_stock': self.in_stock,
            'sort': self.sort,
        }


# ---------------------------------------------------------------------------
# Фасети
# ---------------------------------------------------------------------------


def build_facets():
    """Списки для панелі фільтрів разом із лічильниками товарів.

    Рахується один раз і кладеться в кеш: без цього кожен рендер каталогу
    додавав би три-чотири запити, які майже ніколи не змінюють результат.
    """
    available = Q(products__is_available=True)

    brands = list(
        Brand.objects.filter(is_active=True)
        .annotate(product_count=Count('products', filter=available, distinct=True))
        .filter(product_count__gt=0)
        .values('name', 'slug', 'product_count')
        .order_by('name')
    )

    notes = list(
        Note.objects.annotate(product_count=Count('products', filter=available, distinct=True))
        .filter(product_count__gt=0)
        .values('name', 'slug', 'family', 'product_count')
        .order_by('family', 'name')
    )

    roots = (
        Category.objects.filter(is_active=True, parent__isnull=True)
        .prefetch_related('children')
        .order_by('sort_order', 'name')
    )
    categories = [
        {
            'name': root.name,
            'slug': root.slug,
            'children': [
                {'name': child.name, 'slug': child.slug}
                for child in root.children.all()
                if child.is_active
            ],
        }
        for root in roots
    ]

    return {
        'brands': brands,
        'notes': notes,
        'categories': categories,
        'concentrations': list(Product.CONCENTRATION_CHOICES),
        'genders': list(Product.GENDER_CHOICES),
        'sorts': [(key, label) for key, (label, _) in SORT_OPTIONS.items()],
    }


def build_navigation_tree():
    """Три колонки мега-меню з лічильниками товарів.

    Лічильники беруться одним запитом із `annotate`, а не циклом по
    категоріях: на тринадцяти категоріях цикл дав би тринадцять запитів на
    кожну сторінку сайту, і саме шапка стала б найдорожчою її частиною.

    Лічильник кореня — сума по дітях, а не окремий запит: товари висять на
    листках, тож корінь без дітей завжди порожній.
    """
    children = (
        Category.objects.filter(is_active=True, parent__isnull=False)
        # `available_count`, не `product_count`: останнє — вже property
        # моделі, і annotate під тим самим імʼям не має куди записатись.
        .annotate(
            available_count=Count('products', filter=Q(products__is_available=True), distinct=True)
        )
        .select_related('parent')
        .order_by('sort_order', 'name')
    )

    grouped = {}
    for child in children:
        grouped.setdefault(child.parent_id, []).append(
            {
                'name': child.name,
                'slug': child.slug,
                'count': child.available_count,
            }
        )

    roots = Category.objects.filter(is_active=True, parent__isnull=True).order_by(
        'sort_order', 'name'
    )

    return [
        {
            'name': root.name,
            'slug': root.slug,
            'children': grouped.get(root.id, []),
            'count': sum(item['count'] for item in grouped.get(root.id, [])),
        }
        for root in roots
    ]


def get_navigation_tree():
    """Дерево меню з кешу. Інвалідується тими ж сигналами, що й фасети."""
    return cache.get_or_set(NAV_CACHE_KEY, build_navigation_tree, NAV_CACHE_TIMEOUT)


def invalidate_navigation_tree():
    cache.delete(NAV_CACHE_KEY)


def fallback_suggestions(limit=FALLBACK_SUGGESTIONS):
    """Що показати, коли пошук нічого не знайшов.

    Порожній екран із «0 результатів» — глухий кут, з якого виходять
    закриванням вкладки. Кураторський вибір дає куди клікнути, і це
    правило UX: порожній результат мусить пропонувати, куди йти далі.
    """
    return (
        Product.objects.available().with_relations().order_by('-is_featured', '-sold_count')[:limit]
    )


def get_facets():
    """Фасети з кешу. Інвалідуються сигналами в `shop/signals.py`."""
    return cache.get_or_set(FACETS_CACHE_KEY, build_facets, FACETS_CACHE_TIMEOUT)


def invalidate_facets():
    cache.delete(FACETS_CACHE_KEY)


# ---------------------------------------------------------------------------
# Живий пошук
# ---------------------------------------------------------------------------


def search_suggestions(term, limit=SEARCH_SUGGESTIONS):
    """Підказки для випадаючого списку пошуку.

    Порожній результат — не глухий кут: викликач підставить кураторський
    вибір, щоб користувач мав куди клікнути (те саме правило UX).
    """
    term = (term or '').strip()
    if len(term) < 2:
        return Product.objects.none()

    return (
        Product.objects.available()
        .with_relations()
        .filter(
            Q(name__icontains=term)
            | Q(brand__name__icontains=term)
            | Q(notes__name__icontains=term)
        )
        .distinct()
        .order_by('-is_featured', 'name')[:limit]
    )


def similar_by_notes(product, limit=4):
    """«Схожі за нотами», а не «схожі за категорією».

    Категорія — надто грубий критерій: усі деревні опиняються в одному кошику.
    Спільні ноти ближчі до того, як люди справді обирають аромат.
    """
    note_ids = list(product.notes.values_list('id', flat=True))
    if not note_ids:
        return Product.objects.available().with_relations().exclude(pk=product.pk)[:limit]

    return (
        Product.objects.available()
        .with_relations()
        .filter(notes__in=note_ids)
        .exclude(pk=product.pk)
        .annotate(shared=Count('notes', filter=Q(notes__in=note_ids), distinct=True))
        .order_by('-shared', '-is_featured')[:limit]
    )

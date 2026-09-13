"""View-функції каталогу: головна, список товарів, живий пошук, картка товару."""

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import F
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_safe

from .models import Category, Product, ProductImage
from .photo_rejects import REJECTED_HASHES, REJECTED_URLS, add_rejection
from .services import (
    PRODUCTS_PER_PAGE,
    CatalogueQuery,
    get_facets,
    search_suggestions,
    similar_by_notes,
)

# Скільки товарів показуємо в кожному блоці головної.
HOME_FEATURED = 6
HOME_NEW = 4


def home(request):
    """Головна «Слід»: кураторський вибір, новинки, вхід у категорії."""
    featured = Product.objects.featured().with_relations().with_rating()[:HOME_FEATURED]
    new_arrivals = (
        Product.objects.available()
        .with_relations()
        .filter(is_new=True)
        .order_by('-created_at')[:HOME_NEW]
    )

    return render(
        request,
        'shop/home.html',
        {
            'featured_products': featured,
            'new_products': new_arrivals,
            'facets': get_facets(),
        },
    )


def product_list(request, category_slug=None):
    """Каталог із фільтрами, сортуванням, пошуком і пагінацією.

    Той самий view віддає і HTML, і JSON: при `?format=json` повертається
    лише сітка товарів, і фронтенд підміняє її без перезавантаження сторінки.
    """
    category = None
    if category_slug:
        category = get_object_or_404(
            Category.objects.select_related('parent'), slug=category_slug, is_active=True
        )

    catalogue = CatalogueQuery(request.GET, category=category)
    paginator = Paginator(catalogue.queryset(), PRODUCTS_PER_PAGE)
    page = paginator.get_page(request.GET.get('page'))

    context = {
        'category': category,
        'ancestors': category.get_ancestors() if category else [],
        'page': page,
        'products': page.object_list,
        'facets': get_facets(),
        'state': catalogue.as_state(),
        'catalogue': catalogue,
        'total': paginator.count,
        # Якщо не знайшлося нічого — показуємо не порожній екран, а те, з чого
        # можна почати. Глухий кут у пошуку дратує більше за самі нулі.
        'fallback_products': (
            Product.objects.featured().with_relations()[:4] if paginator.count == 0 else []
        ),
    }

    if request.GET.get('format') == 'json':
        return render(request, 'shop/_product_grid.html', context)

    return render(request, 'shop/product_list.html', context)


def product_search(request):
    """Живий пошук: підказки для випадаючого списку під полем.

    Віддає JSON, бо це єдиний ендпоінт, який викликається на кожне натискання
    клавіші — рендерити заради нього HTML було б марно.
    """
    term = (request.GET.get('q') or '').strip()
    suggestions = search_suggestions(term)

    results = [
        {
            'name': product.name,
            'brand': product.brand.name,
            'price': str(product.price),
            'url': product.get_absolute_url(),
            'image': product.main_image.url if product.main_image else '',
        }
        for product in suggestions
    ]

    return JsonResponse({'query': term, 'count': len(results), 'results': results})


def product_detail(request, slug):
    """Детальна сторінка товару: піраміда нот, опис і схвалені відгуки."""
    product = get_object_or_404(
        Product.objects.with_relations().with_notes().with_rating().prefetch_related('images'),
        slug=slug,
        is_available=True,
    )

    # Лічильник переглядів рахує база через F(), а не Python: інакше два
    # одночасні перегляди прочитали б однакове значення і один із них зник би.
    Product.objects.filter(pk=product.pk).update(views_count=F('views_count') + 1)

    return render(
        request,
        'shop/product_detail.html',
        {
            'product': product,
            'related_products': similar_by_notes(product),
            'reviews': product.reviews.filter(is_approved=True).select_related('user'),
            'breadcrumbs': product.category.get_ancestors(include_self=True),
        },
    )


@require_safe
def photo_sources(request):
    """Службова сторінка: звідки взялося кожне зображення каталогу.

    Тільки при `DEBUG=True`. Показувати покупцям, з яких адрес зібрані фото,
    сенсу немає, а мені це головний робочий інструмент: видно товар, кадр,
    джерело й запит, за яким кадр знайшовся.

    Запит тут не менш важливий за адресу. Коли кадр виявиться невдалим, видно
    буде, яке формулювання дало сміття, — і можна виправити запит, а не
    перебирати результати наосліп.
    """
    if not settings.DEBUG:
        raise Http404('Сторінка доступна лише в режимі розробки')

    images = ProductImage.objects.select_related('product', 'product__brand').order_by(
        'product__id', 'sort_order'
    )

    rendered = Product.objects.exclude(images__source_url__gt='').order_by('id')

    return render(
        request,
        'shop/photo_sources.html',
        {
            'images': images,
            'rendered': rendered,
            'rejected_urls': REJECTED_URLS,
            'rejected_hashes': REJECTED_HASHES,
        },
    )


@require_POST
def photo_reject(request, image_id):
    """Забракувати кадр: дописати його хеш у `shop/photo_rejects.py`.

    Після цього `--only=<slug> --force` візьме **наступного** кандидата, а не
    того самого. Рішення лягає в код, а не в базу: воно має пережити
    `seed_shop --flush` і потрапити в git разом із причиною.
    """
    if not settings.DEBUG:
        raise Http404('Дія доступна лише в режимі розробки')

    image = get_object_or_404(ProductImage, pk=image_id)
    reason = request.POST.get('reason', '').strip() or 'забраковано вручну'

    if image.source_hash:
        add_rejection(int(image.source_hash, 16), image.source_url, reason)
        messages.success(
            request,
            f'Кадр «{image.product.name}» забраковано. Перезаберіть його: '
            f'manage.py fetch_product_photos --only={image.product.slug} --force',
        )
    else:
        messages.warning(
            request,
            'У цього зображення немає хеша джерела — це рендер, а не фотографія.',
        )

    return redirect('shop:photo_sources')

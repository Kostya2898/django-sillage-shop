"""View-функції каталогу: список товарів з фільтрами та сторінка товару."""

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from .models import Category, Product

PRODUCTS_PER_PAGE = 9


def product_list(request, category_slug=None):
    """Список товарів з фільтром за категорією та пошуком за назвою/описом."""
    categories = Category.objects.filter(is_active=True, parent__isnull=True)
    products = Product.objects.filter(is_available=True).select_related('category')

    category = None
    if category_slug:
        category = get_object_or_404(Category, slug=category_slug, is_active=True)
        # Показуємо товари самої категорії та її підкатегорій.
        products = products.filter(Q(category=category) | Q(category__parent=category))

    query = request.GET.get('q', '').strip()
    if query:
        products = products.filter(Q(name__icontains=query) | Q(description__icontains=query))

    paginator = Paginator(products, PRODUCTS_PER_PAGE)
    page = paginator.get_page(request.GET.get('page'))

    return render(
        request,
        'shop/product_list.html',
        {
            'categories': categories,
            'category': category,
            'page': page,
            'products': page.object_list,
            'query': query,
        },
    )


def product_detail(request, slug):
    """Детальна сторінка товару."""
    product = get_object_or_404(
        Product.objects.select_related('category').prefetch_related('images'),
        slug=slug,
        is_available=True,
    )

    related = Product.objects.filter(category=product.category, is_available=True).exclude(
        pk=product.pk
    )[:4]

    return render(
        request,
        'shop/product_detail.html',
        {
            'product': product,
            'related_products': related,
        },
    )

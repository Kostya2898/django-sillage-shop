"""Заповнює бренд і артикул наявним товарам.

Без цього кроку наступна міграція впала б: `sku` стає `unique=True`, а всі
наявні товари мають порожній рядок, і другий такий рядок уже конфліктує.
`brand` за тією ж логікою стає обовʼязковим лише після того, як усі товари
його отримають.

Класичний тристадійний патерн: послаблене поле → data-міграція
→ звуження.
"""

import uuid

from django.db import migrations
from django.utils.text import slugify

# Куди складаємо товари, які існували до появи брендів. Прибрати руками
# в адмінці після того, як seed_demo наповнить каталог SILLAGE (ROADMAP B2.7).
PLACEHOLDER_BRAND = {
    'name': 'Без бренду',
    'slug': 'bez-brendu',
    'country': '',
    'description': (
        'Технічний бренд для товарів, заведених до появи довідника брендів. '
        'Після наповнення каталогу SILLAGE його можна видалити.'
    ),
    'is_active': False,
    'sort_order': 999,
}


def _make_sku(name, taken):
    """Артикул виду SLG-KEDR-4F2A, гарантовано унікальний у межах прогону."""
    letters = ''.join(char for char in slugify(name) if char.isalnum())
    stem = (letters[:4] or 'PROD').upper()

    while True:
        candidate = f'SLG-{stem}-{uuid.uuid4().hex[:4].upper()}'
        if candidate not in taken:
            taken.add(candidate)
            return candidate


def backfill(apps, schema_editor):
    Brand = apps.get_model('shop', 'Brand')
    Product = apps.get_model('shop', 'Product')

    products = Product.objects.all()
    if not products.exists():
        return

    placeholder, _ = Brand.objects.get_or_create(
        slug=PLACEHOLDER_BRAND['slug'],
        defaults=PLACEHOLDER_BRAND,
    )

    Product.objects.filter(brand__isnull=True).update(brand=placeholder)

    taken = set(Product.objects.exclude(sku='').values_list('sku', flat=True))

    for product in Product.objects.filter(sku=''):
        product.sku = _make_sku(product.name, taken)
        # Slug міг лишитись порожнім у товарів, заведених до автогенерації.
        if not product.slug:
            product.slug = slugify(product.name) or f'product-{product.pk}'
        product.save(update_fields=['sku', 'slug'])


def unbackfill(apps, schema_editor):
    """Зворотний хід: чистимо артикули й прибираємо технічний бренд.

    Бренд знімаємо з товарів, бо після відкоту поле знову стане nullable.
    """
    Brand = apps.get_model('shop', 'Brand')
    Product = apps.get_model('shop', 'Product')

    placeholder = Brand.objects.filter(slug=PLACEHOLDER_BRAND['slug']).first()
    if placeholder:
        Product.objects.filter(brand=placeholder).update(brand=None)
        placeholder.delete()

    Product.objects.all().update(sku='')


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0002_catalog_expansion'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]

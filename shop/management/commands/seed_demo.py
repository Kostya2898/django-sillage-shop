"""Наповнює базу демонстраційними категоріями та товарами.

Запуск:  python manage.py seed_demo
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

from shop.models import Category, Product

CATEGORIES = [
    ('Електроніка', 'electronics', [
        ('Ноутбуки', 'laptops'),
        ('Смартфони', 'smartphones'),
    ]),
    ('Книги', 'books', []),
]

PRODUCTS = [
    # (назва, slug, категорія-slug, ціна, залишок)
    ('Ноутбук Lenovo IdeaPad 3', 'lenovo-ideapad-3', 'laptops', '21999.00', 7),
    ('Ноутбук ASUS VivoBook 15', 'asus-vivobook-15', 'laptops', '25499.50', 3),
    ('Смартфон Samsung Galaxy A55', 'samsung-galaxy-a55', 'smartphones', '15999.00', 12),
    ('Смартфон Xiaomi Redmi Note 13', 'xiaomi-redmi-note-13', 'smartphones', '8999.00', 0),
    ('Django для початківців', 'django-for-beginners', 'books', '750.00', 25),
    ('Чистий код', 'clean-code', 'books', '890.00', 4),
]


class Command(BaseCommand):
    help = 'Створює демонстраційні категорії та товари'

    def handle(self, *args, **options):
        slug_to_category = {}

        for name, slug, children in CATEGORIES:
            parent, _ = Category.objects.update_or_create(
                slug=slug,
                defaults={'name': name, 'parent': None, 'is_active': True},
            )
            slug_to_category[slug] = parent

            for child_name, child_slug in children:
                child, _ = Category.objects.update_or_create(
                    slug=child_slug,
                    defaults={'name': child_name, 'parent': parent, 'is_active': True},
                )
                slug_to_category[child_slug] = child

        for name, slug, category_slug, price, stock in PRODUCTS:
            Product.objects.update_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'category': slug_to_category[category_slug],
                    'description': f'Демонстраційний опис для товару «{name}».',
                    'price': Decimal(price),
                    'stock': stock,
                    'is_available': True,
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f'Готово: {Category.objects.count()} категорій, {Product.objects.count()} товарів.'
        ))

"""Наповнює базу демонстраційними категоріями, товарами та користувачем.

Запуск:  python manage.py seed_demo
         python manage.py seed_demo --no-user   (тільки каталог)

Каталог тут поки що з попереднього прикладу — заміна на 30 парфумів
із `data_plan.txt` запланована на етап B2.7 (`ROADMAP.md`).
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from shop.models import Category, Product

User = get_user_model()

DEMO_USER = {
    'username': 'demo',
    'email': 'demo@example.com',
    'phone': '+380670000000',
    'first_name': 'Демо',
    'last_name': 'Покупець',
    'is_subscribed': True,
}
DEMO_PASSWORD = 'demo-pass-12345'

CATEGORIES = [
    (
        'Електроніка',
        'electronics',
        [
            ('Ноутбуки', 'laptops'),
            ('Смартфони', 'smartphones'),
        ],
    ),
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
    help = 'Створює демонстраційні категорії, товари та користувача'

    def add_arguments(self, parser):
        parser.add_argument(
            '--no-user',
            action='store_true',
            help='Не створювати демонстраційного користувача',
        )

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

        if not options['no_user']:
            self._create_demo_user()

        self.stdout.write(
            self.style.SUCCESS(
                f'Готово: {Category.objects.count()} категорій, {Product.objects.count()} товарів.'
            )
        )

    def _create_demo_user(self):
        """Демонстраційний покупець із заповненим профілем.

        Профіль створює сигнал post_save, тож тут його лише доповнюємо —
        і заразом перевіряємо, що сигнал справді підключений.
        """
        user, created = User.objects.get_or_create(
            username=DEMO_USER['username'],
            defaults={key: value for key, value in DEMO_USER.items() if key != 'username'},
        )

        if created:
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=['password'])

        profile = user.profile
        profile.favourite_family = profile.FAMILY_WOODY
        profile.save(update_fields=['favourite_family', 'updated_at'])

        action = 'створено' if created else 'вже існує'
        self.stdout.write(f'Демо-користувач {user.username} / {DEMO_PASSWORD} — {action}.')

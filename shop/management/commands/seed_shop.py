"""Наповнення каталогу SILLAGE: категорії, бренди, ноти, товари, замовлення.

    python manage.py seed_shop --flush
    python manage.py seed_shop --products=5 --orders=0     # швидка ітерація
    python manage.py seed_shop                             # ідемпотентно, без дублікатів

Зображення ця команда не малює — для них є `render_product_images`.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from orders.models import Coupon, Order, OrderItem, OrderStatusHistory, ShippingAddress
from shop.models import Brand, Category, Note, Product, ProductImage, ProductNote, Review

from ._catalogue import BRANDS, CATEGORIES, NOTES
from ._products import PRODUCTS

User = get_user_model()

# Бренд-заглушка з data-міграції B3: він існував тільки щоб NOT NULL не впав
# на legacy-товарах. У каталозі парфумерії йому не місце — інакше «Без бренду»
# назавжди осяде у фільтрі брендів.
LEGACY_BRAND_SLUG = 'bez-brendu'

DEMO_USERS = [
    ('olena', 'Олена', 'Гриценко', 'olena@example.com', '+380671112233'),
    ('taras', 'Тарас', 'Мельник', 'taras@example.com', '+380672223344'),
    ('kateryna', 'Катерина', 'Бондар', 'kateryna@example.com', '+380673334455'),
    ('andrii', 'Андрій', 'Ковальчук', 'andrii@example.com', '+380674445566'),
    ('sofiia', 'Софія', 'Ткаченко', 'sofiia@example.com', '+380675556677'),
]

DEMO_PASSWORD = 'sillage-demo-2026'

CITIES = ['Київ', 'Львів', 'Одеса', 'Харків', 'Івано-Франківськ']

REVIEW_TEXTS = [
    (
        5,
        'Саме те, що шукала',
        'Носила тиждень поспіль і жодного разу не втомилася. '
        'Стійкість чесна, шлейф не душить сусідів у ліфті.',
    ),
    (
        5,
        'Дорого і не пафосно',
        'Рідкісний випадок, коли аромат звучить дорого, '
        'але не кричить про це. Купував наосліп і не пошкодував.',
    ),
    (
        4,
        'Гарний, але не на літо',
        'У прохолодну погоду ідеальний. У спеку важчає '
        'десь через годину — це не мінус, просто врахуйте.',
    ),
    (
        4,
        'Стійкість трохи менша за заявлену',
        'На шкірі тримається годин шість, ' 'не вісім. На светрі — значно довше. Аромат чудовий.',
    ),
    (5, 'Другий флакон', 'Перший скінчився за півроку, взяв одразу сто. ' 'Тут нема що додати.'),
    (
        3,
        'Не моє, але зроблено якісно',
        'Об\'єктивно хороша річ, просто не мій ' 'профіль. Віддав дружині, їй пасує більше.',
    ),
    (
        5,
        'Ідеально для роботи',
        'Помітний рівно настільки, наскільки треба в '
        'офісі. Ніхто не скаржився, кілька людей спитали, що це.',
    ),
    (
        4,
        'Гарний подарунок',
        'Брала в подарунок, разом із discovery-сетом. ' 'Упаковка гідна, вручати не соромно.',
    ),
    (
        5,
        'Той самий запах, що я памʼятаю',
        'Дуже нагадав аромат, який носив ' 'мій батько. Не думав, що таке ще роблять.',
    ),
    (
        4,
        'Красиво розкривається',
        'Перші пʼятнадцять хвилин зовсім інший аромат, '
        'ніж через годину. Раджу не робити висновків одразу.',
    ),
    (
        5,
        'Нарешті нормальна акватика',
        'Без «синьої свіжості» з реклами. ' 'Мінеральний, сухий, дорослий.',
    ),
    (
        2,
        'Занадто гучний для мене',
        'Шлейф величезний, у маленькій кімнаті ' 'забагато. Комусь це буде плюсом, мені — ні.',
    ),
    (
        5,
        'Купую втретє',
        'Уже традиція. Нічого не змінилось у формулі, і це '
        'найкраще, що можна сказати про парфум.',
    ),
    (
        4,
        'Добре тримається на одязі',
        'На шкірі середньо, на шарфі — два дні. ' 'Врахуйте при нанесенні.',
    ),
    (5, 'Найкраща покупка року', 'Довго вагалася через ціну. Тепер розумію, ' 'за що вона.'),
]


class Command(BaseCommand):
    help = 'Наповнює каталог SILLAGE: категорії, бренди, ноти, товари, замовлення'

    def add_arguments(self, parser):
        parser.add_argument(
            '--flush',
            action='store_true',
            help='Спочатку почистити каталог (разом із legacy-товарами і брендом-заглушкою)',
        )
        parser.add_argument(
            '--products',
            type=int,
            default=30,
            help='Скільки товарів створити (за замовчуванням 30)',
        )
        parser.add_argument(
            '--no-images',
            action='store_true',
            help='Не чіпати вже згенеровані зображення під час --flush',
        )
        parser.add_argument('--users', type=int, default=5, help='Скільки тестових покупців')
        parser.add_argument('--orders', type=int, default=10, help='Скільки замовлень')

    @transaction.atomic
    def handle(self, *args, **options):
        # Детермінованість: повторний запуск дає той самий каталог.
        self.random = random.Random('sillage')

        if options['flush']:
            self._flush(keep_images=options['no_images'])

        categories = self._seed_categories()
        brands = self._seed_brands()
        notes = self._seed_notes()
        products = self._seed_products(categories, brands, notes, limit=options['products'])

        self._seed_coupons()
        users = self._seed_users(options['users'])
        self._seed_orders(users, products, count=options['orders'])
        self._seed_reviews(users, products)

        self._drop_legacy_brand()
        self._report()

    # --- очищення --------------------------------------------------------

    def _flush(self, keep_images):
        """Знести каталог. Legacy-дані видаляються явно, а не «якось самі».

        Спершу замовлення й відгуки: `Product.category` має on_delete=PROTECT,
        а `OrderItem.product` — SET_NULL, тож порядок має значення.
        """
        OrderStatusHistory.objects.all().delete()
        OrderItem.objects.all().delete()
        Order.objects.all().delete()
        Review.objects.all().delete()

        if not keep_images:
            for image in ProductImage.objects.all():
                image.image.delete(save=False)
            ProductImage.objects.all().delete()

        ProductNote.objects.all().delete()
        Product.objects.all().delete()
        Note.objects.all().delete()

        # Категорії видаляємо від листя до кореня: parent має CASCADE, але
        # порядок робить намір явним.
        Category.objects.filter(parent__isnull=False).delete()
        Category.objects.all().delete()

        Brand.objects.all().delete()

        self.stdout.write('Каталог очищено (разом із legacy-товарами і брендом-заглушкою).')

    def _drop_legacy_brand(self):
        """Підстраховка на випадок запуску без --flush.

        Бренд-заглушку можна видалити, лише коли на ній не лишилось товарів:
        FK стоїть на PROTECT саме для того, щоб ми не знесли каталог мовчки.
        """
        legacy = Brand.objects.filter(slug=LEGACY_BRAND_SLUG).first()
        if legacy is None:
            return

        stranded = Product.objects.filter(brand=legacy)
        if stranded.exists():
            names = ', '.join(stranded.values_list('name', flat=True)[:5])
            stranded.delete()
            self.stdout.write(self.style.WARNING(f'Видалено legacy-товари: {names}'))

        legacy.delete()
        self.stdout.write(self.style.WARNING('Видалено бренд-заглушку «Без бренду».'))

    # --- довідники -------------------------------------------------------

    def _seed_categories(self):
        by_slug = {}

        for order, (slug, name, description, children) in enumerate(CATEGORIES, start=1):
            parent, _ = Category.objects.update_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'description': description,
                    'parent': None,
                    'sort_order': order * 10,
                    'is_featured': True,
                    'is_active': True,
                },
            )
            by_slug[slug] = parent

            for child_order, (child_slug, child_name) in enumerate(children, start=1):
                child, _ = Category.objects.update_or_create(
                    slug=child_slug,
                    defaults={
                        'name': child_name,
                        'parent': parent,
                        'sort_order': child_order * 10,
                        'is_active': True,
                    },
                )
                by_slug[child_slug] = child

        return by_slug

    def _seed_brands(self):
        by_slug = {}

        for order, (slug, name, country, founded, description) in enumerate(BRANDS, start=1):
            brand, _ = Brand.objects.update_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'country': country,
                    'founded_year': founded,
                    'description': description,
                    'sort_order': order * 10,
                    'is_active': True,
                },
            )
            by_slug[slug] = brand

        return by_slug

    def _seed_notes(self):
        by_name = {}

        for name, family in NOTES.items():
            note, _ = Note.objects.update_or_create(name=name, defaults={'family': family})
            by_name[name] = note

        return by_name

    # --- товари ----------------------------------------------------------

    def _seed_products(self, categories, brands, notes, limit):
        created = []

        for index, item in enumerate(PRODUCTS[:limit], start=1):
            product, _ = Product.objects.update_or_create(
                slug=item['slug'],
                defaults={
                    'name': item['name'],
                    'sku': f'SLG-{index:03d}',
                    'brand': brands[item['brand']],
                    'category': categories[item['category']],
                    'short_description': item['short'],
                    'description': item['description'],
                    'volume_ml': item.get('volume_ml'),
                    'concentration': item.get('concentration', ''),
                    'gender': item['gender'],
                    'longevity_hours': item.get('longevity_hours'),
                    'sillage': item.get('sillage', ''),
                    'year_released': item.get('year_released'),
                    'perfumer': item.get('perfumer', ''),
                    'country': item.get('country', ''),
                    'price': item['price'],
                    'old_price': item.get('old_price'),
                    'stock': item['stock'],
                    'is_available': True,
                    'is_featured': item.get('is_featured', False),
                    'is_new': item.get('is_new', False),
                    'views_count': self.random.randint(40, 900),
                    'sold_count': self.random.randint(0, 60),
                },
            )

            self._attach_notes(product, item.get('notes', {}), notes)
            created.append(product)

        return created

    def _attach_notes(self, product, layers, notes):
        """Піраміда нот. Перезбираємо повністю, щоб повторний сид не дублював."""
        ProductNote.objects.filter(product=product).delete()

        links = [
            ProductNote(
                product=product,
                note=notes[name],
                layer=layer,
                position=position,
            )
            for layer, names in layers.items()
            for position, name in enumerate(names)
        ]
        ProductNote.objects.bulk_create(links)

    # --- покупці, замовлення, відгуки ------------------------------------

    def _seed_coupons(self):
        """Демо-промокоди — по одному на кожну гілку перевірки.

        Прострочений і вичерпаний тут не для краси: саме на них видно, що
        магазин пояснює причину відмови, а не відповідає «код недійсний».
        """
        now = timezone.now()
        coupons = [
            {
                'code': 'SILLAGE10',
                'description': 'Знайомство: −10% на перше замовлення',
                'discount_type': Coupon.TYPE_PERCENT,
                'discount_value': Decimal('10.00'),
                'valid_from': now - timedelta(days=7),
                'valid_to': now + timedelta(days=90),
                'min_order_amount': Decimal('0.00'),
            },
            {
                'code': 'SLID500',
                'description': '−500 ₴ при замовленні від 4 000 ₴',
                'discount_type': Coupon.TYPE_FIXED,
                'discount_value': Decimal('500.00'),
                'valid_from': now - timedelta(days=7),
                'valid_to': now + timedelta(days=60),
                'min_order_amount': Decimal('4000.00'),
            },
            {
                'code': 'VESNA',
                'description': 'Прострочений — показує повідомлення про дату',
                'discount_type': Coupon.TYPE_PERCENT,
                'discount_value': Decimal('15.00'),
                'valid_from': now - timedelta(days=120),
                'valid_to': now - timedelta(days=30),
                'min_order_amount': Decimal('0.00'),
            },
            {
                'code': 'PERSHI50',
                'description': 'Вичерпаний ліміт — показує повідомлення про використання',
                'discount_type': Coupon.TYPE_PERCENT,
                'discount_value': Decimal('50.00'),
                'valid_from': now - timedelta(days=30),
                'valid_to': now + timedelta(days=30),
                'min_order_amount': Decimal('0.00'),
                'max_uses': 50,
                'used_count': 50,
            },
        ]

        for values in coupons:
            Coupon.objects.update_or_create(code=values['code'], defaults=values)

        self.stdout.write(f'Промокоди: {len(coupons)}')

    def _seed_users(self, count):
        users = []

        for username, first, last, email, phone in DEMO_USERS[:count]:
            user, created = User.objects.update_or_create(
                username=username,
                defaults={
                    'first_name': first,
                    'last_name': last,
                    'email': email,
                    'phone': phone,
                    'is_subscribed': self.random.choice([True, False]),
                },
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=['password'])

            ShippingAddress.objects.update_or_create(
                user=user,
                full_name=f'{first} {last}',
                defaults={
                    'phone': phone,
                    'country': 'Україна',
                    'city': self.random.choice(CITIES),
                    'postal_code': f'{self.random.randint(1, 99):02d}001',
                    'address_line1': f'вул. Прикладна, {self.random.randint(1, 90)}',
                    'is_default': True,
                },
            )
            users.append(user)

        return users

    def _seed_orders(self, users, products, count):
        """Замовлення в різних статусах — щоб адмінці й кабінету було що показати."""
        if not users or not products or count <= 0:
            return

        statuses = [
            Order.STATUS_PENDING,
            Order.STATUS_PAID,
            Order.STATUS_PAID,
            Order.STATUS_SHIPPED,
            Order.STATUS_SHIPPED,
            Order.STATUS_DELIVERED,
            Order.STATUS_DELIVERED,
            Order.STATUS_DELIVERED,
            Order.STATUS_CANCELLED,
            Order.STATUS_PENDING,
        ]
        buyable = [p for p in products if p.stock > 0] or products

        for index in range(count):
            user = users[index % len(users)]
            address = user.addresses.first()
            status = statuses[index % len(statuses)]
            number = f'ORD-SEED-{index + 1:04d}'

            if Order.objects.filter(order_number=number).exists():
                continue

            chosen = self.random.sample(buyable, k=min(self.random.randint(1, 3), len(buyable)))
            total = sum((p.price for p in chosen), Decimal('0.00'))

            order = Order.objects.create(
                order_number=number,
                user=user,
                shipping_full_name=address.full_name,
                shipping_phone=address.phone,
                shipping_country=address.country,
                shipping_city=address.city,
                shipping_postal_code=address.postal_code,
                shipping_address_line1=address.address_line1,
                total_amount=total,
                payment_method=self.random.choice(['card', 'cash', 'bank']),
                status=status,
            )
            # created_at має auto_now_add, тож розкидаємо дати окремим UPDATE.
            Order.objects.filter(pk=order.pk).update(
                created_at=timezone.now() - timedelta(days=self.random.randint(1, 120))
            )

            for product in chosen:
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    product_name=product.name,
                    price=product.price,
                    quantity=1,
                )

            OrderStatusHistory.objects.create(
                order=order, status=status, note='Створено сид-командою', created_by=user
            )

    def _seed_reviews(self, users, products):
        """Пʼятнадцять схвалених відгуків із різними оцінками."""
        if not users or not products:
            return

        for index, (rating, title, text) in enumerate(REVIEW_TEXTS):
            product = products[index % len(products)]
            user = users[index % len(users)]

            Review.objects.update_or_create(
                user=user,
                product=product,
                defaults={
                    'rating': rating,
                    'title': title,
                    'text': text,
                    'is_verified_purchase': self.random.choice([True, True, False]),
                    'is_approved': True,
                },
            )

    # --- підсумок --------------------------------------------------------

    def _report(self):
        rows = [
            ('Категорії', Category.objects.count()),
            ('Бренди', Brand.objects.count()),
            ('Ноти', Note.objects.count()),
            ('Товари', Product.objects.count()),
            ('  з них кураторський вибір', Product.objects.filter(is_featured=True).count()),
            ('  новинки', Product.objects.filter(is_new=True).count()),
            ('  зі знижкою', Product.objects.filter(old_price__isnull=False).count()),
            ('  немає на складі', Product.objects.filter(stock=0).count()),
            ('Покупці', User.objects.filter(is_superuser=False).count()),
            ('Замовлення', Order.objects.count()),
            ('Промокоди', Coupon.objects.count()),
            ('Відгуки', Review.objects.count()),
        ]

        for label, value in rows:
            self.stdout.write(f'{label:.<34} {value}')

        self.stdout.write(
            self.style.SUCCESS(f'\nГотово. Демо-покупці: логін olena…sofiia / {DEMO_PASSWORD}')
        )

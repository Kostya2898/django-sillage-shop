"""Моделі каталогу: бренди, категорії, товари, ольфакторні ноти, відгуки.

Модель проєктується під картку товару з `PROJECT_VISION.md`: не таблиця
характеристик, а історія аромату. Тому тут є парфумер, рік, стійкість,
шлейф і піраміда нот у трьох шарах — усе, що людина справді питає про
парфум, перш ніж купити.
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count, Prefetch, Q
from django.urls import reverse

from .utils import transliterate, unique_slug

# Максимальний розмір завантаженого зображення.
MAX_IMAGE_SIZE_MB = 5
MAX_IMAGE_SIZE = MAX_IMAGE_SIZE_MB * 1024 * 1024

IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']


def validate_image_size(value):
    """Не пускати у медіа файли, важчі за 5 МБ."""
    if value.size > MAX_IMAGE_SIZE:
        raise ValidationError(
            f'Файл завеликий: {value.size / 1024 / 1024:.1f} МБ. '
            f'Максимум — {MAX_IMAGE_SIZE_MB} МБ.'
        )


class Brand(models.Model):
    """Парфумерний дім. Усі бренди каталогу вигадані (див. `data_plan.txt`)."""

    name = models.CharField('Назва', max_length=150)
    slug = models.SlugField('Slug', max_length=160, unique=True, blank=True)
    country = models.CharField('Країна', max_length=100, blank=True)
    founded_year = models.PositiveSmallIntegerField(
        'Рік заснування',
        null=True,
        blank=True,
        validators=[MinValueValidator(1700), MaxValueValidator(2100)],
    )
    description = models.TextField('Опис', blank=True)
    logo = models.ImageField(
        'Логотип',
        upload_to='brands/%Y/%m',
        null=True,
        blank=True,
        validators=[FileExtensionValidator(IMAGE_EXTENSIONS), validate_image_size],
        help_text=f'{", ".join(IMAGE_EXTENSIONS).upper()}, до {MAX_IMAGE_SIZE_MB} МБ',
    )
    is_active = models.BooleanField('Активний', default=True)
    sort_order = models.PositiveSmallIntegerField('Порядок', default=100)
    created_at = models.DateTimeField('Створено', auto_now_add=True)

    class Meta:
        verbose_name = 'Бренд'
        verbose_name_plural = 'Бренди'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        # Окремого URL бренду ще немає — фільтр каталогу зʼявиться на етапі
        # B3.1 (ROADMAP.md). Параметр уже закладено, тож посилання не
        # доведеться переписувати.
        return f'{reverse("shop:product_list")}?brand={self.slug}'


class Category(models.Model):
    """Категорія товарів. Може мати батьківську категорію (дерево категорій)."""

    name = models.CharField('Назва', max_length=200)
    slug = models.SlugField('Slug', max_length=210, unique=True, blank=True)
    description = models.TextField('Опис', blank=True)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name='Батьківська категорія',
    )
    image = models.ImageField(
        'Зображення',
        upload_to='categories/%Y/%m',
        blank=True,
        validators=[FileExtensionValidator(IMAGE_EXTENSIONS), validate_image_size],
        help_text=f'{", ".join(IMAGE_EXTENSIONS).upper()}, до {MAX_IMAGE_SIZE_MB} МБ',
    )
    sort_order = models.PositiveSmallIntegerField('Порядок', default=100)
    is_featured = models.BooleanField('На головній', default=False)
    is_active = models.BooleanField('Активна', default=True)
    created_at = models.DateTimeField('Створено', auto_now_add=True)

    class Meta:
        verbose_name = 'Категорія'
        verbose_name_plural = 'Категорії'
        ordering = ['sort_order', 'name']

    def __str__(self):
        if self.parent_id:
            return f'{self.parent} → {self.name}'
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('shop:product_list_by_category', args=[self.slug])

    def get_children(self):
        """Прямі підкатегорії, тільки активні."""
        return self.children.filter(is_active=True)

    def get_descendants(self, include_self=False):
        """Уся гілка вниз — для фільтра «усі товари цієї категорії».

        Рекурсія, а не MPTT: категорій тринадцять, дерево на два рівні,
        і платити складністю пакета тут нема за що.
        """
        branch = [self] if include_self else []

        for child in self.get_children():
            branch.append(child)
            branch.extend(child.get_descendants())

        return branch

    def get_ancestors(self, include_self=False):
        """Шлях до кореня, від верхнього предка вниз — для хлібних крихт."""
        path = []
        node = self.parent

        while node is not None:
            path.append(node)
            node = node.parent

        path.reverse()

        if include_self:
            path.append(self)

        return path

    @property
    def product_count(self):
        """Скільки доступних товарів у цій категорії разом із підкатегоріями."""
        branch = self.get_descendants(include_self=True)
        return Product.objects.filter(category__in=branch, is_available=True).count()


class Note(models.Model):
    """Ольфакторна нота: бергамот, ірис, ветивер, амбра.

    Спільна для всіх товарів: одна й та сама троянда може бути в серці
    одного аромату і в базі іншого — за це відповідає `ProductNote`.
    """

    FAMILY_CITRUS = 'citrus'
    FAMILY_FLORAL = 'floral'
    FAMILY_WOODY = 'woody'
    FAMILY_SPICY = 'spicy'
    FAMILY_RESIN = 'resin'
    FAMILY_GOURMAND = 'gourmand'
    FAMILY_GREEN = 'green'
    FAMILY_AQUATIC = 'aquatic'
    FAMILY_ANIMALIC = 'animalic'

    FAMILY_CHOICES = [
        (FAMILY_CITRUS, 'Цитрусові'),
        (FAMILY_FLORAL, 'Квіткові'),
        (FAMILY_WOODY, 'Деревні'),
        (FAMILY_SPICY, 'Спеції'),
        (FAMILY_RESIN, 'Смоли'),
        (FAMILY_GOURMAND, 'Гурманські'),
        (FAMILY_GREEN, 'Зелені'),
        (FAMILY_AQUATIC, 'Акватичні'),
        (FAMILY_ANIMALIC, 'Тваринні'),
    ]

    name = models.CharField('Назва', max_length=100, unique=True)
    slug = models.SlugField('Slug', max_length=110, unique=True, blank=True)
    family = models.CharField('Родина', max_length=20, choices=FAMILY_CHOICES)
    description = models.TextField('Опис', blank=True)

    class Meta:
        verbose_name = 'Нота'
        verbose_name_plural = 'Ноти'
        ordering = ['family', 'name']
        indexes = [models.Index(fields=['family'])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        # Те саме, що й у Brand: фільтр за нотою — етап B3.1.
        return f'{reverse("shop:product_list")}?note={self.slug}'


class ProductNote(models.Model):
    """Нота в конкретному аромати: у якому шарі й на якому місці.

    Через цю модель будується піраміда: верхні ноти — перше враження,
    серце — основний характер, база — те, що лишається на шкірі.
    """

    LAYER_TOP = 'top'
    LAYER_HEART = 'heart'
    LAYER_BASE = 'base'

    LAYER_CHOICES = [
        (LAYER_TOP, 'Верхні'),
        (LAYER_HEART, 'Серце'),
        (LAYER_BASE, 'База'),
    ]

    product = models.ForeignKey(
        'Product',
        on_delete=models.CASCADE,
        related_name='product_notes',
        verbose_name='Товар',
    )
    note = models.ForeignKey(
        Note,
        on_delete=models.PROTECT,
        related_name='product_notes',
        verbose_name='Нота',
    )
    layer = models.CharField('Шар', max_length=10, choices=LAYER_CHOICES)
    position = models.PositiveSmallIntegerField('Порядок у шарі', default=0)

    class Meta:
        verbose_name = 'Нота товару'
        verbose_name_plural = 'Ноти товару'
        ordering = ['layer', 'position', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'note', 'layer'],
                name='unique_product_note_layer',
            ),
        ]

    def __str__(self):
        return f'{self.product} · {self.get_layer_display()}: {self.note}'


class ProductQuerySet(models.QuerySet):
    """Готові вибірки каталогу — щоб view не збирали їх щоразу вручну."""

    def available(self):
        """Товари, які взагалі можна показувати."""
        return self.filter(is_available=True)

    def in_stock(self):
        return self.available().filter(stock__gt=0)

    def featured(self):
        """«Кураторський вибір» — те, що йде на головну."""
        return self.available().filter(is_featured=True)

    def with_relations(self):
        """Бренд, категорія і головне фото — без N+1 на списку.

        Головне фото кладеться в `main_images`; зручніший доступ — через
        `Product.main_image`.
        """
        return self.select_related('brand', 'category').prefetch_related(
            Prefetch(
                'images',
                queryset=ProductImage.objects.filter(is_main=True),
                to_attr='main_images',
            )
        )

    def with_rating(self):
        """Додає `average_rating` і `reviews_count` як анотації.

        Свідомо не `@property`: властивість зробила б окремий запит на
        кожен товар списку. Рахуємо агрегатом у тому самому запиті —
        але й звертатись до цих атрибутів можна лише після виклику.
        """
        return self.annotate(
            average_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True)),
            reviews_count=Count('reviews', filter=Q(reviews__is_approved=True), distinct=True),
        )

    def with_notes(self):
        """Піраміда нот одним додатковим запитом."""
        return self.prefetch_related(
            Prefetch(
                'product_notes',
                queryset=ProductNote.objects.select_related('note'),
            )
        )


class Product(models.Model):
    """Товар магазину — переважно парфум, але також свічка, дифузор чи сет."""

    CONCENTRATION_EDC = 'edc'
    CONCENTRATION_EDT = 'edt'
    CONCENTRATION_EDP = 'edp'
    CONCENTRATION_EXTRAIT = 'extrait'
    CONCENTRATION_OIL = 'oil'

    CONCENTRATION_CHOICES = [
        (CONCENTRATION_EDC, 'Eau de Cologne'),
        (CONCENTRATION_EDT, 'Eau de Toilette'),
        (CONCENTRATION_EDP, 'Eau de Parfum'),
        (CONCENTRATION_EXTRAIT, 'Extrait de Parfum'),
        (CONCENTRATION_OIL, 'Олія'),
    ]

    GENDER_UNISEX = 'unisex'
    GENDER_FEMININE = 'feminine'
    GENDER_MASCULINE = 'masculine'

    GENDER_CHOICES = [
        (GENDER_UNISEX, 'Унісекс'),
        (GENDER_FEMININE, 'Жіночий'),
        (GENDER_MASCULINE, 'Чоловічий'),
    ]

    SILLAGE_INTIMATE = 'intimate'
    SILLAGE_MODERATE = 'moderate'
    SILLAGE_STRONG = 'strong'
    SILLAGE_ENORMOUS = 'enormous'

    SILLAGE_CHOICES = [
        (SILLAGE_INTIMATE, 'Камерний'),
        (SILLAGE_MODERATE, 'Помірний'),
        (SILLAGE_STRONG, 'Сильний'),
        (SILLAGE_ENORMOUS, 'Дуже сильний'),
    ]

    # --- Ідентифікація ---
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='products',
        verbose_name='Категорія',
    )
    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name='products',
        verbose_name='Бренд',
    )
    name = models.CharField('Назва', max_length=150)
    slug = models.SlugField('Slug', max_length=160, unique=True, blank=True)
    sku = models.CharField('Артикул', max_length=40, unique=True, blank=True)

    # --- Тексти ---
    short_description = models.CharField(
        'Короткий опис',
        max_length=300,
        blank=True,
        help_text='Два речення для картки в каталозі',
    )
    description = models.TextField('Опис', blank=True)

    # --- Характеристики аромату ---
    volume_ml = models.PositiveSmallIntegerField('Обʼєм, мл', null=True, blank=True)
    concentration = models.CharField(
        'Концентрація', max_length=10, choices=CONCENTRATION_CHOICES, blank=True
    )
    gender = models.CharField(
        'Для кого', max_length=10, choices=GENDER_CHOICES, default=GENDER_UNISEX
    )
    longevity_hours = models.PositiveSmallIntegerField(
        'Стійкість, годин',
        null=True,
        blank=True,
        validators=[MaxValueValidator(48)],
    )
    sillage = models.CharField('Шлейф', max_length=10, choices=SILLAGE_CHOICES, blank=True)
    year_released = models.PositiveSmallIntegerField(
        'Рік випуску',
        null=True,
        blank=True,
        validators=[MinValueValidator(1700), MaxValueValidator(2100)],
    )
    perfumer = models.CharField('Парфумер', max_length=150, blank=True)
    country = models.CharField('Країна виробництва', max_length=100, blank=True)
    notes = models.ManyToManyField(
        Note,
        through='ProductNote',
        related_name='products',
        verbose_name='Ноти',
        blank=True,
    )

    # --- Гроші й склад ---
    price = models.DecimalField('Ціна', max_digits=10, decimal_places=2)
    old_price = models.DecimalField(
        'Стара ціна',
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Заповніть, щоб показати знижку',
    )
    stock = models.PositiveIntegerField('Залишок на складі', default=0)
    is_available = models.BooleanField('Доступний', default=True)

    # --- Вітрина ---
    cover = models.ImageField(
        'Головне фото',
        upload_to='products/covers/%Y/%m',
        blank=True,
        validators=[FileExtensionValidator(IMAGE_EXTENSIONS), validate_image_size],
        help_text=f'{", ".join(IMAGE_EXTENSIONS).upper()}, до {MAX_IMAGE_SIZE_MB} МБ',
    )
    is_featured = models.BooleanField('Кураторський вибір', default=False)
    is_new = models.BooleanField('Новинка', default=False)
    views_count = models.PositiveIntegerField('Переглядів', default=0)
    sold_count = models.PositiveIntegerField('Продано', default=0)

    created_at = models.DateTimeField('Створено', auto_now_add=True)
    modified_at = models.DateTimeField('Змінено', auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товари'
        ordering = ['-is_featured', 'name']
        indexes = [
            models.Index(fields=['is_available', 'category']),
            models.Index(fields=['is_featured']),
            models.Index(fields=['price']),
        ]
        # Індекс на slug свідомо не додано: `unique=True` вже створює його,
        # а другий такий самий лише сповільнює запис (див. AUDIT.md, борг #16).

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        if not self.sku:
            self.sku = self._generate_sku()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('shop:product_detail', args=[self.slug])

    def _generate_sku(self):
        """Артикул виду SLG-KEDR-4F2A: читабельний і практично унікальний."""
        letters = ''.join(char for char in transliterate(self.name) if char.isalnum())
        stem = (letters[:4] or 'PROD').upper()
        return f'SLG-{stem}-{uuid.uuid4().hex[:4].upper()}'

    # --- Піраміда нот ---

    def _notes_of(self, layer):
        """Ноти одного шару. Працює з префетчем `with_notes()` без зайвих запитів."""
        return [link.note for link in self.product_notes.all() if link.layer == layer]

    @property
    def top_notes(self):
        return self._notes_of(ProductNote.LAYER_TOP)

    @property
    def heart_notes(self):
        return self._notes_of(ProductNote.LAYER_HEART)

    @property
    def base_notes(self):
        return self._notes_of(ProductNote.LAYER_BASE)

    # --- Гроші ---

    @staticmethod
    def _as_decimal(value):
        """Ціна може приїхати рядком (сид, імпорт прайсу) — не падаємо на цьому."""
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @property
    def has_discount(self):
        """Знижка є, лише якщо стара ціна справді більша за поточну."""
        old = self._as_decimal(self.old_price)
        return bool(old and old > self._as_decimal(self.price))

    @property
    def discount_percent(self):
        """Розмір знижки у відсотках, заокруглений донизу."""
        if not self.has_discount:
            return 0
        old = self._as_decimal(self.old_price)
        saved = (old - self._as_decimal(self.price)) / old * Decimal('100')
        return int(saved)

    # --- Наявність і вітрина ---

    @property
    def is_in_stock(self):
        """Чи можна взагалі купити цей товар просто зараз."""
        return self.is_available and self.stock > 0

    @property
    def main_image(self):
        """Головне фото: спершу `cover`, далі — позначене `is_main`.

        Після `with_relations()` бере готовий `main_images` і в базу не ходить.
        """
        if self.cover:
            return self.cover

        prefetched = getattr(self, 'main_images', None)
        if prefetched is not None:
            return prefetched[0].image if prefetched else None

        image = self.images.filter(is_main=True).first()
        return image.image if image else None


class ProductImage(models.Model):
    """Зображення товару. Товар може мати кілька фото; головне показуємо першим."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='Товар',
    )
    image = models.ImageField(
        'Зображення',
        upload_to='products/%Y/%m/%d',
        validators=[FileExtensionValidator(IMAGE_EXTENSIONS), validate_image_size],
        help_text=f'{", ".join(IMAGE_EXTENSIONS).upper()}, до {MAX_IMAGE_SIZE_MB} МБ',
    )
    alt_text = models.CharField(
        'Альтернативний текст',
        max_length=200,
        blank=True,
        help_text='Якщо не заповнити — підставиться назва товару',
    )
    is_main = models.BooleanField('Головне', default=False)
    sort_order = models.PositiveSmallIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Зображення товару'
        verbose_name_plural = 'Зображення товарів'
        ordering = ['-is_main', 'sort_order', 'id']
        constraints = [
            # Головне фото може бути тільки одне на товар — інакше шаблон
            # мовчки показував би випадкове з двох.
            models.UniqueConstraint(
                fields=['product'],
                condition=Q(is_main=True),
                name='one_main_image_per_product',
            ),
        ]

    def __str__(self):
        return f'Зображення для {self.product.name}'

    def save(self, *args, **kwargs):
        if not self.alt_text:
            self.alt_text = self.product.name
        super().save(*args, **kwargs)


class Review(models.Model):
    """Відгук покупця. Публікується лише після модерації."""

    RATING_MIN = 1
    RATING_MAX = 5

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name='Автор',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name='Товар',
    )
    rating = models.PositiveSmallIntegerField(
        'Оцінка',
        validators=[MinValueValidator(RATING_MIN), MaxValueValidator(RATING_MAX)],
    )
    title = models.CharField('Заголовок', max_length=200, blank=True)
    text = models.TextField('Текст відгуку')
    is_verified_purchase = models.BooleanField('Підтверджена покупка', default=False)
    is_approved = models.BooleanField(
        'Опубліковано',
        default=False,
        help_text='Відгук зʼявиться на сайті лише після перевірки',
    )
    created_at = models.DateTimeField('Створено', auto_now_add=True)
    updated_at = models.DateTimeField('Змінено', auto_now=True)

    class Meta:
        verbose_name = 'Відгук'
        verbose_name_plural = 'Відгуки'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'product'],
                name='one_review_per_user_per_product',
            ),
        ]
        indexes = [models.Index(fields=['product', 'is_approved'])]

    def __str__(self):
        return f'{self.product.name} — {self.rating}/{self.RATING_MAX} від {self.user}'

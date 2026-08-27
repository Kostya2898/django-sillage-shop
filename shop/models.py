"""Моделі каталогу: категорії, товари та їхні зображення."""

from django.db import models
from django.urls import reverse


class Category(models.Model):
    """Категорія товарів. Може мати батьківську категорію (дерево категорій)."""

    name = models.CharField('Назва', max_length=200)
    slug = models.SlugField('Slug', unique=True)
    description = models.TextField('Опис', blank=True)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name='Батьківська категорія',
    )
    is_active = models.BooleanField('Активна', default=True)
    created_at = models.DateTimeField('Створено', auto_now_add=True)

    class Meta:
        verbose_name = 'Категорія'
        verbose_name_plural = 'Категорії'
        ordering = ['name']

    def __str__(self):
        if self.parent_id:
            return f'{self.parent} → {self.name}'
        return self.name

    def get_absolute_url(self):
        return reverse('shop:product_list_by_category', args=[self.slug])


class Product(models.Model):
    """Товар магазину."""

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='products',
        verbose_name='Категорія',
    )
    name = models.CharField('Назва', max_length=150)
    slug = models.SlugField('Slug', unique=True)
    description = models.TextField('Опис', blank=True)
    price = models.DecimalField('Ціна', max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField('Залишок на складі', default=0)
    is_available = models.BooleanField('Доступний', default=True)
    created_at = models.DateTimeField('Створено', auto_now_add=True)
    modified_at = models.DateTimeField('Змінено', auto_now=True)

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товари'
        ordering = ['name']
        indexes = [models.Index(fields=['slug'])]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('shop:product_detail', args=[self.slug])

    @property
    def is_in_stock(self):
        """Чи можна взагалі купити цей товар просто зараз."""
        return self.is_available and self.stock > 0


class ProductImage(models.Model):
    """Зображення товару. Товар може мати кілька фото; головне показуємо першим."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='Товар',
    )
    image = models.ImageField('Зображення', upload_to='products/%Y/%m/%d')
    alt_text = models.CharField('Альтернативний текст', max_length=200, blank=True)
    is_main = models.BooleanField('Головне', default=False)

    class Meta:
        verbose_name = 'Зображення товару'
        verbose_name_plural = 'Зображення товарів'
        ordering = ['-is_main', 'id']

    def __str__(self):
        return f'Зображення для {self.product.name}'

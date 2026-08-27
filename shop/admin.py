"""Адмінка каталогу: бренди, категорії, товари з нотами, відгуки."""

from django.contrib import admin

from .models import Brand, Category, Note, Product, ProductImage, ProductNote, Review


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ['name', 'country', 'founded_year', 'is_active', 'product_count']
    list_filter = ['is_active', 'country']
    search_fields = ['name', 'country', 'description']
    prepopulated_fields = {'slug': ('name',)}

    @admin.display(description='Товарів')
    def product_count(self, obj):
        return obj.products.count()


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'parent', 'sort_order', 'is_featured', 'is_active', 'created_at']
    list_filter = ['is_active', 'is_featured', 'parent']
    list_editable = ['sort_order', 'is_featured']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ['name', 'family', 'used_in']
    list_filter = ['family']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}

    @admin.display(description='Ароматів')
    def used_in(self, obj):
        return obj.products.count()


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ['image', 'alt_text', 'is_main', 'sort_order']


class ProductNoteInline(admin.TabularInline):
    """Піраміда нот редагується разом із товаром."""

    model = ProductNote
    extra = 3
    autocomplete_fields = ['note']
    fields = ['note', 'layer', 'position']
    ordering = ['layer', 'position']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'brand',
        'category',
        'price',
        'stock',
        'is_available',
        'is_featured',
        'modified_at',
    ]
    list_filter = [
        'is_available',
        'is_featured',
        'is_new',
        'brand',
        'category',
        'concentration',
        'gender',
        'created_at',
    ]
    list_editable = ['price', 'stock', 'is_available', 'is_featured']
    list_select_related = ['brand', 'category']
    search_fields = ['name', 'sku', 'description', 'perfumer', 'brand__name']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['views_count', 'sold_count', 'created_at', 'modified_at']
    inlines = [ProductNoteInline, ProductImageInline]

    fieldsets = (
        (None, {'fields': ('name', 'slug', 'sku', 'brand', 'category')}),
        ('Тексти', {'fields': ('short_description', 'description')}),
        (
            'Аромат',
            {
                'fields': (
                    'volume_ml',
                    'concentration',
                    'gender',
                    'longevity_hours',
                    'sillage',
                    'year_released',
                    'perfumer',
                    'country',
                )
            },
        ),
        ('Гроші і склад', {'fields': ('price', 'old_price', 'stock', 'is_available')}),
        ('Вітрина', {'fields': ('cover', 'is_featured', 'is_new')}),
        ('Статистика', {'fields': ('views_count', 'sold_count', 'created_at', 'modified_at')}),
    )


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = [
        'product',
        'user',
        'rating',
        'is_verified_purchase',
        'is_approved',
        'created_at',
    ]
    list_filter = ['is_approved', 'is_verified_purchase', 'rating', 'created_at']
    list_editable = ['is_approved']
    list_select_related = ['product', 'user']
    search_fields = ['product__name', 'user__username', 'title', 'text']
    raw_id_fields = ['user', 'product']
    readonly_fields = ['created_at', 'updated_at']
    actions = ['approve', 'reject']

    @admin.action(description='Опублікувати відгуки')
    def approve(self, request, queryset):
        updated = queryset.filter(is_approved=False).update(is_approved=True)
        self.message_user(request, f'Опубліковано відгуків: {updated}')

    @admin.action(description='Зняти з публікації')
    def reject(self, request, queryset):
        updated = queryset.filter(is_approved=True).update(is_approved=False)
        self.message_user(request, f'Знято з публікації: {updated}')

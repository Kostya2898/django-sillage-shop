from django.contrib import admin

from .models import Cart, CartItem


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    raw_id_fields = ['product']


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ['cart_code', 'user', 'paid_status', 'created_at', 'modified_at']
    list_filter = ['paid_status', 'created_at']
    search_fields = ['cart_code', 'user__username']
    inlines = [CartItemInline]

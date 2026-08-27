from django.contrib import admin

from .models import Transaction


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['reference', 'order', 'user', 'amount', 'currency', 'status', 'created_at']
    list_filter = ['status', 'currency', 'created_at']
    search_fields = ['reference', 'gateway_transaction_id', 'order__order_number', 'user__username']
    readonly_fields = ['created_at', 'updated_at']

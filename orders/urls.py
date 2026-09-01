from django.urls import path

from . import views

app_name = 'orders'

urlpatterns = [
    path('checkout/', views.checkout, name='checkout'),
    path('checkout/identity/', views.checkout_identity, name='checkout_identity'),
    path('checkout/confirm/', views.checkout_confirm, name='checkout_confirm'),
    path('coupon/apply/', views.coupon_apply, name='coupon_apply'),
    path('coupon/remove/', views.coupon_remove, name='coupon_remove'),
    path('success/<str:order_number>/', views.order_success, name='order_success'),
    path('', views.order_list, name='order_list'),
    # Дії над замовленням — до загального `<order_number>/`, інакше
    # «cancel» і «invoice» ловились би як номери замовлень.
    path('<str:order_number>/cancel/', views.order_cancel, name='order_cancel'),
    path('<str:order_number>/invoice/', views.order_invoice, name='order_invoice'),
    path('<str:order_number>/', views.order_detail, name='order_detail'),
]

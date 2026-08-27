from django.urls import path

from . import views

app_name = 'payments'

urlpatterns = [
    path('pay/<str:order_number>/', views.initiate_payment, name='initiate_payment'),
    path('gateway/<str:tx_ref>/', views.mock_gateway, name='mock_gateway'),
    path('callback/', views.payment_callback, name='payment_callback'),
]

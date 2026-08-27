"""Кореневий URLconf проекту shop_project."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('cart/', include('cart.urls')),
    path('orders/', include('orders.urls')),
    path('payments/', include('payments.urls')),
    path('', include('shop.urls')),
]

if settings.DEBUG:
    # У режимі розробки Django сам віддає завантажені зображення товарів.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

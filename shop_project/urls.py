"""Кореневий URLconf проекту shop_project."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

# Брендування панелі керування. Стандартна адмінка Django з нормальними
# заголовками виглядає гідно — сторонні теми (jazzmin, grappelli) додали б
# ризик і залежність без реального виграшу.
admin.site.site_header = 'SILLAGE · панель керування'
admin.site.site_title = 'SILLAGE'
admin.site.index_title = 'Каталог, замовлення та клієнти'

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

    # Debug Toolbar підключається лише коли він справді в INSTALLED_APPS —
    # у prod-налаштуваннях застосунку немає, і цей блок мовчки не спрацює.
    if 'debug_toolbar' in settings.INSTALLED_APPS:
        urlpatterns += [path('__debug__/', include('debug_toolbar.urls'))]

elif settings.SERVE_MEDIA:
    # Свідомий компроміс для навчального деплою. З DEBUG=False Django медіа не
    # віддає, а WhiteNoise обслуговує лише статику, зібрану на збірці, — фото
    # товарів, завантажені через адмінку, стали б 404. Правильно — окреме
    # сховище (S3, R2) або nginx перед gunicorn; для проєкту без них це
    # єдиний спосіб показати каталог із фото. `serve` сам захищений від
    # виходу за MEDIA_ROOT (`../`).
    urlpatterns += [
        re_path(
            rf'^{settings.MEDIA_URL.strip("/")}/(?P<path>.*)$',
            serve,
            {'document_root': settings.MEDIA_ROOT},
        ),
    ]

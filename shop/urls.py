from django.urls import path

from . import views

app_name = 'shop'

urlpatterns = [
    path('', views.home, name='home'),
    path('catalogue/', views.product_list, name='product_list'),
    path('catalogue/search/', views.product_search, name='product_search'),
    path(
        'catalogue/<slug:category_slug>/',
        views.product_list,
        name='product_list_by_category',
    ),
    path('product/<slug:slug>/', views.product_detail, name='product_detail'),
    # Службові сторінки фотоконвеєра. Самі view відповідають 404 поза DEBUG,
    # тож маршрути можна лишити зареєстрованими завжди — `{% url %}` у
    # шаблонах не падає, а сторінка на проді недоступна.
    path('photo-sources/', views.photo_sources, name='photo_sources'),
    path('photo-sources/<int:image_id>/reject/', views.photo_reject, name='photo_reject'),
]

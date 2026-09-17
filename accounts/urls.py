from django.contrib.auth import views as auth_views
from django.urls import path
from django_ratelimit.decorators import ratelimit

from shop_project.ratelimit import LIMITS

from . import views

app_name = 'accounts'

urlpatterns = [
    path(
        'login/',
        ratelimit(
            group='accounts:login',
            key='ip',
            rate=LIMITS['accounts:login'].rate,
            method='POST',
            block=True,
        )(auth_views.LoginView.as_view(template_name='accounts/login.html')),
        name='login',
    ),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('signup/', views.signup, name='signup'),
    path('profile/', views.profile, name='profile'),
]

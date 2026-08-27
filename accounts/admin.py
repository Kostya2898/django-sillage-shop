"""Адмінка користувачів: CustomUser із профілем як inline."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import CustomUser, UserProfile


class UserProfileInline(admin.StackedInline):
    """Профіль редагується на тій самій сторінці, що й користувач."""

    model = UserProfile
    can_delete = False
    verbose_name = 'Профіль'
    verbose_name_plural = 'Профіль'
    fk_name = 'user'
    readonly_fields = ['created_at', 'updated_at']


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """Стандартна адмінка користувача плюс поля магазину."""

    inlines = [UserProfileInline]

    list_display = [
        'username',
        'email',
        'phone',
        'is_subscribed',
        'is_staff',
        'is_active',
        'created_at',
    ]
    list_filter = ['is_subscribed', 'is_staff', 'is_superuser', 'is_active', 'created_at']
    search_fields = ['username', 'email', 'phone', 'first_name', 'last_name']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'last_login', 'date_joined']

    # Копіюємо структуру UserAdmin і вставляємо свої поля в «Особисті дані».
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Особисті дані', {'fields': ('first_name', 'last_name', 'email', 'phone')}),
        ('Магазин', {'fields': ('is_subscribed',)}),
        (
            'Права доступу',
            {
                'fields': (
                    'is_active',
                    'is_staff',
                    'is_superuser',
                    'groups',
                    'user_permissions',
                ),
            },
        ),
        ('Важливі дати', {'fields': ('last_login', 'date_joined', 'created_at')}),
    )

    # Форма створення користувача в адмінці: email обов'язковий і унікальний,
    # тому просимо його одразу, а не після збереження.
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('username', 'email', 'phone', 'password1', 'password2'),
            },
        ),
    )

    @admin.display(description='Профіль заповнено', boolean=True)
    def has_filled_profile(self, obj):
        profile = getattr(obj, 'profile', None)
        return bool(profile and (profile.date_of_birth or profile.favourite_family))


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Окремий список профілів — зручно шукати за ольфакторною родиною."""

    list_display = ['user', 'favourite_family', 'date_of_birth', 'updated_at']
    list_filter = ['favourite_family']
    search_fields = ['user__username', 'user__email', 'user__phone']
    raw_id_fields = ['user']
    readonly_fields = ['created_at', 'updated_at']

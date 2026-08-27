"""Користувач магазину та його профіль.

Розділення свідоме і відповідає вимозі уроку:

* `CustomUser` — те, без чого не працює сам магазин: логін, email для листів,
  телефон для кур'єра, згода на розсилку. Ці поля читає бекенд.
* `UserProfile` — те, що наповнює кабінет: дата народження, аватар, улюблена
  ольфакторна родина, адреса за замовчуванням. Створюється сигналом
  `post_save` (`accounts/signals.py`), тож існує для кожного користувача.

`USERNAME_FIELD` лишається `username` — на email-логін навмисно не переходимо,
щоб не переписувати наявні форми й шаблони.
"""

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    """Користувач магазину.

    Успадковує все від `AbstractUser` і додає поля, потрібні для покупок.
    `email` тут — обов'язковий і унікальний: на нього йдуть листи про
    замовлення, і без унікальності відновлення пароля стає неоднозначним.
    """

    email = models.EmailField('Email', unique=True)
    phone = models.CharField('Телефон', max_length=20, blank=True)
    is_subscribed = models.BooleanField(
        'Підписка на розсилку',
        default=False,
        help_text='Листи про нові аромати й закриті передпродажі',
    )
    created_at = models.DateTimeField('Зареєстрований', auto_now_add=True)

    class Meta:
        verbose_name = 'Користувач'
        verbose_name_plural = 'Користувачі'
        ordering = ['-created_at']

    def __str__(self):
        return self.username

    def get_display_name(self):
        """Ім'я для вітання в кабінеті: справжнє, якщо є, інакше логін."""
        full_name = self.get_full_name().strip()
        return full_name or self.username


class UserProfile(models.Model):
    """Додаткові дані користувача, які показує кабінет."""

    FAMILY_WOODY = 'woody'
    FAMILY_FLORAL = 'floral'
    FAMILY_AMBER = 'amber'
    FAMILY_CITRUS = 'citrus'
    FAMILY_GOURMAND = 'gourmand'
    FAMILY_LEATHER = 'leather'
    FAMILY_AQUATIC = 'aquatic'

    FAMILY_CHOICES = [
        (FAMILY_WOODY, 'Деревні'),
        (FAMILY_FLORAL, 'Квіткові'),
        (FAMILY_AMBER, 'Амброві'),
        (FAMILY_CITRUS, 'Цитрусові'),
        (FAMILY_GOURMAND, 'Гурманські'),
        (FAMILY_LEATHER, 'Шкіра і тютюн'),
        (FAMILY_AQUATIC, 'Акватичні'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='Користувач',
    )
    date_of_birth = models.DateField('Дата народження', null=True, blank=True)
    avatar = models.ImageField('Аватар', upload_to='avatars/%Y/%m', blank=True)
    favourite_family = models.CharField(
        'Улюблена ольфакторна родина',
        max_length=20,
        choices=FAMILY_CHOICES,
        blank=True,
        help_text='За нею кабінет підбирає рекомендації',
    )
    default_shipping_address = models.ForeignKey(
        'orders.ShippingAddress',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Адреса за замовчуванням',
    )
    created_at = models.DateTimeField('Створено', auto_now_add=True)
    updated_at = models.DateTimeField('Змінено', auto_now=True)

    class Meta:
        verbose_name = 'Профіль користувача'
        verbose_name_plural = 'Профілі користувачів'

    def __str__(self):
        return f'Профіль {self.user.username}'

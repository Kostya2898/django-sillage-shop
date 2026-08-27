"""Профіль користувача — додаткові поля поверх вбудованої моделі User."""

from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='Користувач',
    )
    phone = models.CharField('Телефон', max_length=20, blank=True)
    date_of_birth = models.DateField('Дата народження', null=True, blank=True)

    class Meta:
        verbose_name = 'Профіль користувача'
        verbose_name_plural = 'Профілі користувачів'

    def __str__(self):
        return f'Профіль {self.user.username}'

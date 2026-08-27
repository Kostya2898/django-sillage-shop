from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'accounts'
    verbose_name = 'Користувачі'

    def ready(self):
        # Підключаємо обробники сигналів (створення профілю, злиття кошиків).
        from . import signals  # noqa: F401

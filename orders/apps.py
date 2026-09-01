from django.apps import AppConfig


class OrdersConfig(AppConfig):
    name = 'orders'
    verbose_name = 'Замовлення'

    def ready(self):
        # Історія статусів і листи про зміну статусу.
        from . import signals  # noqa: F401

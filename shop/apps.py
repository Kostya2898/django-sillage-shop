from django.apps import AppConfig


class ShopConfig(AppConfig):
    name = 'shop'
    verbose_name = 'Каталог'

    def ready(self):
        # Підключаємо скидання кешу фасетів при зміні каталогу.
        from . import signals  # noqa: F401

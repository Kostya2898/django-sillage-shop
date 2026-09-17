"""Сигнали каталогу: скидання кешу фасетів."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Brand, Category, Note, Product
from .services import invalidate_facets, invalidate_navigation_tree


@receiver(post_save, sender=Brand)
@receiver(post_save, sender=Category)
@receiver(post_save, sender=Note)
@receiver(post_save, sender=Product)
@receiver(post_delete, sender=Brand)
@receiver(post_delete, sender=Category)
@receiver(post_delete, sender=Note)
@receiver(post_delete, sender=Product)
def reset_catalogue_facets(sender, **kwargs):
    """Фасети містять лічильники товарів, тож застарівають від будь-якої зміни.

    Дешевше скинути кеш і перерахувати раз, ніж показувати «Деревні (12)»,
    коли їх насправді одинадцять. Те саме стосується дерева мега-меню: воно
    теж із лічильниками і теж застаріває від будь-якої зміни каталогу.
    """
    invalidate_facets()
    invalidate_navigation_tree()

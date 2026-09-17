"""Сигнали каталогу: скидання кешу при будь-якій зміні каталогу."""

from django.db.models.signals import post_delete, post_save

from .cache import invalidate_catalog_cache
from .models import Brand, Category, Note, Product, Review

# `Review` тут через головну: картки кураторського вибору показують середню
# оцінку, і новий відгук інакше з'явився б там лише через TTL.
CATALOG_MODELS = (Brand, Category, Note, Product, Review)


def reset_catalog_cache(sender, **kwargs):
    """Лічильники у фасетах і меню, рейтинг на головній застарівають від
    будь-якої зміни. Дешевше перерахувати раз, ніж показувати «Деревні (12)»,
    коли їх насправді одинадцять.
    """
    invalidate_catalog_cache()


for model in CATALOG_MODELS:
    for signal in (post_save, post_delete):
        signal.connect(
            reset_catalog_cache,
            sender=model,
            dispatch_uid=f'shop:reset-catalog-cache:{signal is post_save}:{model.__name__}',
        )

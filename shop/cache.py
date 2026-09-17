"""Кеш каталогу: іменовані ключі й одна точка інвалідації.

Ключі зібрані тут, а не розкидані по `services.py`, з однієї причини:
інвалідація мусить знати **всі** ключі каталогу. Коли ключ оголошений поруч
зі своїм білдером, новий кеш додають, а скинути забувають — і на головній
годину висить товар, якого вже немає.

Стратегія — «скинути все»: будь-яка зміна категорії, бренду, товару, ноти чи
відгуку видаляє всі ключі разом. Дешевше перерахувати чотири запити раз, ніж
відстежувати, яка зміна зачіпає який блок, і помилитися в лічильнику.
"""

from django.core.cache import cache

# Страховка, а не основний механізм: свіжість забезпечують сигнали. TTL
# ловить те, повз що сигнали проходять, — `QuerySet.update()` (так списується
# склад у `create_order`) `post_save` не шле.
CATALOG_CACHE_TIMEOUT = 60 * 15

NAVIGATION_TREE_KEY = 'shop:navigation-tree'
FACETS_KEY = 'shop:catalogue-facets'
BRANDS_KEY = 'shop:brands'
HOME_FEATURED_KEY = 'shop:home-featured'

CATALOG_CACHE_KEYS = (
    NAVIGATION_TREE_KEY,
    FACETS_KEY,
    BRANDS_KEY,
    HOME_FEATURED_KEY,
)


def invalidate_catalog_cache():
    """Скинути весь кеш каталогу одним запитом до сховища."""
    cache.delete_many(CATALOG_CACHE_KEYS)

"""Дерево навігації в кожному шаблоні.

Шапка з мега-меню є на кожній сторінці сайту, тож дерево має бути в контексті
завжди — інакше кожен view мусив би його додавати, і перший забутий дав би
порожнє меню на випадковій сторінці.

`SimpleLazyObject` тут не косметика: адмінка, службові сторінки й ендпоінти,
що віддають JSON, шапку не рендерять, і рахувати для них дерево — марна
робота. Ліниве значення обчислюється лише тоді, коли шаблон справді до нього
звернувся. Той самий приймач уже застосований до кошика
(`cart/context_processors.py`).
"""

from django.conf import settings
from django.utils.functional import SimpleLazyObject

from .services import get_navigation_tree

# Шляхи, на яких меню не потрібне. Префікси, а не точні адреси: під /admin/
# лежить ціле дерево сторінок.
IGNORED_PREFIXES = ('/admin/', settings.STATIC_URL, settings.MEDIA_URL)


def navigation(request):
    """Дерево категорій для мега-меню й підвалу."""
    if any(request.path.startswith(prefix) for prefix in IGNORED_PREFIXES if prefix):
        return {}

    return {'nav_tree': SimpleLazyObject(get_navigation_tree)}

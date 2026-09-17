"""Кореневий URLconf збирається по-різному залежно від налаштувань.

Ці гілки не бачить жоден інший тест: прогін іде без Debug Toolbar і з
DEBUG=False. Саме так пройшла помилка, коли блок Debug Toolbar опинився
всередині гілки `SERVE_MEDIA` — у розробці кожна сторінка віддавала 500
(«'djdt' is not a registered namespace»), а 551 тест лишались зеленими.
"""

import importlib

from django.test import SimpleTestCase, override_settings
from django.urls import URLResolver, clear_url_caches

import shop_project.urls


def build_urlconf():
    """Перечитати urls.py з поточними налаштуваннями."""
    module = importlib.reload(shop_project.urls)
    clear_url_caches()
    return URLResolver(r'^/', module)


def media_routes(resolver):
    return [p for p in resolver.url_patterns if 'media' in str(p.pattern)]


class RootUrlconfTests(SimpleTestCase):
    def tearDown(self):
        # Повернути модуль до стану під налаштуваннями прогону.
        importlib.reload(shop_project.urls)
        clear_url_caches()

    @override_settings(DEBUG=True, SERVE_MEDIA=False)
    def test_debug_registers_toolbar_namespace_when_toolbar_installed(self):
        with self.modify_settings(INSTALLED_APPS={'append': 'debug_toolbar'}):
            resolver = build_urlconf()

        self.assertIn('djdt', resolver.namespace_dict)
        self.assertTrue(media_routes(resolver))

    @override_settings(DEBUG=False, SERVE_MEDIA=True)
    def test_serve_media_without_debug_adds_media_route_only(self):
        with self.modify_settings(INSTALLED_APPS={'append': 'debug_toolbar'}):
            resolver = build_urlconf()

        self.assertTrue(media_routes(resolver))
        self.assertNotIn('djdt', resolver.namespace_dict)

    @override_settings(DEBUG=False, SERVE_MEDIA=False)
    def test_production_default_serves_no_media_through_django(self):
        resolver = build_urlconf()

        self.assertEqual(media_routes(resolver), [])

"""Ліміти частоти запитів: перевищення дає 429 із поясненням, а не 500.

У решті прогону ліміти вимкнені (`RATELIMIT_ENABLE` у dev.py), бо лічильники
живуть у кеші, спільному для всіх тестів. Тут їх вмикаємо явно, а кеш
чистимо з обох боків, щоб чужі запити не з'їли ліміт і наші не лишились
у кеші після тесту.
"""

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from shop_project.ratelimit import LIMITS, client_ip


@override_settings(RATELIMIT_ENABLE=True)
class RateLimitedEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_sixth_login_attempt_gets_429_with_human_message(self):
        url = reverse('accounts:login')
        payload = {'username': 'nobody', 'password': 'wrong-password'}

        for attempt in range(5):
            response = self.client.post(url, payload)
            self.assertEqual(response.status_code, 200, f'спроба {attempt + 1}')

        response = self.client.post(url, payload)

        self.assertEqual(response.status_code, 429)
        self.assertTemplateUsed(response, '429.html')
        self.assertContains(response, 'Забагато спроб входу', status_code=429)
        self.assertEqual(response['Retry-After'], str(LIMITS['accounts:login'].retry_after))

    def test_login_page_itself_is_not_limited(self):
        """Ліміт рахує лише POST: відкрити форму можна скільки завгодно."""
        url = reverse('accounts:login')

        for _ in range(10):
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_live_search_over_limit_answers_json_not_html(self):
        url = reverse('shop:product_search')
        headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}

        for _ in range(30):
            self.assertEqual(self.client.get(url, {'q': 'ір'}, **headers).status_code, 200)

        response = self.client.get(url, {'q': 'ір'}, **headers)

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertFalse(response.json()['ok'])
        self.assertIn('пошукових запитів', response.json()['error'])


class ClientIpTests(SimpleTestCase):
    """На кого рахується ліміт — і чи можна його обійти підробленим заголовком."""

    def setUp(self):
        self.request = RequestFactory().get(
            '/',
            REMOTE_ADDR='10.0.0.1',
            HTTP_X_FORWARDED_FOR='6.6.6.6, 203.0.113.7',
        )

    @override_settings(RATELIMIT_TRUST_PROXY=False)
    def test_without_proxy_forwarded_header_is_ignored(self):
        self.assertEqual(client_ip(self.request), '10.0.0.1')

    @override_settings(RATELIMIT_TRUST_PROXY=True)
    def test_behind_proxy_takes_address_appended_by_proxy(self):
        """Перша адреса — від клієнта, її можна вписати будь-яку."""
        self.assertEqual(client_ip(self.request), '203.0.113.7')

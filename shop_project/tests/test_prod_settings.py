"""Production-налаштування відмовляються стартувати з небезпечним оточенням.

Налаштування імпортуються один раз на процес, тому кожен випадок
перевіряється окремим інтерпретатором із власним оточенням. Порожня змінна
передається явно: `.env` читається через `setdefault` і вже заданої змінної
не перебиває — інакше локальний `.env` тихо підставив би свій ключ і тест
перевіряв би не те.
"""

import os
import subprocess
import sys

from django.conf import settings
from django.core.management.utils import get_random_secret_key
from django.test import SimpleTestCase

IMPORT_PROD = (
    'import shop_project.settings.prod as s; '
    'print(s.DEBUG, s.SECURE_REFERRER_POLICY, s.SECURE_PROXY_SSL_HEADER[0])'
)


def import_prod(**overrides):
    environment = {**os.environ, **overrides}
    environment.pop('DJANGO_SETTINGS_MODULE', None)
    return subprocess.run(
        [sys.executable, '-c', IMPORT_PROD],
        cwd=settings.BASE_DIR,
        env=environment,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=60,
    )


class ProdSettingsGuardTests(SimpleTestCase):
    def setUp(self):
        self.good = {
            'SECRET_KEY': get_random_secret_key(),
            'ALLOWED_HOSTS': 'sillage.example.com',
            'PYTHONIOENCODING': 'utf-8',
        }

    def assertRefuses(self, result, fragment):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('ImproperlyConfigured', result.stderr)
        self.assertIn(fragment, result.stderr)

    def test_valid_environment_starts_with_debug_off(self):
        result = import_prod(**self.good)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ['False', 'same-origin', 'HTTP_X_FORWARDED_PROTO'])

    def test_empty_secret_key_refuses_to_start(self):
        self.assertRefuses(import_prod(**{**self.good, 'SECRET_KEY': ''}), 'SECRET_KEY')

    def test_development_key_refuses_to_start(self):
        result = import_prod(**{**self.good, 'SECRET_KEY': 'dev-only-insecure-key-change-me'})
        self.assertRefuses(result, 'SECRET_KEY')

    def test_short_key_refuses_to_start(self):
        self.assertRefuses(import_prod(**{**self.good, 'SECRET_KEY': 'x' * 49}), 'SECRET_KEY')

    def test_empty_allowed_hosts_refuses_to_start(self):
        self.assertRefuses(import_prod(**{**self.good, 'ALLOWED_HOSTS': ''}), 'ALLOWED_HOSTS')

    def test_debug_cannot_be_switched_on_from_environment(self):
        result = import_prod(**{**self.good, 'DEBUG': 'True'})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split()[0], 'False')

"""Перевірки, які стосуються всіх шаблонів одразу.

Ці тести не про конкретну сторінку, а про клас помилок: такі баги не ловляться
переглядом однієї сторінки, бо ламають ту, на яку ніхто не дивився.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TEMPLATE_DIR = Path(settings.BASE_DIR) / 'templates'


def all_templates():
    return sorted(TEMPLATE_DIR.rglob('*.html'))


class CommentSyntaxTests(SimpleTestCase):
    """`{# ... #}` не вміє переноситись на наступний рядок.

    Лексер Django шукає `{#.*?#}` без DOTALL, тож коментар, розтягнутий на два
    рядки, просто не розпізнається як коментар — і його текст їде користувачу
    у верстку. Помилка тиха: сторінка віддається зі статусом 200, шаблон
    компілюється, і видно її лише очима на конкретному екрані.

    Для багаторядкових пояснень існує `{% comment %}`.
    """

    def test_no_multiline_hash_comments(self):
        offenders = []

        for path in all_templates():
            source = path.read_text(encoding='utf-8')
            for match in re.finditer(r'\{#', source):
                end_of_line = source.find('\n', match.start())
                if end_of_line == -1:
                    end_of_line = len(source)
                if '#}' not in source[match.start() : end_of_line]:
                    line = source[: match.start()].count('\n') + 1
                    offenders.append(f'{path.relative_to(TEMPLATE_DIR)}:{line}')

        self.assertEqual(
            offenders,
            [],
            'Багаторядковий {# #} рендериться як звичайний текст. '
            f'Замініть на {{% comment %}}: {offenders}',
        )

    def test_no_unclosed_comment_tags(self):
        for path in all_templates():
            source = path.read_text(encoding='utf-8')
            with self.subTest(template=str(path.relative_to(TEMPLATE_DIR))):
                self.assertEqual(
                    source.count('{% comment %}'),
                    source.count('{% endcomment %}'),
                    'Незакритий {% comment %}',
                )


class CsrfTokenTests(SimpleTestCase):
    """Кожна POST-форма має нести CSRF-токен.

    Вимога курсу і базова гігієна: форма без токена віддає 403 у проді й
    мовчки працює в тестах, де CSRF вимкнено.
    """

    FORM_RE = re.compile(r'<form\b[^>]*>.*?</form>', re.DOTALL | re.IGNORECASE)
    METHOD_POST_RE = re.compile(r'method\s*=\s*["\']post["\']', re.IGNORECASE)

    def test_every_post_form_has_csrf_token(self):
        offenders = []

        for path in all_templates():
            source = path.read_text(encoding='utf-8')
            for form in self.FORM_RE.findall(source):
                if self.METHOD_POST_RE.search(form) and 'csrf_token' not in form:
                    offenders.append(str(path.relative_to(TEMPLATE_DIR)))

        self.assertEqual(offenders, [], f'POST-форма без {{% csrf_token %}}: {offenders}')


class IconTests(SimpleTestCase):
    """Іконки — SVG, а не емодзі (конвенція проєкту)."""

    EMOJI_RE = re.compile(
        '[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]',
        re.UNICODE,
    )

    def test_no_emoji_in_templates(self):
        offenders = []

        for path in all_templates():
            source = path.read_text(encoding='utf-8')
            found = self.EMOJI_RE.findall(source)
            if found:
                offenders.append(f'{path.relative_to(TEMPLATE_DIR)}: {"".join(found)}')

        self.assertEqual(offenders, [], f'Емодзі замість SVG-іконок: {offenders}')

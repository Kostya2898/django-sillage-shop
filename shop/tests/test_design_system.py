"""Дизайн-система: правила, які легко зламати непомітно.

Кожен тест тут закриває помилку, яку неможливо побачити на одній сторінці, бо
вона виявляється на тій сторінці, куди ніхто не дивився. Захардкоджений HEX у
компоненті не ламає нічого **сьогодні** — він ламає наступну зміну палітри, і
тоді шукати доведеться по всіх файлах.

Числа контрасту тут не вписані руками. Вони рахуються з `tokens.css`, тому
тест не може розійтися з палітрою: він або читає справжній колір, або падає.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from shop.design_tokens import MIN_LARGE, MIN_TEXT, contrast_ratio, palette_report, read_tokens
from testing import ShopTestCase

CSS_DIR = Path(settings.BASE_DIR) / 'static' / 'css'
TEMPLATES_DIR = Path(settings.BASE_DIR) / 'templates'

# `tokens.css` — єдиний файл, де HEX дозволений: це шар первинних значень.
TOKENS_FILE = CSS_DIR / 'tokens.css'


def css_files(exclude_tokens=True):
    files = sorted(CSS_DIR.rglob('*.css'))
    if exclude_tokens:
        files = [f for f in files if f != TOKENS_FILE]
    return files


def without_comments(source):
    """CSS без коментарів.

    Перша версія різала лише по `/*` у тому самому рядку — і тест падав на
    коментарі «`border-radius: 16px` на всьому — ознака шаблонного SaaS»,
    тобто на тексті, який якраз забороняє те, що тест шукає.
    """
    return re.sub(r'/\*.*?\*/', '', source, flags=re.DOTALL)


def code_lines(path):
    """Пронумеровані рядки файлу без коментарів."""
    return list(enumerate(without_comments(path.read_text(encoding='utf-8')).splitlines(), 1))


class TokenDisciplineTests(SimpleTestCase):
    """HEX живе лише в шарі токенів."""

    HEX_RE = re.compile(r'#[0-9a-fA-F]{3,8}\b')

    def test_components_have_no_hardcoded_hex(self):
        """Компонент, який знає колір, неможливо перефарбувати темою."""
        offenders = []

        for path in css_files():
            for number, line in code_lines(path):
                if self.HEX_RE.search(line):
                    offenders.append(f'{path.name}:{number}: {line.strip()}')

        self.assertEqual(
            offenders,
            [],
            'HEX поза tokens.css — компонент перестає підкорятися палітрі: ' f'{offenders}',
        )

    def test_no_pure_black_or_white_anywhere(self):
        """Ані `#000`, ані `#FFF` — ні в токенах, ні в компонентах.

        Виняток рівно один: `rgba(255,255,255,.07)` — верхня внутрішня грань
        скла. Це не колір, а світло на межі матеріалу, і воно напівпрозоре.
        """
        banned = re.compile(r'#(000|fff|000000|ffffff)\b', re.IGNORECASE)
        offenders = []

        for path in css_files(exclude_tokens=False):
            for number, line in code_lines(path):
                if banned.search(line):
                    offenders.append(f'{path.name}:{number}')

        self.assertEqual(offenders, [], f'Чистий чорний або білий: {offenders}')

    def test_opaque_white_is_never_used_as_a_colour(self):
        """`rgb(255,255,255)` без прозорості — той самий чистий білий."""
        opaque = re.compile(r'rgba?\(\s*255\s*,\s*255\s*,\s*255\s*(?:,\s*1(?:\.0+)?\s*)?\)')
        offenders = []

        for path in css_files(exclude_tokens=False):
            if opaque.search(without_comments(path.read_text(encoding='utf-8'))):
                offenders.append(path.name)

        self.assertEqual(offenders, [], f'Непрозорий білий: {offenders}')


class ContrastTests(SimpleTestCase):
    """Контраст — числами, а не на око."""

    def test_body_text_pairs_pass_aa(self):
        failures = []

        for row in palette_report():
            # Вимкнені стани WCAG з перевірки виключає, і троянда на рамках
            # працює за порогом великого тексту.
            if row['fg_token'] in {'ash-dim', 'rose'}:
                continue
            if not row['passes_text']:
                failures.append(f'{row["label"]} — {row["ratio"]}:1')

        self.assertEqual(failures, [], f'Текстові пари мають тягнути {MIN_TEXT}:1 — {failures}')

    def test_ash_on_smola_specifically(self):
        """Пара, названа в ТЗ окремо: попелястий на смолі."""
        tokens = read_tokens()
        ratio = contrast_ratio(tokens['ash'], tokens['smola'])

        self.assertGreaterEqual(
            ratio,
            MIN_TEXT,
            f'Попіл #9C93A6 на смолі #16131B дає {ratio:.2f}:1',
        )

    def test_large_text_pairs_pass_three_to_one(self):
        for row in palette_report():
            with self.subTest(pair=row['label']):
                self.assertGreaterEqual(row['ratio'], MIN_LARGE)

    def test_accent_button_text_is_readable(self):
        """Нуар на латуні — текст головної кнопки."""
        tokens = read_tokens()
        ratio = contrast_ratio(tokens['noir'], tokens['brass'])

        self.assertGreaterEqual(ratio, MIN_TEXT)


class MotionContractTests(SimpleTestCase):
    """Моушн-контракт: криві, тривалості, заборонені прийоми."""

    def setUp(self):
        self.tokens = TOKENS_FILE.read_text(encoding='utf-8')
        self.all_css = '\n'.join(
            without_comments(p.read_text(encoding='utf-8')) for p in css_files(False)
        )

    def test_both_curves_are_declared(self):
        self.assertIn('cubic-bezier(0.22, 1, 0.36, 1)', self.tokens)
        self.assertIn('cubic-bezier(0.65, 0, 0.35, 1)', self.tokens)

    def test_default_ease_is_not_used(self):
        """Дефолтний `ease` ні на що не налаштований, тож не використовується."""
        offenders = []

        for path in css_files(exclude_tokens=False):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                code = line.split('/*')[0]
                # Шукаємо `ease` як окреме слово в transition/animation.
                if re.search(r'\b(transition|animation)[^;]*\bease\b(?!-)', code):
                    offenders.append(f'{path.name}:{number}')

        self.assertEqual(offenders, [], f'Дефолтний ease: {offenders}')

    def test_nothing_lasts_longer_than_900ms(self):
        """Ліміт 900 мс стосується переходів, а не нескінченних циклів.

        Skeleton, спінер і демонстрація кривих на стайлгайді крутяться
        безкінечно: там тривалість — це період, а не час, який хтось чекає.
        Тому з перевірки виключаються оголошення з `infinite`.
        """
        too_long = []

        for path in css_files(exclude_tokens=False):
            source = without_comments(path.read_text(encoding='utf-8'))
            for declaration in re.findall(r'(?:transition|animation)[^;{}]*;', source):
                if 'infinite' in declaration:
                    continue
                for value in re.findall(r'(\d{3,5})ms', declaration):
                    if int(value) > 900:
                        too_long.append(f'{path.name}: {value}ms')

        self.assertEqual(too_long, [], f'Перехід довший за 900 мс: {too_long}')

    def test_no_spring_curves(self):
        """Пружні криві з перельотом заборонені.

        Переліт лічильника кошика зроблений keyframes-ом на 1.06, а не
        пружною кривою, саме щоб він був єдиним і обмеженим.
        """
        banned = ['back.out', 'elastic', 'cubic-bezier(0.68, -0.55']
        for token in banned:
            with self.subTest(curve=token):
                self.assertNotIn(token, self.all_css)

    def test_cart_bump_overshoot_is_within_six_percent(self):
        match = re.search(r'@keyframes bump \{(.+?)\}\s*\n', self.all_css, re.DOTALL)
        self.assertIsNotNone(match, 'Немає keyframes bump')

        scales = [float(value) for value in re.findall(r'scale\(([\d.]+)\)', match.group(1))]
        self.assertLessEqual(max(scales), 1.06, 'Переліт лічильника більший за 6%')

    def test_reduced_motion_is_handled(self):
        for path in [CSS_DIR / 'tokens.css', CSS_DIR / 'base.css']:
            with self.subTest(file=path.name):
                self.assertIn('prefers-reduced-motion', path.read_text(encoding='utf-8'))

    def test_reduced_motion_keeps_composition(self):
        """Без руху сторінка має бути завершеною, а не порожньою.

        Тобто в блоці `reduce` мусить стояти повернення прозорості й
        трансформу в кінцевий стан, а не просто `animation: none`.
        """
        base = (CSS_DIR / 'base.css').read_text(encoding='utf-8')
        # Блоків кілька (scroll-behavior, рух, зерно) — цікавить той, що
        # повертає елементи у видимий стан, тож перевіряємо їх усі разом.
        blocks = base.split('@media (prefers-reduced-motion: reduce)')[1:]
        joined = '\n'.join(blocks)

        self.assertIn('opacity: 1', joined)
        self.assertIn('transform: none', joined)


class GeometryTests(SimpleTestCase):
    """Кути й тач-цілі."""

    def test_no_large_border_radius(self):
        """Скруглення 12 px і більше — ознака шаблонного SaaS."""
        offenders = []

        for path in css_files(exclude_tokens=False):
            for number, line in code_lines(path):
                for value in re.findall(r'border-radius:\s*([\d.]+)px', line):
                    if float(value) >= 12:
                        offenders.append(f'{path.name}:{number} → {value}px')

        self.assertEqual(offenders, [], f'Завелике скруглення: {offenders}')

    def test_tap_target_token_is_44(self):
        self.assertIn('--tap-min: 44px', TOKENS_FILE.read_text(encoding='utf-8'))

    def test_interactive_components_use_the_tap_token(self):
        """Кожен інтерактивний компонент спирається на мінімальну тач-ціль."""
        components = (CSS_DIR / 'components.css').read_text(encoding='utf-8')

        for selector in ['.btn {', '.chip {', '.pagination__link {', '.stepper__btn {']:
            with self.subTest(component=selector):
                block = components.split(selector)[1].split('}')[0]
                self.assertIn('var(--tap-min)', block, f'{selector} без тач-цілі 44px')


class TemplateDisciplineTests(SimpleTestCase):
    """Шаблони: без інлайн-стилів і без HEX."""

    # PDF-рахунок — обґрунтований виняток, і єдиний.
    #
    # `xhtml2pdf` не читає зовнішні стилі й не знає `var(--…)`: у нього немає
    # каскаду й немає користувацьких властивостей. Рахунок або має стилі
    # всередині документа, або не має стилів узагалі. Це не послаблення
    # правила, а межа рушія — і саме тому виняток названий тут явно, а не
    # прихований пом'якшеною перевіркою.
    # Шаблони, які рендерить не браузер:
    #   `orders/invoice.html` — xhtml2pdf;
    #   `orders/emails/*`     — поштові клієнти.
    # Обидва не читають зовнішні стилі й не знають `var(--…)`: у них немає
    # ані каскаду, ані користувацьких властивостей. Лист із <style> приїжджає
    # голим HTML, бо Outlook вирізає його цілком. Тому інлайн там — умова
    # роботи, а не послаблення правила, і виняток названий явно.
    ENGINE_TEMPLATES = ('orders/invoice.html',)
    ENGINE_PREFIXES = ('orders/emails/',)

    @classmethod
    def rendered_elsewhere(cls, path):
        name = path.relative_to(TEMPLATES_DIR).as_posix()
        return name in cls.ENGINE_TEMPLATES or name.startswith(cls.ENGINE_PREFIXES)

    def test_no_inline_styles(self):
        """Значення в атрибуті неможливо перевизначити темою."""
        offenders = []

        for path in TEMPLATES_DIR.rglob('*.html'):
            if self.rendered_elsewhere(path):
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if re.search(r'\sstyle\s*=\s*["\']', line):
                    offenders.append(f'{path.relative_to(TEMPLATES_DIR)}:{number}')

        self.assertEqual(offenders, [], f'Інлайн-стилі: {offenders}')

    def test_no_hex_in_templates(self):
        offenders = []
        hex_re = re.compile(r'(?<![\w&])#[0-9a-fA-F]{6}\b')

        for path in TEMPLATES_DIR.rglob('*.html'):
            if self.rendered_elsewhere(path):
                continue

            source = path.read_text(encoding='utf-8')
            # `{% comment %}` — пояснення, не застосування.
            source = re.sub(
                r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', '', source, flags=re.DOTALL
            )
            source = re.sub(r'\{#.*?#\}', '', source)

            # `<code>#0A090C</code>` на стайлгайді — це текст про колір,
            # а не колір. Прибираємо вміст <code> перед перевіркою.
            source = re.sub(r'<code>.*?</code>', '', source, flags=re.DOTALL)

            # `theme-color` — другий виняток межі рушія, і теж названий явно.
            # Цей колір читає не сторінка, а хром браузера: смужку навколо
            # вікна він фарбує **до** того, як існує хоч один стиль, тому
            # `var(--bg-page)` там не існує в принципі. Щоб дублікат не
            # розʼїхався з токеном, його пінить окремий тест нижче.
            source = re.sub(r'<meta\s+name="theme-color"[^>]*>', '', source)

            for number, line in enumerate(source.splitlines(), 1):
                if hex_re.search(line):
                    offenders.append(f'{path.relative_to(TEMPLATES_DIR)}:{number}')

        self.assertEqual(offenders, [], f'HEX у шаблоні: {offenders}')

    def test_theme_color_matches_page_background(self):
        """Смужка браузера і тло сторінки — один колір, інакше видно шов.

        Це єдине місце, де значення з токенів продубльоване вручну, тож
        тест звіряє дублікат із джерелом: якщо `--bg-page` колись поїде,
        падає тут, а не в чужому телефоні.
        """
        base = (TEMPLATES_DIR / 'base.html').read_text(encoding='utf-8')
        declared = re.search(r'name="theme-color"\s+content="(#[0-9a-fA-F]{6})"', base)
        self.assertIsNotNone(declared, 'Немає meta theme-color')

        tokens = TOKENS_FILE.read_text(encoding='utf-8')
        # `--bg-page: var(--noir)` → сам `--noir` уже HEX.
        alias = re.search(r'--bg-page:\s*var\((--[\w-]+)\)', tokens)
        self.assertIsNotNone(alias, 'Немає токена --bg-page')
        primitive = re.search(rf'{alias.group(1)}:\s*(#[0-9a-fA-F]{{6}})', tokens)
        self.assertIsNotNone(primitive, f'Не знайдено HEX для {alias.group(1)}')

        self.assertEqual(declared.group(1).lower(), primitive.group(1).lower())

    def test_film_layer_is_included_once(self):
        base = (TEMPLATES_DIR / 'base.html').read_text(encoding='utf-8')

        self.assertIn("partials/_film.html", base)
        self.assertEqual(base.count("partials/_film.html"), 1)

    def test_css_load_order_is_fixed(self):
        """tokens → base → components. Порядок не переставляється."""
        base = (TEMPLATES_DIR / 'base.html').read_text(encoding='utf-8')

        positions = [
            base.index('css/tokens.css'),
            base.index('css/base.css'),
            base.index('css/components.css'),
        ]
        self.assertEqual(positions, sorted(positions), 'Порядок підключення CSS зламано')


class StyleguidePageTests(ShopTestCase):
    """Стайлгайд: у DEBUG відкритий, поза ним — 404."""

    @override_settings(DEBUG=True)
    def test_page_opens_in_debug(self):
        response = self.client.get(reverse('shop:styleguide'))

        self.assertEqual(response.status_code, 200)

    def test_page_is_hidden_without_debug(self):
        response = self.client.get(reverse('shop:styleguide'))

        self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=True)
    def test_page_shows_real_contrast_numbers(self):
        response = self.client.get(reverse('shop:styleguide'))

        # Саме виміряне число, а не «перевірено».
        self.assertContains(response, '6.24')
        self.assertContains(response, '16.47')

    @override_settings(DEBUG=True)
    def test_page_shows_every_component_state(self):
        response = self.client.get(reverse('shop:styleguide'))
        body = response.content.decode()

        for component in [
            'btn--primary',
            'btn--ghost',
            'btn--quiet',
            'is-loading',
            'field__error',
            'chip',
            'tag--sale',
            'card-product',
            'breadcrumbs',
            'pagination',
            'drawer',
            'toast',
            'skeleton',
            'stepper',
            'rating',
            'accordion',
            'modal',
            'empty',
        ]:
            with self.subTest(component=component):
                self.assertIn(component, body)

    @override_settings(DEBUG=True)
    def test_page_shows_both_curves(self):
        response = self.client.get(reverse('shop:styleguide'))
        body = response.content.decode()

        self.assertIn('--ease-out', body)
        self.assertIn('--ease-in-out', body)

"""Читання палітри з `tokens.css` і розрахунок контрастів.

Навіщо читати CSS із Python: щоб число контрасту на стайлгайді не було
вписане руками. Вписане руками воно перестає відповідати кольору вже після
першої правки палітри — і сторінка починає брехати саме там, де має
доводити.

Формула — WCAG 2.1: відносна яскравість із гамма-корекцією, потім
(L_світліший + 0.05) / (L_темніший + 0.05).
"""

import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings

TOKENS_FILE = Path(settings.BASE_DIR) / 'static' / 'css' / 'tokens.css'

# Пари «текст на тлі», які мають бути перевірені. Саме ці комбінації
# зустрічаються в інтерфейсі; решта — похідні від них.
CHECKED_PAIRS = [
    ('bone', 'noir', 'Кістка на Нуарі', 'основний текст'),
    ('bone', 'smola', 'Кістка на Смолі', 'основний текст'),
    ('ash', 'noir', 'Попіл на Нуарі', 'другорядний текст'),
    ('ash', 'smola', 'Попіл на Смолі', 'другорядний текст'),
    ('brass', 'noir', 'Латунь на Нуарі', 'ціна, акцент'),
    ('brass', 'smola', 'Латунь на Смолі', 'ціна, акцент'),
    ('rose-text', 'smola', 'Троянда (текст) на Смолі', 'помилка'),
    ('rose', 'smola', 'Троянда на Смолі', 'рамка, знижка'),
    ('noir', 'brass', 'Нуар на Латуні', 'текст кнопки'),
    ('ash-dim', 'smola', 'Попіл тьмяний на Смолі', 'вимкнений стан'),
]

# Мінімуми WCAG AA.
MIN_TEXT = 4.5
MIN_LARGE = 3.0


def _relative_luminance(hex_colour):
    value = hex_colour.lstrip('#')
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground, background):
    light = _relative_luminance(foreground)
    dark = _relative_luminance(background)
    if light < dark:
        light, dark = dark, light
    return (light + 0.05) / (dark + 0.05)


@lru_cache(maxsize=1)
def read_tokens():
    """Первинні кольори з `tokens.css` — єдине місце, де вони оголошені."""
    source = TOKENS_FILE.read_text(encoding='utf-8')
    return dict(re.findall(r'--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})', source))


def palette_report():
    """Перевірені пари з реальними числами — для стайлгайду і для тестів."""
    tokens = read_tokens()
    rows = []

    for fg, bg, label, role in CHECKED_PAIRS:
        if fg not in tokens or bg not in tokens:
            continue

        ratio = contrast_ratio(tokens[fg], tokens[bg])
        rows.append(
            {
                'label': label,
                'role': role,
                'fg': tokens[fg],
                'bg': tokens[bg],
                'fg_token': fg,
                'bg_token': bg,
                'ratio': round(ratio, 2),
                # Окремо рядком: українська локаль форматує float із комою
                # («6,24»), а контраст — технічна величина, і в ній крапка.
                'ratio_text': f'{ratio:.2f}',
                'passes_text': ratio >= MIN_TEXT,
                'passes_large': ratio >= MIN_LARGE,
            }
        )

    return rows

"""Допоміжні функції каталогу: транслітерація та унікальні slug-и.

Чому власна таблиця, а не `unidecode`
------------------------------------
`unidecode` транслітерує кирилицю за російськими правилами: «и» → `i`,
«г» → `g`. Для української це неправильно і, головне, розходиться з тим,
що вже зафіксовано в `data_plan.txt`: там «Кедрова тиша» має slug
`kedrova-tysha`, а `unidecode` дав би `kedrova-tisha`.

Тут — офіційна українська транслітерація (постанова КМУ №55 від 2010):
«и» → `y`, «г» → `h`, «х» → `kh`, «ц» → `ts`, «щ» → `shch`. Для «є», «ї»,
«й», «ю», «я» правило залежить від позиції: на початку слова `ye`, `yi`,
`y`, `yu`, `ya`, усередині — `ie`, `i`, `i`, `iu`, `ia`.

Бонусом — нуль нових залежностей.
"""

import re

from django.utils.text import slugify

# Літери, які на початку слова читаються інакше, ніж усередині.
POSITIONAL = {
    'є': ('ye', 'ie'),
    'ї': ('yi', 'i'),
    'й': ('y', 'i'),
    'ю': ('yu', 'iu'),
    'я': ('ya', 'ia'),
}

SIMPLE = {
    'а': 'a',
    'б': 'b',
    'в': 'v',
    'г': 'h',
    'ґ': 'g',
    'д': 'd',
    'е': 'e',
    'ж': 'zh',
    'з': 'z',
    'и': 'y',
    'і': 'i',
    'к': 'k',
    'л': 'l',
    'м': 'm',
    'н': 'n',
    'о': 'o',
    'п': 'p',
    'р': 'r',
    'с': 's',
    'т': 't',
    'у': 'u',
    'ф': 'f',
    'х': 'kh',
    'ц': 'ts',
    'ч': 'ch',
    'ш': 'sh',
    'щ': 'shch',
    'ь': '',
    "'": '',
    'ʼ': '',
    '’': '',
    # Російські літери — на випадок, якщо назва приїде з чужого прайсу.
    'ё': 'e',
    'ы': 'y',
    'э': 'e',
    'ъ': '',
}

WORD_BOUNDARY = re.compile(r'[^\w\']', re.UNICODE)


def transliterate(value):
    """Українська кирилиця → латиниця за правилами КМУ №55.

    >>> transliterate('Амброве серце')
    'Ambrove sertse'
    >>> transliterate('Кедрова тиша')
    'Kedrova tysha'
    """
    if not value:
        return ''

    result = []
    at_word_start = True

    for char in value:
        lower = char.lower()
        is_upper = char.isupper()

        if lower in POSITIONAL:
            initial, inner = POSITIONAL[lower]
            piece = initial if at_word_start else inner
        elif lower in SIMPLE:
            piece = SIMPLE[lower]
        else:
            piece = char

        if is_upper and piece:
            piece = piece.capitalize()

        result.append(piece)
        # Наступна літера починає слово, якщо поточний символ — роздільник.
        at_word_start = bool(WORD_BOUNDARY.match(char))

    return ''.join(result)


def ukrainian_slugify(value):
    """Slug з української назви.

    `slugify` сам по собі викидає кирилицю і повертає порожній рядок,
    тому спершу транслітеруємо.

    >>> ukrainian_slugify('Амброве серце')
    'ambrove-sertse'
    """
    return slugify(transliterate(value))


def unique_slug(instance, value, field_name='slug', max_length=None):
    """Slug, унікальний у межах моделі: `name`, `name-2`, `name-3`…

    Обʼєкт із тим самим pk не вважається конфліктом — інакше повторне
    збереження щоразу нарощувало б суфікс.
    """
    model = instance.__class__
    base = ukrainian_slugify(value) or 'item'

    if max_length is None:
        max_length = model._meta.get_field(field_name).max_length or 50

    base = base[:max_length]
    candidate = base
    suffix = 2

    while True:
        taken = model.objects.filter(**{field_name: candidate})
        if instance.pk:
            taken = taken.exclude(pk=instance.pk)

        if not taken.exists():
            return candidate

        tail = f'-{suffix}'
        candidate = f'{base[: max_length - len(tail)]}{tail}'
        suffix += 1

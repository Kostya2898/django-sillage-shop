"""Забраковані вручну зображення.

Робочий цикл такий: дивлюсь контактний лист → бачу кадр, що випадає → додаю
сюди його хеш або адресу → `--only=slug --force` бере **наступного**
кандидата, а не того самого.

Саме тому список живе в коді, а не в базі: він переживає `seed_shop --flush`
і потрапляє в git разом із рішенням, чому цей кадр не підійшов.

Хеші — це dHash 8×8 з `_photos.dhash()`; його друкує `--dry-run` і показує
сторінка `/photo-sources/`.
"""

# Адреси, з яких більше не брати. Ключ — точний URL, значення — причина.
REJECTED_URLS = {}

# Перцептивні хеші забракованих кадрів. Ключ — dHash, значення — причина.
# Ловить те саме зображення, навіть якщо воно приїде з іншої адреси.
REJECTED_HASHES = {}


def is_rejected_url(url):
    return url in REJECTED_URLS


def is_rejected_hash(value, threshold=10):
    """Чи збігається хеш із раніше забракованим.

    Поріг той самий, що й у дедуплікації: перекодований JPEG того самого
    кадру дає інші біти, але близький хеш.
    """
    return any(bin(value ^ known).count('1') <= threshold for known in REJECTED_HASHES)


def reason_for(url=None, value=None):
    """Пояснення, чому кадр забракували, — для звіту команди."""
    if url and url in REJECTED_URLS:
        return REJECTED_URLS[url]

    if value is not None:
        for known, reason in REJECTED_HASHES.items():
            if bin(value ^ known).count('1') <= 10:
                return reason

    return 'забраковано вручну'


def add_rejection(value, url='', reason='забраковано вручну'):
    """Дописати забракований кадр у цей самий файл.

    Так, функція перезаписує власний модуль. Це свідомо і працює лише в DEBUG
    (єдиний викликач — dev-сторінка `/photo-sources/`): рішення «цей кадр
    нікуди» має потрапити в git разом із причиною, а не лишитись у базі, яку
    зносить `seed_shop --flush`.

    Формат файлу навмисно простий, тож перезапис — це друк двох словників, а не
    правка тексту регуляркою.
    """
    from pathlib import Path

    if url:
        REJECTED_URLS[url] = reason
    REJECTED_HASHES[int(value)] = reason

    path = Path(__file__)
    source = path.read_text(encoding='utf-8')
    head = source.split('# Адреси, з яких більше не брати.', 1)[0]
    tail = source.split('def is_rejected_url(url):', 1)[1]

    lines = [
        head,
        '# Адреси, з яких більше не брати. Ключ — точний URL, значення — причина.',
        'REJECTED_URLS = {',
        *(f'    {key!r}: {text!r},' for key, text in sorted(REJECTED_URLS.items())),
        '}',
        '',
        '# Перцептивні хеші забракованих кадрів. Ключ — dHash, значення — причина.',
        '# Ловить те саме зображення, навіть якщо воно приїде з іншої адреси.',
        'REJECTED_HASHES = {',
        *(f'    0x{key:016x}: {text!r},' for key, text in sorted(REJECTED_HASHES.items())),
        '}',
        '',
        '',
        'def is_rejected_url(url):' + tail,
    ]
    path.write_text('\n'.join(lines), encoding='utf-8')

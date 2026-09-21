"""Зведення різних знімків до вигляду однієї зйомки.

Суть модуля в одному реченні: тридцять фотографій із тридцяти різних джерел
мають вийти звідси так, наче їх зняли за одну зміну, одним світлом, на одному
фоні. Без цього каталог виглядає як маркетплейс, і жодна верстка не рятує —
око бачить різнобій експозиції раніше, ніж читає назву товару.

Порядок кроків не довільний, він від грубого до тонкого:

1. **кроп 4:5 з центруванням на предметі** — спершу вирішуємо, що в кадрі;
2. **вирівнювання експозиції** — найдієвіший крок; після нього різнобій
   зникає приблизно наполовину, бо саме різна яскравість читається як
   «фотографії з різних місць»;
3. **розділене тонування** — тіні в Нуар, світлі в Кістку: це те, що робить
   кадри «одного світла», навіть якщо оригінали знімали при різній
   температурі;
4. **затемнення тла** — фон іде в Нуар, предмет лишається;
5. **плівка** — віньєтка, зерно, підйом чорного.

Параметри плівки імпортуються з `_render.py`, а не дублюються: рендери з B5
лишаються запасним варіантом для товарів без фото, і вони мусять лежати в
одному ряду з фотографіями. Два списки констант розійшлися б на першій же
правці.
"""

import io
import math
from typing import NamedTuple

import numpy as np
from PIL import Image

from ._render import (
    BLACK_FLOOR,
    FILM_GRAIN,
    FILM_VIGNETTE,
    FILM_VIGNETTE_EXP,
    WHITE_CEIL,
)

# Формат каталогу — той самий, що в B5 (ART_DIRECTION.md).
FULL_SIZE = (1200, 1500)
THUMB_SIZE = (600, 750)
WEBP_QUALITY = 84
ASPECT = FULL_SIZE[0] / FULL_SIZE[1]

# --- пороги відсіву ---

# Коротка сторона: усе, менше за це, на сітці 4:5 перетворюється на мило.
MIN_SHORT_SIDE = 1000

# Довгі вузькі смуги — це банери, а не товар.
MIN_ASPECT, MAX_ASPECT = 0.5, 2.0

# Логотип чи заглушка: майже плаский кадр із кількох кольорів.
MIN_UNIQUE_COLORS = 3000
MAX_FLAT_BACKGROUND = 0.72

# Наскільки близькими мають бути dHash, щоб вважати кадри однаковими.
# 8×8 dHash дає 64 біти; 10 — звична межа для «те саме фото, інший ресайз».
DHASH_THRESHOLD = 10

# --- цілі грейду ---

_FLOOR_LUMA = float(BLACK_FLOOR @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32))
_CEIL_LUMA = float(WHITE_CEIL @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32))

# Еталонний тональний профіль — перцентилі яскравості, зняті з рендерів B5.
#
# Спершу тут стояла одна цифра: «підтягнути медіану до 0.149». Контактний лист
# показав, чому цього мало. Рендер — це яскравий предмет на темному тлі, тобто
# широкий діапазон усередині кадру: p5 = 0.05, p99 = 0.81. Вирівнювання за
# медіаною зводило фото в вузьку смугу біля 0.17 — медіана сходилась, а кадр
# виходив млявий і сірий, і рендери поруч кричали, що вони з іншої зйомки.
#
# Тридцять три контрольні точки описують увесь розподіл: і глибину тіней, і
# висоту відблисків. Нижня точка підтягнута до межі палітри — чистого чорного
# в кадрі бути не має.
REFERENCE_TONE_CURVE = np.array(
    [
        _FLOOR_LUMA,
        0.0487,
        0.0555,
        0.0567,
        0.0594,
        0.0623,
        0.0633,
        0.0644,
        0.0672,
        0.0674,
        0.0712,
        0.0724,
        0.0745,
        0.0768,
        0.0818,
        0.0843,
        0.0903,
        0.0997,
        0.1172,
        0.1490,
        0.2270,
        0.2973,
        0.3401,
        0.3773,
        0.4125,
        0.4425,
        0.4664,
        0.4911,
        0.5117,
        0.5290,
        0.5495,
        0.5708,
        0.9291,
    ],
    dtype=np.float32,
)

# Груба ціль для першого проходу. Точну яскравість задає фінальний прохід;
# цей потрібен лише щоб `split_tone` рахував ваги на осмислених значеннях,
# а не на майже чорному чи випаленому кадрі.
COARSE_MEDIAN_LUMA = 0.30

# Наскільки повно прибирається колірний відлив джерела. 1.0 — до повністю
# нейтрального; трохи менше лишає кадру характер, не лишаючи різнобою.
WHITE_BALANCE_STRENGTH = 0.92

# Наскільки сильно тягнемо тіні в Нуар, а світлі ділянки в Кістку.
SHADOW_TINT_STRENGTH = 0.55
HIGHLIGHT_TINT_STRENGTH = 0.35

# Зниження насиченості: легке, щоб кадр не став сірим.
SATURATION = 0.86

# Затемнення тла.
BACKGROUND_DARKEN = 0.88

# Знебарвлення тла під тією ж маскою: 1.0 — повністю сірий фон.
BACKGROUND_DESATURATE = 0.95

# Наскільки м'яко маска предмета спадає до тла.
SUBJECT_SOFTNESS = 0.22

# Наскільки яскравішим за тло має бути піксель, щоб вважатись предметом.
SUBJECT_BRIGHTNESS_THRESHOLD = 0.42

# Межі вікна кропу як частка висоти вихідного кадру. Тримають зум у вузькому
# коридорі навіть тоді, коли рамка предмета визначилась невдало.
MIN_FRAME_SHARE = 0.72
MAX_FRAME_SHARE = 1.0

# Друге знебарвлення — після підгонки тонів, коли гало вже видно.
OUTSIDE_NEUTRAL_STRENGTH = 0.90


class Rejection(NamedTuple):
    """Причина відмови у форматі, придатному і для таблиці, і для логу."""

    reason: str
    detail: str

    def __str__(self):
        return f'{self.reason}: {self.detail}'


# ---------------------------------------------------------------------------
# Перцептивний хеш
# ---------------------------------------------------------------------------


def dhash(image, size=8):
    """Різницевий хеш 8×8: 64 біти, стійкі до ресайзу й перекодування.

    Свій, а не `imagehash`: алгоритм — десять рядків, а нова залежність
    заради них до `pyproject.toml` не вартує.
    """
    small = image.convert('L').resize((size + 1, size), Image.LANCZOS)
    pixels = np.asarray(small, dtype=np.int16)

    bits = pixels[:, 1:] > pixels[:, :-1]
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    return value


def hamming(left, right):
    """Скільки бітів різняться — міра несхожості двох кадрів."""
    return bin(left ^ right).count('1')


def is_duplicate(candidate_hash, known_hashes, threshold=DHASH_THRESHOLD):
    """Чи є серед відомих хешів достатньо близький."""
    return any(hamming(candidate_hash, known) <= threshold for known in known_hashes)


# ---------------------------------------------------------------------------
# Відсів
# ---------------------------------------------------------------------------


def screen(data):
    """Перевірити кандидата. Повертає (Image, None) або (None, Rejection).

    На вході — байти невідомого походження: автопошук приносить логотипи,
    банери, скріншоти й HTML-сторінки з розширенням .jpg. Пороги тут навмисно
    жорсткі: краще лишити рендер, ніж поставити в каталог банер.
    """
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        return None, Rejection('не зображення', f'{type(exc).__name__}')

    image = image.convert('RGB')
    width, height = image.size

    if min(width, height) < MIN_SHORT_SIDE:
        return None, Rejection('замалий', f'{width}×{height}, треба ≥{MIN_SHORT_SIDE} по короткій')

    ratio = width / height
    if not (MIN_ASPECT <= ratio <= MAX_ASPECT):
        return None, Rejection('банер', f'співвідношення {ratio:.2f}')

    colors = image.getcolors(maxcolors=MIN_UNIQUE_COLORS)
    if colors is not None:
        # getcolors повернув список — отже, унікальних кольорів менше за поріг.
        return None, Rejection('плаский кадр', f'{len(colors)} кольорів — схоже на логотип')

    flat = flat_background_share(image)
    if flat > MAX_FLAT_BACKGROUND:
        return None, Rejection('заливка', f'{flat:.0%} кадру — один тон')

    return image, None


def flat_background_share(image):
    """Частка кадру, зайнята найпоширенішим тоном — крім чорного.

    Дешевий детектор графіки: у фотографії навіть рівний фон має градієнт і
    шум, тож жоден окремий тон не займає більшої частини кадру. У логотипа чи
    рекламного банера — займає.

    Чорний не рахується. Нуарну предметку знімають на фоні, свідомо
    придавленому в нуль, і там один тон займає три чверті кадру — фільтр
    відсіював саме ті кадри, які найкраще лягають у каталог. Графіку на
    чорному це не пропускає: у логотипа кілька кольорів, і його ловить
    `MIN_UNIQUE_COLORS` у `screen()`.
    """
    small = image.resize((128, 160), Image.LANCZOS)
    # Огрубляємо до 32 рівнів на канал, щоб шум не рахувався за різні кольори.
    quantised = (np.asarray(small, dtype=np.uint8) >> 3).reshape(-1, 3)
    packed = (
        (quantised[:, 0].astype(np.int32) << 10)
        | (quantised[:, 1].astype(np.int32) << 5)
        | quantised[:, 2].astype(np.int32)
    )

    # «Чорний» — нижні два рівні з 32 у кожному каналі, тобто темніше 16/255.
    lit = packed[~(quantised <= 1).all(axis=1)]
    if lit.size == 0:
        return 0.0

    _, counts = np.unique(lit, return_counts=True)
    return counts.max() / packed.size


# ---------------------------------------------------------------------------
# Кроп
# ---------------------------------------------------------------------------


def subject_box(image):
    """Межі предмета в кадрі.

    Спершу тут були градієнти, і вони не спрацювали: у предметній зйомці
    найсильніший градієнт часто дає не флакон, а лінія переходу тла в підлогу —
    вона тягнеться на всю ширину кадру, тож межі виходили майже на весь кадр,
    маска накривала все, і затемнення тла не робило нічого. На контактному
    листі це читалось як кольорове гало довкола кожного флакона.

    Тому ознака тут яскравість: предмет освітлений, тло — ні. Береться
    найбільша зв'язна маса яскравих пікселів у центральній частині кадру;
    поодинокі відблиски на тлі до неї не потрапляють, бо межі рахуються по
    перцентилях маси, а не по крайніх точках.
    """
    small = image.convert('L').resize((160, 200), Image.LANCZOS)
    gray = np.asarray(small, dtype=np.float32) / 255.0
    height, width = gray.shape

    background = float(np.percentile(gray, 25))
    peak = float(np.percentile(gray, 99))
    if peak - background < 1e-3:
        return 0, 0, image.size[0], image.size[1]

    bright = gray >= background + (peak - background) * SUBJECT_BRIGHTNESS_THRESHOLD

    # Край кадру ігноруємо: предмет у центрі, а по краях часто світлий фон.
    margin_x, margin_y = int(width * 0.06), int(height * 0.06)
    bright[:margin_y, :] = bright[-margin_y:, :] = False
    bright[:, :margin_x] = bright[:, -margin_x:] = False

    if not bright.any():
        return 0, 0, image.size[0], image.size[1]

    left, right = _mass_span(bright.sum(axis=0).astype(np.float32))
    top, bottom = _mass_span(bright.sum(axis=1).astype(np.float32))

    scale_x, scale_y = image.size[0] / width, image.size[1] / height
    return (
        int(left * scale_x),
        int(top * scale_y),
        int(right * scale_x),
        int(bottom * scale_y),
    )


def _mass_span(profile, keep=0.94):
    """Межі, всередині яких зосереджено `keep` маси профілю яскравих пікселів."""
    total = profile.sum()
    if total <= 0:
        return 0, len(profile)

    cumulative = np.cumsum(profile) / total
    margin = (1.0 - keep) / 2.0

    start = int(np.searchsorted(cumulative, margin))
    end = int(np.searchsorted(cumulative, 1.0 - margin))
    return start, max(end, start + 1)


def crop_to_ratio(image, box=None, headroom=0.10):
    """Кроп 4:5, центрований на предметі, з відступом зверху.

    `headroom` зсуває кадр угору: предмет, поставлений точно в геометричний
    центр, візуально «падає» — око чекає трохи більше повітря над ним.
    """
    width, height = image.size
    left, top, right, bottom = box or subject_box(image)

    cx = (left + right) / 2.0
    cy = (top + bottom) / 2.0

    # Розмір вікна — за предметом, але в жорстких межах.
    #
    # Обмеження не косметичне: визначення предмета іноді хибить (темний флакон
    # на темному тлі дає надто низьку рамку), і без нижньої межі кроп заганяв
    # кадр у такий зум, що флакон вилазив за краї. Верхня межа — щоб предмет
    # не потонув у просторі. Однакові пропорції предмета в кадрі — така сама
    # частина «однієї зйомки», як і однакове світло.
    subject_h = bottom - top
    target_h = float(np.clip(subject_h * 1.5, height * MIN_FRAME_SHARE, height * MAX_FRAME_SHARE))
    target_h = min(target_h, height)
    target_w = target_h * ASPECT

    if target_w > width:
        target_w = width
        target_h = target_w / ASPECT

    cy -= target_h * headroom

    x0 = int(round(min(max(cx - target_w / 2.0, 0), width - target_w)))
    y0 = int(round(min(max(cy - target_h / 2.0, 0), height - target_h)))

    return image.crop((x0, y0, x0 + int(target_w), y0 + int(target_h)))


def macro_crop(image, scale=0.42):
    """Кроп деталі з основного кадру — другий корисний знімок із одного.

    Береться верхня третина предмета: там кришка, плечі флакона й найцікавіші
    відблиски. Це звичайний прийом предметної зйомки, а не економія.
    """
    width, height = image.size
    box_w = int(width * scale)
    box_h = int(box_w / ASPECT)

    x0 = (width - box_w) // 2
    y0 = int(height * 0.18)

    if y0 + box_h > height:
        y0 = max(0, height - box_h)

    return image.crop((x0, y0, x0 + box_w, y0 + box_h))


# ---------------------------------------------------------------------------
# Грейд
# ---------------------------------------------------------------------------


def _to_linear(array):
    return np.where(array <= 0.04045, array / 12.92, ((array + 0.055) / 1.055) ** 2.4)


def _to_srgb(array):
    return np.where(array <= 0.0031308, array * 12.92, 1.055 * array ** (1 / 2.4) - 0.055)


def luma(array):
    """Яскравість за Rec.709."""
    return array @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def normalise_exposure(array, target=COARSE_MEDIAN_LUMA):
    """Підтягнути медіанну яскравість кадру до спільної цілі.

    Множник, а не зсув: множення зберігає співвідношення яскравостей, тобто
    не робить кадр плоским. Обмеження на розмах — щоб дуже темний оригінал
    не витягувався в шум.
    """
    current = float(np.median(luma(array)))
    if current <= 1e-4:
        return array

    factor = float(np.clip(target / current, 0.35, 2.8))
    return np.clip(array * factor, 0.0, 1.0)


def neutralise_white_balance(array, strength=WHITE_BALANCE_STRENGTH):
    """Прибрати колірний відлив джерела — «біле по білій точці».

    Найважливіший крок після експозиції, і найлегше його проґавити: вирівняна
    яскравість без вирівняного балансу дає рівно те, що видно на пробному
    контактному листі — один кадр рожевий, сусідній зелений, третій фіолетовий,
    хоч усі однакової світлості.

    Опорна точка — 97-й перцентиль по кожному каналу, а не середнє: у
    предметній зйомці найсвітліші ділянки це відблиски, а вони мають колір
    джерела світла. Середнє по кадру збилося б на колір фону.

    Тонування бренду (`split_tone`) накладається вже після цього — на
    нейтральну основу, а не поверх чужого відливу.
    """
    reference = np.percentile(array.reshape(-1, 3), 97, axis=0)
    target = float(reference.mean())

    gains = np.clip(target / np.maximum(reference, 1e-4), 0.55, 1.8)
    gains = 1.0 + (gains - 1.0) * strength

    return np.clip(array * gains.astype(np.float32), 0.0, 1.0)


def split_tone(array, shadows, highlights):
    """Тіні — в один колір, світлі ділянки — в інший.

    Саме цей крок робить різні зйомки «одним світлом»: він переписує
    температуру кадру, а не просто його яскравість.
    """
    weight = luma(array)[..., None]

    shadow_mix = (1.0 - weight) ** 2.0 * SHADOW_TINT_STRENGTH
    highlight_mix = weight**2.0 * HIGHLIGHT_TINT_STRENGTH

    result = array * (1.0 - shadow_mix) + shadows * shadow_mix
    result = result * (1.0 - highlight_mix) + highlights * highlight_mix
    return np.clip(result, 0.0, 1.0)


def match_tone_curve(array, curve=REFERENCE_TONE_CURVE):
    """Підігнати розподіл яскравості кадру під еталонний профіль B5.

    Це і є те, що робить фото й рендери «однією зйомкою»: збігається не одне
    число, а вся крива — глибина тіней, положення середніх тонів і висота
    відблисків. Вирівнювання за медіаною давало збіг у центрі й розбіжність
    на кінцях, а око читає саме кінці.

    Коефіцієнт рахується по яскравості й застосовується до всіх трьох каналів
    однаково, тому відтінок кадру не змінюється — тон уже заданий раніше
    балансом білого і роздільним тонуванням.
    """
    brightness = luma(array)

    quantiles = np.percentile(brightness, np.linspace(0.0, 100.0, len(curve)))
    # np.interp вимагає строго зростаючої шкали; плаский кадр дає повтори.
    quantiles = np.maximum.accumulate(quantiles) + np.arange(len(curve)) * 1e-6

    mapped = np.interp(brightness, quantiles, curve).astype(np.float32)
    gain = mapped / np.maximum(brightness, 1e-4)

    result = array * gain[..., None]
    # Гарантія меж палітри: ані чистого чорного, ані чистого білого.
    return np.clip(result, BLACK_FLOOR, WHITE_CEIL)


def neutralise_outside(array, mask, strength=OUTSIDE_NEUTRAL_STRENGTH):
    """Добити залишковий колір поза предметом уже після підгонки тонів.

    Крива розтягує напівтінь, і те, що до неї було ледь помітним відливом,
    після неї стає видимим гало. Тому знебарвлення повторюється: один раз до
    кривої, другий — після, коли видно результат.
    """
    background = (1.0 - mask)[..., None]
    gray = luma(array)[..., None]

    return array + (gray - array) * background * strength


def desaturate(array, amount=SATURATION):
    gray = luma(array)[..., None]
    return np.clip(gray + (array - gray) * amount, 0.0, 1.0)


def subject_mask(shape, box, softness=SUBJECT_SOFTNESS):
    """Мʼяка еліптична маска довкола предмета: 1 на предметі, 0 на тлі.

    Радіальна маска від центру кадру, яка стояла тут раніше, не працювала:
    підсвічений чужий фон утворює кольорове гало щільно довкола флакона —
    близько до центру й досить яскраве, тож ані відстань, ані яскравість його
    не відділяли. Межі предмета ми вже знаємо з кропу, тож розумніше рахувати
    від них.
    """
    height, width = shape
    left, top, right, bottom = box

    cx = (left + right) / 2.0
    cy = (top + bottom) / 2.0
    rx = max((right - left) / 2.0, width * 0.08) * (1.0 + softness)
    ry = max((bottom - top) / 2.0, height * 0.08) * (1.0 + softness)

    ys = (np.arange(height, dtype=np.float32)[:, None] - cy) / ry
    xs = (np.arange(width, dtype=np.float32)[None, :] - cx) / rx
    distance = np.sqrt(xs**2 + ys**2)

    # 1 усередині еліпса, плавно до 0 на подвоєному радіусі.
    return np.clip(1.0 - (distance - 1.0) / max(softness * 4.0, 1e-3), 0.0, 1.0)


def darken_background(array, mask, strength=BACKGROUND_DARKEN):
    """Фон іде в Нуар — і по яскравості, і по кольору.

    Маска — добуток двох ознак: далеко від центру і темніше за предмет.
    Помилятись вона може лише в бік «недотемнили», і це навмисно: з'їдений
    край флакона помітно одразу, а трохи світліший фон — ні.

    Знебарвлення тут не менш важливе за затемнення. Баланс білого рівняє
    освітлювач, але не колір чужого тла: студія з рожевим фоном лишиться
    рожевою, хоч і темною. Саме залишковий колір фону читається на
    контактному листі як «кадри з різних місць», тому під маскою насиченість
    гаситься майже повністю.
    """
    background = (1.0 - mask)[..., None]

    # Спершу гасимо колір фону, потім тягнемо його в Нуар. Порядок важливий:
    # затемнений кольоровий фон лишився б кольоровим, тільки темнішим.
    gray = luma(array)[..., None]
    neutral = array + (gray - array) * background * BACKGROUND_DESATURATE

    return np.clip(
        neutral * (1.0 - background * strength) + BLACK_FLOOR * background * strength,
        0.0,
        1.0,
    )


def apply_vignette(array, vignette=FILM_VIGNETTE):
    """Віньєтка — тим самим числом, що в B5."""
    height, width, _ = array.shape

    ys = np.linspace(-1.0, 1.0, height, dtype=np.float32)[:, None]
    xs = np.linspace(-1.0, 1.0, width, dtype=np.float32)[None, :]
    radius = np.sqrt(xs**2 + ys**2) / math.sqrt(2.0)

    return np.clip(array * (1.0 - vignette * radius**FILM_VIGNETTE_EXP)[..., None], 0.0, 1.0)


def apply_grain(array, rng, grain=FILM_GRAIN):
    """Зерно — останнім кроком, уже на фінальних тонах.

    До підгонки кривої його накладати не можна: та розтягує темні ділянки, і
    рівне зерно перетворюється на плямистий шум у фоні.
    """
    height, width, _ = array.shape
    noise = rng.normal(0.0, grain, size=(height, width, 1)).astype(np.float32)
    return np.clip(array + noise, BLACK_FLOOR, WHITE_CEIL)


def lift_to_palette(array):
    """Ані чистого чорного, ані чистого білого — кадр лишається в палітрі.

    Робиться **останнім**: після нього яскравість більше ніхто не чіпає, тож
    фінальна медіана кадру передбачувана й однакова для всіх.
    """
    return np.clip(BLACK_FLOOR + array * (WHITE_CEIL - BLACK_FLOOR), 0.0, 1.0)


def grade(image, seed=0):
    """Повний конвеєр: кадр на вході, кадр «однієї зйомки» на виході."""
    rng = np.random.default_rng(seed)

    array = np.asarray(image.convert('RGB'), dtype=np.float32) / 255.0

    # Маска предмета рахується один раз на вихідному кадрі й обслуговує обидва
    # кроки роботи з тлом — до кривої й після неї.
    mask = subject_mask(array.shape[:2], subject_box(image))

    linear = _to_linear(array).astype(np.float32)

    linear = normalise_exposure(linear)
    linear = neutralise_white_balance(linear)
    linear = split_tone(linear, BLACK_FLOOR, WHITE_CEIL)
    linear = desaturate(linear)
    linear = darken_background(linear, mask)

    srgb = _to_srgb(np.clip(linear, 0.0, 1.0)).astype(np.float32)
    srgb = apply_vignette(srgb)

    # Підгонка тонального профілю — головний крок: саме він ставить кадр в один
    # ряд із рендерами B5. Він же гарантує межі палітри.
    srgb = match_tone_curve(srgb)

    # Порядок двох останніх кроків має значення: обидва працюють із тим, що
    # крива щойно витягла з темряви.
    srgb = neutralise_outside(srgb, mask)
    finished = apply_grain(srgb, rng)

    return Image.fromarray((finished * 255.0).astype(np.uint8), mode='RGB')


def encode_webp(image, size):
    """Готовий кадр → WebP у памʼяті. Ресайз завжди з великого."""
    resized = image.resize(size, Image.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, format='WEBP', quality=WEBP_QUALITY, method=6)
    return buffer.getvalue()


def is_catalogue_ratio(image, tolerance=0.01):
    """Чи кадр уже в пропорції каталогу 4:5 — тоді кропати його нема чого."""
    width, height = image.size
    return abs(width / height - ASPECT) <= ASPECT * tolerance


def process(image, seed=0, graded=True):
    """Кандидат → (обкладинка, мініатюра, макро) у байтах WebP.

    `graded=False` — для кадрів, уже відібраних під каталог вручну: без
    тонування, без затемнення тла, а готовий кадр 4:5 ще й без перекропу.
    Грейд писався під синтетичні рендери з кольоровим тлом; на живих фото
    затемнення за маскою предмета малює сірі овальні ореоли, а тональна
    крива постеризує фактури — мох, кавові зерна. Відібраному кадру він
    лише шкодить.
    """
    if graded:
        cropped = crop_to_ratio(image)
        frame = grade(cropped, seed=seed)
        detail = grade(macro_crop(cropped), seed=seed + 1)
    else:
        frame = image.convert('RGB')
        if not is_catalogue_ratio(frame):
            frame = crop_to_ratio(frame)
        detail = macro_crop(frame)

    return {
        'full': encode_webp(frame, FULL_SIZE),
        'thumb': encode_webp(frame, THUMB_SIZE),
        'macro': encode_webp(detail, FULL_SIZE),
    }


def measure(image):
    """Медіанна яскравість і насиченість — для звіту про однорідність."""
    array = np.asarray(image.convert('RGB'), dtype=np.float32) / 255.0
    brightness = luma(array)
    maximum = array.max(axis=-1)
    minimum = array.min(axis=-1)
    saturation = np.where(maximum > 0, (maximum - minimum) / np.maximum(maximum, 1e-4), 0.0)

    # Відлив — розкид середніх по каналах: 0 означає нейтральний кадр.
    channels = array.reshape(-1, 3).mean(axis=0)
    cast = float(channels.max() - channels.min())

    # Окремо по кутах: саме залишковий колір фону створює враження, що кадри
    # знімали в різних місцях, і в середньому по кадру він губиться.
    h, w, _ = array.shape
    ch, cw = max(h // 6, 1), max(w // 6, 1)
    corners = np.concatenate(
        [
            array[:ch, :cw].reshape(-1, 3),
            array[:ch, -cw:].reshape(-1, 3),
            array[-ch:, :cw].reshape(-1, 3),
            array[-ch:, -cw:].reshape(-1, 3),
        ]
    ).mean(axis=0)
    corner_cast = float(corners.max() - corners.min())

    return {
        'median_luma': float(np.median(brightness)),
        'mean_saturation': float(saturation.mean()),
        'black_point': float(brightness.min()),
        'white_point': float(brightness.max()),
        'cast': cast,
        'corner_cast': corner_cast,
    }

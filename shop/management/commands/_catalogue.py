"""Дані каталогу SILLAGE — джерело для `manage.py seed_shop`.

Відповідає `data_plan.txt`: 16 категорій, 9 брендів, ~40 нот, 30 товарів.
Тексти справжні й українською — опис товару це половина враження від
магазину, і генерувати його шаблоном означало б зіпсувати саме те, заради
чого будувався каталог.

Модуль починається з підкреслення, тому Django не вважає його командою.
"""

from decimal import Decimal

from shop.models import Note, Product, ProductNote

# ---------------------------------------------------------------------------
# Категорії
# ---------------------------------------------------------------------------

# (slug, назва, опис, [(slug, назва), ...])
CATEGORIES = [
    (
        'aromaty',
        'Аромати',
        'Двадцять один аромат. Кожен обраний за те, що він розповідає, '
        'а не за те, скільки він коштує.',
        [
            ('derevni', 'Деревні'),
            ('kvitkovi', 'Квіткові'),
            ('ambrovi', 'Амброві'),
            ('tsytrusovi', 'Цитрусові'),
            ('hurmanski', 'Гурманські'),
            ('shkira-i-tyutyun', 'Шкіра і тютюн'),
            ('akvatychni', 'Акватичні'),
        ],
    ),
    (
        'dim',
        'Дім',
        'Те, чим пахне кімната, коли вас у ній ще немає.',
        [
            ('svichky', 'Свічки'),
            ('dyfuzory', 'Дифузори'),
            ('aromasprei', 'Аромаспреї'),
        ],
    ),
    (
        'formaty',
        'Формати',
        'Спробувати перед тим, як закохатись. І повернутись, коли скінчиться.',
        [
            ('discovery-sety', 'Discovery-сети'),
            ('travel-10ml', 'Тревел 10 мл'),
            ('refily', 'Рефіли'),
        ],
    ),
]

# ---------------------------------------------------------------------------
# Бренди
# ---------------------------------------------------------------------------

# (slug, назва, країна, рік, опис)
BRANDS = [
    (
        'maison-ferrant',
        'Maison Ferrant',
        'Франція',
        1946,
        'Класичний французький дім, заснований через рік після війни — на гроші, '
        'виручені за проданий рояль. Троянда, ірис, альдегіди: усе те, що вважалося '
        'старомодним рівно доти, доки не стало знову сучасним. Тут досі пишуть '
        'формули від руки і не вважають це кокетством.',
    ),
    (
        'atelier-noir',
        'Atelier Noir',
        'Франція',
        2009,
        'Майстерня одного парфумера, який відмовився працювати на великі концерни '
        'і відкрив підвал у Марселі. Шкіра, тютюн, дьоготь, ветивер — найтемніші '
        'аромати каталогу. Нічого рожевого, нічого солодкого, жодного компліменту '
        'наздогін.',
    ),
    (
        'vestige',
        'Vestige',
        'Італія',
        2014,
        'Мінеральність, камінь, суха деревина. Дім називає свій метод «ольфакторною '
        'археологією»: кожен аромат відновлює запах місця, якого вже немає — '
        'теплого мармуру, пилу в порожньому залі, замші на спинці крісла.',
    ),
    (
        'orris-and-co',
        'Orris and Co.',
        'Британія',
        1998,
        'Спеціалісти з ірису й нічого більше. Корінь визріває шість років, перш ніж '
        'із нього щось дістануть, — саме тому їхні флакони коштують стільки, скільки '
        'коштують. Пудрові, прохолодні, навмисно стримані композиції.',
    ),
    (
        'casa-lume',
        'Casa Lume',
        'Італія',
        1987,
        'Середземноморʼя без листівкової краси: лимон, неролі, інжир, сонце о другій '
        'дня, коли всі нормальні люди сидять у тіні. Найлегший і найдоступніший дім '
        'каталогу — і найчастіший перший флакон наших покупців.',
    ),
    (
        'nord-botanica',
        'Nord Botanica',
        'Швеція',
        2011,
        'Скандинавська стриманість, доведена до принципу: не більше семи складників '
        'у формулі. Хвоя, мох, сіль, мінерали. В їхніх ароматах відчувається холодне '
        'повітря — не свіжість із реклами, а саме холод.',
    ),
    (
        'seance',
        'Séance',
        'Франція',
        2016,
        'Ладан, смоли, кава, темні спеції. Дім грає з ритуальністю відкрито і з '
        'гумором: флакони нумеруються не за порядком, а за римськими числами, '
        'і жоден покупець досі не зрозумів логіки. Аромати для тих, кому '
        'подобається трохи театру.',
    ),
    (
        'ambre-rouge',
        'Ambre Rouge',
        'Іспанія',
        1972,
        'Амбра, ваніль, мед, бензоїн — тепла, щільна, зимова парфумерія з Валенсії. '
        'Дім пережив дві зміни власників і жодного разу не змінив стиль: усе, що '
        'вони випускають, гріє.',
    ),
    (
        'sillage',
        'SILLAGE',
        'Україна',
        2024,
        'Власна марка магазину. Не парфуми — спосіб їх обрати: кураторські сети, '
        'у яких вісім ароматів підібрані так, щоб ви зрозуміли, що вам насправді '
        'подобається, ще до того, як витратите сім тисяч на помилку.',
    ),
]

# ---------------------------------------------------------------------------
# Ноти
# ---------------------------------------------------------------------------

# назва -> ольфакторна родина
NOTES = {
    # Цитрусові
    'бергамот': Note.FAMILY_CITRUS,
    'калабрійський бергамот': Note.FAMILY_CITRUS,
    'лимон': Note.FAMILY_CITRUS,
    'сицилійський лимон': Note.FAMILY_CITRUS,
    'лимонна цедра': Note.FAMILY_CITRUS,
    'лимонний лист': Note.FAMILY_CITRUS,
    'мандарин': Note.FAMILY_CITRUS,
    'зелений мандарин': Note.FAMILY_CITRUS,
    'грейпфрут': Note.FAMILY_CITRUS,
    'рожевий грейпфрут': Note.FAMILY_CITRUS,
    'гіркий апельсин': Note.FAMILY_CITRUS,
    'апельсинова цедра': Note.FAMILY_CITRUS,
    'петитгрейн': Note.FAMILY_CITRUS,
    'неролі': Note.FAMILY_CITRUS,
    # Квіткові
    'травнева троянда': Note.FAMILY_FLORAL,
    'дамаська троянда': Note.FAMILY_FLORAL,
    'півонія': Note.FAMILY_FLORAL,
    'тубероза': Note.FAMILY_FLORAL,
    'жасмин самбак': Note.FAMILY_FLORAL,
    'гарденія': Note.FAMILY_FLORAL,
    'корінь ірису': Note.FAMILY_FLORAL,
    'ірис': Note.FAMILY_FLORAL,
    'фіалка': Note.FAMILY_FLORAL,
    'фіалковий лист': Note.FAMILY_FLORAL,
    'геліотроп': Note.FAMILY_FLORAL,
    'іммортель': Note.FAMILY_FLORAL,
    'лаванда': Note.FAMILY_FLORAL,
    'морська лаванда': Note.FAMILY_FLORAL,
    'альдегіди': Note.FAMILY_FLORAL,
    # Деревні
    'атласький кедр': Note.FAMILY_WOODY,
    'кедр': Note.FAMILY_WOODY,
    'сухий кедр': Note.FAMILY_WOODY,
    'мисорський сандал': Note.FAMILY_WOODY,
    'сандал': Note.FAMILY_WOODY,
    'ветивер': Note.FAMILY_WOODY,
    'гаїтянський ветивер': Note.FAMILY_WOODY,
    'кипарис': Note.FAMILY_WOODY,
    'ялівець': Note.FAMILY_WOODY,
    'смерекова глиця': Note.FAMILY_WOODY,
    'агарове дерево': Note.FAMILY_WOODY,
    'сухе дерево': Note.FAMILY_WOODY,
    'вибілене морем дерево': Note.FAMILY_WOODY,
    'кокосове дерево': Note.FAMILY_WOODY,
    'пачулі': Note.FAMILY_WOODY,
    # Спеції
    'рожевий перець': Note.FAMILY_SPICY,
    'чорний перець': Note.FAMILY_SPICY,
    'кардамон': Note.FAMILY_SPICY,
    'кориця': Note.FAMILY_SPICY,
    'гвоздика': Note.FAMILY_SPICY,
    'шафран': Note.FAMILY_SPICY,
    'мускатний горіх': Note.FAMILY_SPICY,
    'кмин': Note.FAMILY_SPICY,
    'розмарин': Note.FAMILY_SPICY,
    'шавлія': Note.FAMILY_SPICY,
    'мускатна шавлія': Note.FAMILY_SPICY,
    'біла шавлія': Note.FAMILY_SPICY,
    'евкаліпт': Note.FAMILY_SPICY,
    'мʼята': Note.FAMILY_SPICY,
    # Смоли
    'ладан': Note.FAMILY_RESIN,
    'мирра': Note.FAMILY_RESIN,
    'елемі': Note.FAMILY_RESIN,
    'бензоїн': Note.FAMILY_RESIN,
    'лабданум': Note.FAMILY_RESIN,
    'сіра амбра': Note.FAMILY_RESIN,
    'амбра': Note.FAMILY_RESIN,
    'мінеральна амбра': Note.FAMILY_RESIN,
    'березовий дьоготь': Note.FAMILY_RESIN,
    # Гурманські
    'ваніль': Note.FAMILY_GOURMAND,
    'бурбонська ваніль': Note.FAMILY_GOURMAND,
    'боби тонка': Note.FAMILY_GOURMAND,
    'тонка': Note.FAMILY_GOURMAND,
    'мед': Note.FAMILY_GOURMAND,
    'смажена кава': Note.FAMILY_GOURMAND,
    'какао-боби': Note.FAMILY_GOURMAND,
    'гіркий мигдаль': Note.FAMILY_GOURMAND,
    'мигдальне молочко': Note.FAMILY_GOURMAND,
    'інжирне молочко': Note.FAMILY_GOURMAND,
    'кокос': Note.FAMILY_GOURMAND,
    'сухофрукти': Note.FAMILY_GOURMAND,
    'слива': Note.FAMILY_GOURMAND,
    'личі': Note.FAMILY_GOURMAND,
    'ревінь': Note.FAMILY_GOURMAND,
    'рисова пудра': Note.FAMILY_GOURMAND,
    # Зелені
    'зелений листок': Note.FAMILY_GREEN,
    'галбанум': Note.FAMILY_GREEN,
    'зелений інжир': Note.FAMILY_GREEN,
    'чорна смородина': Note.FAMILY_GREEN,
    'насіння моркви': Note.FAMILY_GREEN,
    'чай улун': Note.FAMILY_GREEN,
    'димчастий чай': Note.FAMILY_GREEN,
    'димчастий чай лапсанг': Note.FAMILY_GREEN,
    'дубовий мох': Note.FAMILY_GREEN,
    'сухий мох': Note.FAMILY_GREEN,
    # Акватичні
    'морська сіль': Note.FAMILY_AQUATIC,
    'водорості': Note.FAMILY_AQUATIC,
    'озонові ноти': Note.FAMILY_AQUATIC,
    # Тваринні
    'білий мускус': Note.FAMILY_ANIMALIC,
    'мускус': Note.FAMILY_ANIMALIC,
    'амбретта': Note.FAMILY_ANIMALIC,
    'кастореум': Note.FAMILY_ANIMALIC,
    'замша': Note.FAMILY_ANIMALIC,
    'сафʼянова шкіра': Note.FAMILY_ANIMALIC,
    'тютюновий лист': Note.FAMILY_ANIMALIC,
    'кашмеран': Note.FAMILY_ANIMALIC,
}

# ---------------------------------------------------------------------------
# Скорочення для читабельності таблиці товарів
# ---------------------------------------------------------------------------

EDC = Product.CONCENTRATION_EDC
EDT = Product.CONCENTRATION_EDT
EDP = Product.CONCENTRATION_EDP
EXT = Product.CONCENTRATION_EXTRAIT
OIL = Product.CONCENTRATION_OIL

UNI = Product.GENDER_UNISEX
FEM = Product.GENDER_FEMININE
MAS = Product.GENDER_MASCULINE

INTIMATE = Product.SILLAGE_INTIMATE
MODERATE = Product.SILLAGE_MODERATE
STRONG = Product.SILLAGE_STRONG
ENORMOUS = Product.SILLAGE_ENORMOUS

TOP = ProductNote.LAYER_TOP
HEART = ProductNote.LAYER_HEART
BASE = ProductNote.LAYER_BASE


def price(value):
    """Гроші — завжди Decimal і ніколи рядок.

    Рядок у грошовому полі доїжджає до арифметики через float і дає копійчані
    розбіжності в підсумку замовлення. Це найгірший клас багів, бо тихий.
    """
    return Decimal(value)

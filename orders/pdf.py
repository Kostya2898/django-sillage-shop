"""PDF-рахунок до замовлення.

Двигун — xhtml2pdf (поверх reportlab). WeasyPrint тут свідомо не використано:
він тягне за собою GTK, який на Windows не ставиться без окремого інсталятора,
а проєкт має збиратись однією командою на будь-якій машині розробника.

**Про кирилицю.** Вбудовані шрифти reportlab (Helvetica й компанія) кирилиці
не мають — з ними рахунок друкується чорними квадратами. Тому шрифт
підключається явно: DejaVu Sans лежить у `static/fonts/` разом зі своєю
ліцензією і потрапляє в PDF через `@font-face` у шаблоні.
"""

import logging
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from xhtml2pdf import pisa
from xhtml2pdf.default import DEFAULT_FONT

logger = logging.getLogger(__name__)

INVOICE_TEMPLATE = 'orders/invoice.html'


class InvoiceRenderError(RuntimeError):
    """Рахунок не вдалося зібрати."""


# Шрифт із кирилицею. Шлях віддається шаблону, щоб той поставив його
# в @font-face: xhtml2pdf вміє читати локальні файли через link_callback.
FONT_DIR = settings.BASE_DIR / 'static' / 'fonts'
FONT_REGULAR = FONT_DIR / 'DejaVuSans.ttf'
FONT_BOLD = FONT_DIR / 'DejaVuSans-Bold.ttf'

# Імʼя, під яким шрифт видно в CSS шаблона.
FONT_FAMILY = 'DejaVuSans'

_fonts_registered = False


def register_fonts():
    """Зареєструвати DejaVu у reportlab і показати його xhtml2pdf.

    Через `@font-face` у CSS не працює: xhtml2pdf мовчки лишає Helvetica —
    файл збирається, помилок немає, а кирилиця виходить квадратами. Тому шрифт
    реєструється напряму в reportlab, а `DEFAULT_FONT` — це та таблиця, у якій
    xhtml2pdf шукає відповідність між `font-family` з CSS і шрифтом reportlab.

    Реєстрація одноразова на процес: повторний виклик reportlab переживає,
    але змісту в ньому немає.
    """
    global _fonts_registered
    if _fonts_registered:
        return

    if not FONT_REGULAR.exists():
        raise InvoiceRenderError(
            f'Немає шрифту {FONT_REGULAR}. Без нього кирилиця в PDF друкується квадратами.'
        )

    pdfmetrics.registerFont(TTFont(FONT_FAMILY, str(FONT_REGULAR)))

    bold_name = f'{FONT_FAMILY}-Bold'
    if FONT_BOLD.exists():
        pdfmetrics.registerFont(TTFont(bold_name, str(FONT_BOLD)))
    else:
        # Краще той самий накреслення, ніж падіння на кожному <strong>.
        bold_name = FONT_FAMILY
        logger.warning('Немає %s — жирний текст у рахунку буде звичайним', FONT_BOLD)

    pdfmetrics.registerFontFamily(
        FONT_FAMILY,
        normal=FONT_FAMILY,
        bold=bold_name,
        italic=FONT_FAMILY,
        boldItalic=bold_name,
    )

    # Ключі в DEFAULT_FONT — у нижньому регістрі: саме так xhtml2pdf
    # нормалізує font-family перед пошуком.
    DEFAULT_FONT[FONT_FAMILY.lower()] = FONT_FAMILY
    DEFAULT_FONT[f'{FONT_FAMILY.lower()}-bold'] = bold_name

    _fonts_registered = True


def _link_callback(uri, rel):
    """Перетворити URI зі шаблона на шлях у файловій системі.

    xhtml2pdf не ходить у мережу за ресурсами — усе, що потрапляє в PDF,
    має існувати на диску. Сюди приходять посилання на шрифт і на зображення.
    """
    if uri.startswith('file:///'):
        return uri

    for prefix, root in (
        (settings.STATIC_URL, settings.BASE_DIR / 'static'),
        (settings.MEDIA_URL, Path(settings.MEDIA_ROOT)),
    ):
        if prefix and uri.startswith(prefix):
            path = Path(root) / uri[len(prefix) :]
            if path.exists():
                return str(path)
            logger.warning('Рахунок посилається на неіснуючий файл: %s', path)
            return uri

    return uri


def invoice_context(order):
    """Дані рахунку. Винесено окремо, щоб їх можна було перевірити без PDF."""
    return {
        'order': order,
        'items': order.items.all(),
        'seller': settings.INVOICE_SELLER,
        'font_family': FONT_FAMILY,
    }


def render_order_invoice(order):
    """Зібрати PDF-рахунок і повернути його байтами."""
    register_fonts()

    html = render_to_string(INVOICE_TEMPLATE, invoice_context(order))

    buffer = BytesIO()
    result = pisa.CreatePDF(
        html,
        dest=buffer,
        encoding='utf-8',
        link_callback=_link_callback,
    )

    if result.err:
        raise InvoiceRenderError(f'xhtml2pdf повернув {result.err} помилок')

    return buffer.getvalue()


def invoice_filename(order):
    """Імʼя файлу латиницею: кирилиця в Content-Disposition ламає частину клієнтів."""
    return f'sillage-invoice-{order.order_number}.pdf'

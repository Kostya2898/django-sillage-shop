"""PDF-рахунок.

Головна перевірка — кирилиця. Вбудовані шрифти reportlab її не мають, і рахунок
із ними друкується чорними квадратами: файл нібито валідний, помилок немає, а
читати його неможливо. Тому текст із готового PDF тут дістається назад і
звіряється з тим, що мало бути надруковано.
"""

from decimal import Decimal

from django.urls import reverse
from pypdf import PdfReader

from orders.models import Order
from orders.pdf import render_order_invoice
from testing import ShopTestCase
from testing.factories import CouponFactory, DeliveryMethodFactory, ProductFactory


def pdf_text(content):
    """Витягнути текст з усіх сторінок PDF."""
    from io import BytesIO

    reader = PdfReader(BytesIO(content))
    return '\n'.join(page.extract_text() for page in reader.pages)


def embedded_fonts(content):
    from io import BytesIO

    reader = PdfReader(BytesIO(content))
    fonts = set()
    for page in reader.pages:
        for ref in page['/Resources'].get('/Font', {}).values():
            fonts.add(str(ref.get_object().get('/BaseFont')))
    return fonts


class InvoiceRenderingTests(ShopTestCase):
    def setUp(self):
        self.product = ProductFactory(name='Ветивер Обскюр, 50 мл', price=Decimal('4200.00'))
        self.order = self.create_order(items=[(self.product, 2)])
        self.order.shipping_full_name = 'Гринюк Костянтин Вікторович'
        self.order.shipping_city = 'Київ'
        self.order.save(update_fields=['shipping_full_name', 'shipping_city'])

    def test_output_is_a_pdf(self):
        content = render_order_invoice(self.order)

        self.assertTrue(content.startswith(b'%PDF'))

    def test_cyrillic_font_is_embedded(self):
        """Без вбудованого DejaVu кирилиця стає чорними квадратами."""
        fonts = embedded_fonts(render_order_invoice(self.order))

        self.assertTrue(
            any('DejaVuSans' in font for font in fonts),
            f'Кириличний шрифт не потрапив у PDF, там лише: {fonts}',
        )

    def test_cyrillic_is_readable(self):
        text = pdf_text(render_order_invoice(self.order))

        self.assertIn('Ветивер Обскюр', text)
        self.assertIn('Гринюк Костянтин Вікторович', text)
        self.assertIn('Київ', text)

    def test_no_black_squares(self):
        """Прямий контроль симптому: ■ у тексті означає відсутній гліф."""
        text = pdf_text(render_order_invoice(self.order))

        self.assertNotIn('■', text)

    def test_invoice_has_seller_details(self):
        text = pdf_text(render_order_invoice(self.order))

        self.assertIn('Продавець', text)
        self.assertIn('SILLAGE', text)
        self.assertIn('IBAN', text)

    def test_invoice_has_number_and_date(self):
        text = pdf_text(render_order_invoice(self.order))

        self.assertIn(self.order.order_number, text)
        self.assertIn('Рахунок', text)

    def test_invoice_lists_items_with_totals(self):
        text = pdf_text(render_order_invoice(self.order))

        self.assertIn('Ветивер Обскюр', text)
        self.assertIn('8 400', text.replace('\xa0', ' '), 'Сума позиції: 2 × 4 200')

    def test_invoice_has_signature_lines(self):
        text = pdf_text(render_order_invoice(self.order))

        self.assertIn('підпис', text)
        self.assertIn('Отримувач', text)


class InvoiceTotalsTests(ShopTestCase):
    def test_discount_and_delivery_appear_in_the_invoice(self):
        coupon = CouponFactory(code='OSIN', discount_value=Decimal('10'))
        method = DeliveryMethodFactory(name='Нова пошта', price=Decimal('80.00'), free_from=None)
        product = ProductFactory(price=Decimal('1000.00'))

        order = self.create_order(items=[(product, 2)])
        order.coupon = coupon
        order.coupon_code = 'OSIN'
        order.discount_amount = Decimal('200.00')
        order.delivery_method = method
        order.delivery_name = 'Нова пошта'
        order.delivery_price = Decimal('80.00')
        order.total_amount = Decimal('1880.00')
        order.save()

        text = pdf_text(render_order_invoice(order)).replace('\xa0', ' ')

        self.assertIn('OSIN', text)
        self.assertIn('200', text)
        self.assertIn('Нова пошта', text)
        self.assertIn('1 880', text)

    def test_free_delivery_is_named_not_zero(self):
        order = self.create_order()
        order.delivery_name = 'Самовивіз'
        order.delivery_price = Decimal('0.00')
        order.save(update_fields=['delivery_name', 'delivery_price'])

        text = pdf_text(render_order_invoice(order))

        self.assertIn('безкоштовно', text)


class InvoiceViewTests(ShopTestCase):
    def setUp(self):
        self.user = self.login()
        self.order = self.create_order(user=self.user)

    def test_download_returns_a_pdf_attachment(self):
        response = self.client.get(reverse('orders:order_invoice', args=[self.order.order_number]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_filename_is_latin(self):
        """Кирилиця в Content-Disposition ламає частину клієнтів."""
        response = self.client.get(reverse('orders:order_invoice', args=[self.order.order_number]))

        disposition = response['Content-Disposition']
        self.assertTrue(disposition.isascii(), disposition)
        self.assertIn(self.order.order_number, disposition)

    def test_button_is_on_the_order_page(self):
        response = self.client.get(reverse('orders:order_detail', args=[self.order.order_number]))

        self.assertContains(response, 'Завантажити рахунок')
        self.assertContains(
            response, reverse('orders:order_invoice', args=[self.order.order_number])
        )

    def test_stranger_cannot_download_someone_elses_invoice(self):
        theirs = self.create_order()

        response = self.client.get(reverse('orders:order_invoice', args=[theirs.order_number]))

        self.assertEqual(response.status_code, 404)

    def test_anonymous_cannot_download_a_users_invoice(self):
        self.client.logout()

        response = self.client.get(reverse('orders:order_invoice', args=[self.order.order_number]))

        self.assertEqual(response.status_code, 404)


class InvoiceIsOptionalForTheLetterTests(ShopTestCase):
    """Лист про замовлення має піти навіть тоді, коли рахунок не зібрався."""

    def test_letter_survives_a_broken_invoice(self):
        import logging
        from unittest import mock

        from django.core import mail

        from orders.emails import send_order_confirmation_email

        logging.disable(logging.ERROR)
        self.addCleanup(logging.disable, logging.NOTSET)

        order = self.create_order()
        mail.outbox.clear()

        with mock.patch('orders.pdf.render_order_invoice', side_effect=RuntimeError('шрифт зник')):
            sent = send_order_confirmation_email(order)

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].attachments, [], 'Рахунок не додався — і це нормально')


class OrderTotalsBreakdownTests(ShopTestCase):
    """`items_total − discount + delivery = total_amount` для будь-якого замовлення."""

    def test_breakdown_adds_up_after_checkout(self):
        coupon = CouponFactory(code='OSIN', discount_value=Decimal('15'))
        product = ProductFactory(price=Decimal('3000.00'), stock=5)

        user = self.login()
        address = self.create_address(user)
        self.client.post(reverse('cart:cart_add', args=[product.id]), {'quantity': 1})
        self.client.post(reverse('orders:coupon_apply'), {'code': 'OSIN'})
        self.client.post(
            reverse('orders:checkout'), {'select_address': '1', 'address_id': address.id}
        )
        self.client.post(reverse('orders:checkout_confirm'), self.confirm_payload())

        order = Order.objects.get()
        self.assertEqual(
            order.total_amount,
            order.items_total - order.discount_amount + order.delivery_price,
        )
        self.assertEqual(order.coupon, coupon)

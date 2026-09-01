"""Наповнення нових полів даними: підсумки старих замовлень і тарифи доставки.

Дві різні речі в одній міграції свідомо: обидві — це «зробити наявну базу
придатною до нового коду», і застосовуються вони рівно один раз.

`items_total` у старих замовленнях дорівнює `total_amount`: знижок і доставки
тоді ще не існувало, тож сума товарів і була сумою до сплати. Лишити там нуль
означало б, що рахунок за старе замовлення надрукується з нульовими товарами.
"""

from decimal import Decimal

from django.db import migrations
from django.db.models import F

# Тарифи потрібні checkout-у, щоб узагалі відкритись, тому вони приїжджають
# міграцією, а не сидом: сид — це демо-каталог, який на проді ніхто не запускає.
DELIVERY_METHODS = [
    {
        'name': 'Нова пошта, відділення',
        'description': 'Самовивіз із відділення у вашому місті',
        'price': Decimal('80.00'),
        'free_from': Decimal('2500.00'),
        'estimated_days': 2,
        'sort_order': 10,
    },
    {
        'name': 'Нова пошта, курʼєр',
        'description': 'Курʼєр привезе за вказаною адресою',
        'price': Decimal('130.00'),
        'free_from': Decimal('4000.00'),
        'estimated_days': 3,
        'sort_order': 20,
    },
    {
        'name': 'Самовивіз із бутика',
        'description': 'вул. Ярославів Вал, 15, Київ — щодня з 11:00 до 20:00',
        'price': Decimal('0.00'),
        'free_from': None,
        'estimated_days': 1,
        'sort_order': 30,
    },
]


def fill_items_total(apps, schema_editor):
    Order = apps.get_model('orders', 'Order')
    Order.objects.filter(items_total=Decimal('0.00')).update(items_total=F('total_amount'))


def unfill_items_total(apps, schema_editor):
    """Зворотний хід нічого не псує: поле все одно зникне разом із 0002."""


def create_delivery_methods(apps, schema_editor):
    DeliveryMethod = apps.get_model('orders', 'DeliveryMethod')
    for values in DELIVERY_METHODS:
        DeliveryMethod.objects.get_or_create(name=values['name'], defaults=values)


def delete_delivery_methods(apps, schema_editor):
    DeliveryMethod = apps.get_model('orders', 'DeliveryMethod')
    DeliveryMethod.objects.filter(name__in=[v['name'] for v in DELIVERY_METHODS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0002_guest_checkout_coupons_delivery'),
    ]

    operations = [
        migrations.RunPython(fill_items_total, unfill_items_total),
        migrations.RunPython(create_delivery_methods, delete_delivery_methods),
    ]

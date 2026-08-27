"""Третій крок: `brand` стає обовʼязковим, `sku` — унікальним.

Написана вручну, а не через `makemigrations`: автогенератор питає одноразове
значення для `brand`, хоча воно вже не потрібне — попередня data-міграція
(`0003_backfill_brand_and_sku`) проставила бренд усім наявним товарам.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0003_backfill_brand_and_sku'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='brand',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='products',
                to='shop.brand',
                verbose_name='Бренд',
            ),
        ),
        migrations.AlterField(
            model_name='product',
            name='sku',
            field=models.CharField(
                blank=True, max_length=40, unique=True, verbose_name='Артикул'
            ),
        ),
    ]

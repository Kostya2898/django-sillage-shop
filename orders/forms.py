"""Форми checkout-процесу."""

from django import forms

from .models import DeliveryMethod, Order, ShippingAddress

# Поля адреси, які потрапляють у знімок замовлення. Використовуються і формою
# гостя, і збереженням адреси гостя в сесії — тому список один на модуль.
ADDRESS_FIELDS = [
    'full_name',
    'phone',
    'country',
    'city',
    'postal_code',
    'address_line1',
    'address_line2',
]

ADDRESS_WIDGETS = {
    'full_name': forms.TextInput(
        attrs={
            'class': 'form-control',
            'placeholder': 'Прізвище Імʼя По батькові',
            'autocomplete': 'name',
        }
    ),
    'phone': forms.TextInput(
        attrs={
            'class': 'form-control',
            'placeholder': '+380...',
            'autocomplete': 'tel',
            'inputmode': 'tel',
        }
    ),
    'country': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'country-name'}),
    'city': forms.TextInput(
        attrs={
            'class': 'form-control',
            'placeholder': 'Місто',
            'autocomplete': 'address-level2',
        }
    ),
    'postal_code': forms.TextInput(
        attrs={
            'class': 'form-control',
            'placeholder': '01001',
            'autocomplete': 'postal-code',
            'inputmode': 'numeric',
        }
    ),
    'address_line1': forms.TextInput(
        attrs={
            'class': 'form-control',
            'placeholder': 'Вулиця, будинок, квартира',
            'autocomplete': 'address-line1',
        }
    ),
    'address_line2': forms.TextInput(
        attrs={
            'class': 'form-control',
            'placeholder': 'Додаткова інформація (необовʼязково)',
            'autocomplete': 'address-line2',
        }
    ),
}


class ShippingAddressForm(forms.ModelForm):
    """Форма адреси доставки з Bootstrap-класами."""

    class Meta:
        model = ShippingAddress
        fields = [*ADDRESS_FIELDS, 'is_default']
        widgets = {
            **ADDRESS_WIDGETS,
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        optional = {'address_line2', 'is_default'}
        for field_name, field in self.fields.items():
            if field_name not in optional:
                field.required = True


class GuestCheckoutForm(forms.Form):
    """Адреса й контакти покупця, який не заводить акаунт.

    Свідомо не ModelForm: адреса гостя **не** зберігається в адресну книгу,
    вона живе в сесії до створення замовлення і далі існує тільки знімком
    у самому замовленні. ModelForm провокував би випадковий `save()`.

    Email тут обовʼязковий: без нього гість не отримає ні підтвердження, ні
    рахунку, ні посилання на замовлення — і покупка стане невидимою для нього
    самого.
    """

    email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'name@example.com',
                'autocomplete': 'email',
                'inputmode': 'email',
            }
        ),
        help_text='Надішлемо підтвердження, рахунок і посилання на замовлення',
    )
    full_name = forms.CharField(label='ПІБ', max_length=200)
    phone = forms.CharField(label='Телефон', max_length=20)
    country = forms.CharField(label='Країна', max_length=100, initial='Україна')
    city = forms.CharField(label='Місто', max_length=100)
    postal_code = forms.CharField(label='Поштовий індекс', max_length=20)
    address_line1 = forms.CharField(label='Адреса (рядок 1)', max_length=250)
    address_line2 = forms.CharField(label='Адреса (рядок 2)', max_length=250, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Віджети беремо ті самі, що й у формі адреси користувача: дві різні
        # форми не мають виглядати по-різному на сусідніх кроках.
        for name, widget in ADDRESS_WIDGETS.items():
            if name in self.fields:
                self.fields[name].widget = widget

    def address_data(self):
        """Дані адреси без email — рівно те, що лягає в знімок замовлення."""
        return {name: self.cleaned_data[name] for name in ADDRESS_FIELDS}


class OrderCheckoutForm(forms.Form):
    """Фінальне підтвердження замовлення: доставка, оплата, коментар."""

    delivery_method = forms.ModelChoiceField(
        label='Спосіб доставки',
        queryset=DeliveryMethod.objects.none(),
        empty_label=None,
        widget=forms.RadioSelect,
    )

    payment_method = forms.ChoiceField(
        label='Спосіб оплати',
        choices=Order.PAYMENT_CHOICES,
        initial='cash',
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
    )

    notes = forms.CharField(
        label='Коментар до замовлення',
        required=False,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Додаткова інформація для курʼєра...',
            }
        ),
    )

    agree_terms = forms.BooleanField(
        label='Я погоджуюсь з умовами доставки та оплати',
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    def __init__(self, *args, delivery_methods=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Queryset задаємо в конструкторі, а не в оголошенні поля: інакше
        # список тарифів зафіксувався б на момент імпорту модуля, і новий
        # спосіб доставки з адмінки не зʼявився б до перезапуску процесу.
        if delivery_methods is not None:
            self.fields['delivery_method'].queryset = delivery_methods
            # Доставка не має бути обовʼязковим вибором, якщо тарифів немає
            # взагалі — інакше checkout стає непрохідним.
            self.fields['delivery_method'].required = delivery_methods.exists()


class CouponForm(forms.Form):
    """Введення промокоду."""

    code = forms.CharField(
        label='Промокод',
        max_length=32,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'Промокод',
                'autocapitalize': 'characters',
                'autocomplete': 'off',
                'aria-label': 'Промокод',
            }
        ),
    )

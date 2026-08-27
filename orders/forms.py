"""Форми checkout-процесу."""

from django import forms

from .models import Order, ShippingAddress


class ShippingAddressForm(forms.ModelForm):
    """Форма адреси доставки з Bootstrap-класами."""

    class Meta:
        model = ShippingAddress
        fields = [
            'full_name', 'phone', 'country', 'city',
            'postal_code', 'address_line1', 'address_line2',
            'is_default',
        ]
        widgets = {
            'full_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Прізвище Ім\'я По батькові',
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+380...',
            }),
            'country': forms.TextInput(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Місто',
            }),
            'postal_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '01001',
            }),
            'address_line1': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Вулиця, будинок, квартира',
            }),
            'address_line2': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Додаткова інформація (необов\'язково)',
            }),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        optional = {'address_line2', 'is_default'}
        for field_name, field in self.fields.items():
            if field_name not in optional:
                field.required = True


class OrderCheckoutForm(forms.Form):
    """Фінальне підтвердження замовлення: спосіб оплати та коментар."""

    payment_method = forms.ChoiceField(
        label='Спосіб оплати',
        choices=Order.PAYMENT_CHOICES,
        initial='cash',
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
    )

    notes = forms.CharField(
        label='Коментар до замовлення',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Додаткова інформація для кур\'єра...',
        }),
    )

    agree_terms = forms.BooleanField(
        label='Я погоджуюсь з умовами доставки та оплати',
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

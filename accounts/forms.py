"""Форми реєстрації та редагування кабінету."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import UserProfile

User = get_user_model()

# Клас із дизайн-системи, а не з Bootstrap: `.field__control` — це
# компонент поля з `components.css`. Через цей один словник системний
# вигляд отримують усі форми проєкту — вхід, реєстрація, кабінет і
# checkout, — бо всі вони рендерять `{{ field }}`.
SYSTEM_INPUT = {'class': 'field__control'}


class SignUpForm(UserCreationForm):
    """Реєстрація з обов'язковим email — на нього підуть листи про замовлення."""

    email = forms.EmailField(
        label='Email',
        required=True,
        widget=forms.EmailInput(attrs={**SYSTEM_INPUT, 'type': 'email', 'autocomplete': 'email'}),
    )
    phone = forms.CharField(
        label='Телефон',
        required=False,
        widget=forms.TextInput(
            attrs={
                **SYSTEM_INPUT,
                'type': 'tel',
                'autocomplete': 'tel',
                'placeholder': '+380...',
            }
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ['username', 'email', 'phone']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'field__control')

    def clean_email(self):
        """Email унікальний на рівні моделі — тут даємо людське повідомлення."""
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                'Користувач з таким email вже зареєстрований. '
                'Увійдіть або скористайтесь відновленням пароля.'
            )
        return email


class UserAccountForm(forms.ModelForm):
    """Контактні дані, які живуть на самій моделі користувача."""

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'is_subscribed']
        widgets = {
            'first_name': forms.TextInput(attrs={**SYSTEM_INPUT, 'autocomplete': 'given-name'}),
            'last_name': forms.TextInput(attrs={**SYSTEM_INPUT, 'autocomplete': 'family-name'}),
            # type='email' і type='tel' піднімають правильну клавіатуру на
            # мобільному і вмикають автозаповнення браузера.
            'email': forms.EmailInput(
                attrs={**SYSTEM_INPUT, 'type': 'email', 'autocomplete': 'email'}
            ),
            'phone': forms.TextInput(
                attrs={
                    **SYSTEM_INPUT,
                    'type': 'tel',
                    'autocomplete': 'tel',
                    'placeholder': '+380...',
                }
            ),
            'is_subscribed': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_email(self):
        email = self.cleaned_data['email']
        taken = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if taken.exists():
            raise forms.ValidationError('Цей email вже належить іншому акаунту')
        return email


class UserProfileForm(forms.ModelForm):
    """Те, що наповнює кабінет: дата народження, аватар, смаки.

    Адреси тут немає: дефолтну задає сам `ShippingAddress.is_default`,
    і дублювати цей факт у профілі означало б рано чи пізно їх розсинхронити.
    """

    class Meta:
        model = UserProfile
        fields = ['date_of_birth', 'avatar', 'favourite_family']
        widgets = {
            'date_of_birth': forms.DateInput(attrs={**SYSTEM_INPUT, 'type': 'date'}),
            'avatar': forms.ClearableFileInput(attrs={'class': 'field__control'}),
            'favourite_family': forms.Select(attrs={'class': 'field__control'}),
        }

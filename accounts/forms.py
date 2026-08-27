"""Форми реєстрації та редагування профілю."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import UserProfile

User = get_user_model()

BOOTSTRAP_INPUT = {'class': 'form-control'}


class SignUpForm(UserCreationForm):
    """Реєстрація з обов'язковим email — на нього підуть листи про замовлення."""

    email = forms.EmailField(
        label='Email',
        required=True,
        widget=forms.EmailInput(attrs=BOOTSTRAP_INPUT),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ['username', 'email']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Користувач з таким email вже зареєстрований')
        return email


class UserProfileForm(forms.ModelForm):
    """Редагування додаткових полів профілю."""

    class Meta:
        model = UserProfile
        fields = ['phone', 'date_of_birth']
        widgets = {
            'phone': forms.TextInput(attrs={**BOOTSTRAP_INPUT, 'placeholder': '+380...'}),
            'date_of_birth': forms.DateInput(attrs={**BOOTSTRAP_INPUT, 'type': 'date'}),
        }

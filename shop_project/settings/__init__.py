"""Пакет налаштувань проєкту.

Навмисно порожній: конкретний модуль обирається через змінну оточення
`DJANGO_SETTINGS_MODULE`, а не імпортом за замовчуванням.

    shop_project.settings.dev    — розробка (дефолт у manage.py/wsgi.py/asgi.py)
    shop_project.settings.prod   — production

Спільна частина живе в `base.py` і сама по собі не використовується.
"""

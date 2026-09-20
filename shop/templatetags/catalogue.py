"""Теги каталогу: робота з рядком запиту і формат ціни.

Без них пагінація і сортування губили б активні фільтри: перехід на другу
сторінку скидав би вибраний бренд, а зміна сортування — пошуковий запит.
"""

from django import template

from cart.services import format_amount, format_price

register = template.Library()


@register.simple_tag(takes_context=True)
def query_string(context, **updates):
    """Поточний рядок запиту зі зміненими параметрами.

    `{% query_string page=2 %}` → `?q=ірис&brand=vestige&page=2`.
    Значення `None` прибирає параметр — так працює скидання фільтра.
    """
    params = context['request'].GET.copy()

    for key, value in updates.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value

    # Сторінка завжди скидається при зміні фільтрів: інакше можна опинитись
    # на сьомій сторінці вибірки, у якій тепер дві.
    if 'page' not in updates:
        params.pop('page', None)

    encoded = params.urlencode()
    return f'?{encoded}' if encoded else ''


@register.simple_tag(takes_context=True)
def toggle_param(context, key, value):
    """Рядок запиту з доданим або прибраним значенням багатозначного фільтра.

    Саме так поводяться чекбокси брендів і нот: клік вмикає, повторний вимикає.
    """
    params = context['request'].GET.copy()
    current = params.getlist(key)
    value = str(value)

    if value in current:
        current.remove(value)
    else:
        current.append(value)

    params.setlist(key, current)
    params.pop('page', None)

    encoded = params.urlencode()
    return f'?{encoded}' if encoded else ''


@register.filter
def plural(value, forms):
    """Українська множина: «1 аромат, 2 аромати, 5 ароматів».

    Вбудований `pluralize` знає лише дві форми й на трьох тихо віддає
    порожній рядок — через це в каталозі стояло «Знайдено 30» без слова,
    а на сторінці товару «Стійкість 6» без «годин».
    """
    try:
        one, few, many = (form.strip() for form in str(forms).split(','))
        number = abs(int(value))
    except (TypeError, ValueError):
        return ''

    if number % 100 in range(11, 15):
        return many
    if number % 10 == 1:
        return one
    if number % 10 in (2, 3, 4):
        return few
    return many


@register.filter
def money(value):
    """Ціна в єдиному форматі сайту: «4 200 ₴».

    Символ валюти фільтр додає сам — у шаблоні після `|money` нічого
    дописувати не треба. Доти дописували руками, і пробіл перед ₴
    виходив звичайний — гривня відривалась від числа переносом рядка.

    Реалізація одна на весь проєкт — `cart.services.format_price`, та сама,
    якою кошик відповідає на fetch: інакше сторінка й drawer знову
    розійшлись би в розрядці.
    """
    return format_price(value)


@register.filter
def money_amount(value):
    """Те саме число, але без символа валюти: «4 200».

    Потрібне тільки там, де ₴ уже стоїть у заголовку колонки — у
    PDF-рахунку це «Ціна, ₴». Усюди інде беремо `money`, інакше гривня
    просто зникне з екрана.
    """
    return format_amount(value)

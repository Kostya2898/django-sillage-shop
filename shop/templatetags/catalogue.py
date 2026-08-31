"""Теги каталогу: робота з рядком запиту.

Без них пагінація і сортування губили б активні фільтри: перехід на другу
сторінку скидав би вибраний бренд, а зміна сортування — пошуковий запит.
"""

from django import template

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
def money(value):
    """Ціна з нерозривними пробілами між тисячами: 4 200 ₴."""
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return value
    return f'{number:,}'.replace(',', ' ')

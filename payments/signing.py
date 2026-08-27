"""Підпис платіжних транзакцій.

Мок-шлюз повертає користувача назад звичайним GET-редіректом, і без підпису
будь-хто міг би просто відкрити `/payments/callback/?status=successful&tx_ref=…`
і зробити своє замовлення оплаченим. Підпис прибиває результат до конкретної
транзакції та її суми.

У справжньому інтегруванні цю роль виконує або підпис провайдера (Flutterwave
`verif-hash`, LiqPay `signature`), або окремий verify-запит до його API.
Формула тут навмисно найпростіша з робочих — HMAC-SHA256 на `PAYMENT_SECRET_KEY`.
"""

import hashlib
import hmac

from django.conf import settings


def transaction_signature(tx_ref, amount, currency):
    """HMAC-SHA256 від трійки (референс, сума, валюта).

    Сума нормалізується до двох знаків, щоб `1000` і `1000.00` давали однаковий
    підпис — інакше він залежав би від того, як Decimal дістався з бази.
    """
    payload = f'{tx_ref}:{amount:.2f}:{currency}'
    return hmac.new(
        settings.PAYMENT_SECRET_KEY.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def signature_is_valid(signature, tx_ref, amount, currency):
    """Звірити підпис за сталий час.

    `compare_digest`, а не `==`: звичайне порівняння рядків виходить на першій
    відмінності, і за часом відповіді підпис можна підбирати побайтово.
    """
    if not signature:
        return False

    expected = transaction_signature(tx_ref, amount, currency)
    return hmac.compare_digest(expected, signature)

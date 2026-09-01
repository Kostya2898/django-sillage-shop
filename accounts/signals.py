"""Сигнали застосунку accounts."""

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver

from cart.cart import merge_carts
from orders.services import attach_guest_orders

from .models import UserProfile

User = get_user_model()


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Кожному новому користувачу автоматично створюємо профіль."""
    if created:
        UserProfile.objects.get_or_create(user=instance)


@receiver(post_save, sender=User)
def claim_guest_orders(sender, instance, created, **kwargs):
    """Купував гостем, потім зареєструвався — замовлення стають його.

    Інакше історія покупок починалася б з нуля саме тоді, коли людина вперше
    вирішила завести акаунт, і перше ж «а де моє замовлення?» йшло б у підтримку.
    """
    if created:
        attach_guest_orders(instance)


@receiver(user_logged_in)
def merge_session_cart_into_database(sender, request, user, **kwargs):
    """Гість поклав товари в кошик і залогінився — переносимо їх у базу."""
    merge_carts(request, user=user)

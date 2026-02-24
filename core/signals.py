from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User, Buyer, Seller

@receiver(post_save, sender=User)
def ensure_profiles(sender, instance: User, created, **kwargs):
    if created:
        if instance.role == 'Buyer':
            Buyer.objects.get_or_create(user=instance)
        elif instance.role == 'Seller':
            Seller.objects.get_or_create(user=instance)
    else:
        # Always ensure the active role profile exists after updates
        if instance.role == 'Buyer':
            Buyer.objects.get_or_create(user=instance)
        else:
            Seller.objects.get_or_create(user=instance)

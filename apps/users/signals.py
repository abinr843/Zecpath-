import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings

from .models import CustomUser, Candidate, Employer

logger = logging.getLogger(__name__)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    logger.info(
        "SIGNAL FIRED: User %s | Created: %s | Role: %s",
        instance.email, created, instance.role,
    )

    if created:
        # Force the role into a pure string, remove hidden spaces, and make it uppercase
        safe_role = str(instance.role).strip().upper()

        if safe_role == 'EMPLOYER':
            Employer.objects.create(user=instance)
            logger.info("SUCCESS: Employer Profile Auto-Generated!")
        elif safe_role == 'CANDIDATE':
            Candidate.objects.create(user=instance)
            logger.info("SUCCESS: Candidate Profile Auto-Generated!")
        else:
            logger.error("ERROR: No matching role found for '%s'", safe_role)

def save_profile(sender, instance, **kwargs):
    if instance.role == 'employer'and hasattr(instance, 'employer'):
        instance.Employer.save()
    if instance.role == 'candidate'and hasattr(instance, 'candidate'):
        instance.Candidate.save()

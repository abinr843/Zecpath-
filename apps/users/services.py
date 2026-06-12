import logging

from django.db import transaction
from django.core.mail import send_mail
from django.conf import settings

from .models import CustomUser, Candidate, Employer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Email helpers (stubs — swap in a real provider later)
# ---------------------------------------------------------------------------

def send_welcome_email(user):
    """
    Sends a welcome email to a newly registered user.
    Currently a stub that logs the action; replace the body with
    a real email backend (SendGrid, SES, etc.) when ready.
    """
    try:
        send_mail(
            subject="Welcome to ZecPath!",
            message=f"Hi {user.username}, thanks for joining ZecPath.",
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@zecpath.com'),
            recipient_list=[user.email],
            fail_silently=True,
        )
        logger.info("Welcome email queued for %s", user.email)
    except Exception as exc:
        # Never let an email failure break the registration flow
        logger.warning("Welcome email failed for %s: %s", user.email, exc)


# ---------------------------------------------------------------------------
# Account-creation services
# ---------------------------------------------------------------------------

def create_candidate_account(registration_payload: dict) -> Candidate:
    """
    Create a User with the CANDIDATE role and return the linked
    Candidate profile.

    The post_save signal in signals.py auto-creates the Candidate row,
    so we only need to create the user here and then refresh/update the
    profile with any extra fields the caller provided.
    """
    with transaction.atomic():
        # 1. Create the base user (triggers post_save → Candidate created)
        user = CustomUser.objects.create_user(
            username=registration_payload['username'],
            email=registration_payload['email'],
            password=registration_payload['password'],
            role='CANDIDATE',
        )

        # 2. Grab the auto-created profile and patch in optional extras
        candidate = user.candidate
        profile_fields = {
            'headline', 'bio', 'skills', 'languages', 'education',
            'experience_years', 'expected_salary', 'location',
            'willing_to_relocate', 'portfolio_url', 'github_url',
            'linkedin_url',
        }
        updated = False
        for field in profile_fields:
            if field in registration_payload:
                setattr(candidate, field, registration_payload[field])
                updated = True
        if updated:
            candidate.save()

    # 3. Fire-and-forget welcome email (outside the transaction)
    send_welcome_email(user)

    return candidate


def create_employer_account(registration_payload: dict) -> Employer:
    """
    Create a User with the EMPLOYER role and return the linked
    Employer profile.

    Works identically to create_candidate_account — the signal
    auto-creates the Employer row.
    """
    with transaction.atomic():
        # 1. Create the base user (triggers post_save → Employer created)
        user = CustomUser.objects.create_user(
            username=registration_payload['username'],
            email=registration_payload['email'],
            password=registration_payload['password'],
            role='EMPLOYER',
        )

        # 2. Grab the auto-created profile and patch in optional extras
        employer = user.employer
        profile_fields = {
            'company_name', 'description', 'industry', 'company_size',
            'established_year', 'headquarters', 'domain',
            'linkedin_url', 'twitter_url',
        }
        updated = False
        for field in profile_fields:
            if field in registration_payload:
                setattr(employer, field, registration_payload[field])
                updated = True
        if updated:
            employer.save()

    # 3. Fire-and-forget welcome email (outside the transaction)
    send_welcome_email(user)

    return employer
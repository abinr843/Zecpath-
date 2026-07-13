import logging

from django.db import transaction
from rest_framework.exceptions import ValidationError

from .models import Application
from .validators import validate_job_is_active, validate_application_deadline, validate_no_duplicate_application

logger = logging.getLogger(__name__)

# ─── Lazy import helpers to avoid circular imports ────
def _get_email_helpers():
    from .tasks import send_application_submitted_email, send_status_change_email
    return send_application_submitted_email, send_status_change_email


def process_new_application(candidate, job, cover_letter=None):
    """
    Single source of truth for creating a job application.

    This function encapsulates ALL business logic for the apply flow:
      1. Validates the job is active
      2. Validates the application deadline hasn't passed
      3. Validates the candidate hasn't already applied (duplicate prevention)
      4. Validates the candidate has a master resume uploaded
      5. Snapshots the candidate's current resume URL
      6. Creates the Application record atomically

    Raises rest_framework.exceptions.ValidationError on any failure
    so the view can return a clean 400 response.

    Future: Step 7 — Trigger ATS resume scoring engine here.
    """
    # 1. Job must be active
    validate_job_is_active(job)

    # 2. Deadline must not have passed
    validate_application_deadline(job)

    # 3. No duplicate applications
    validate_no_duplicate_application(candidate, job)

    # 4. Candidate must have a resume on file
    if not candidate.master_resume:
        raise ValidationError(
            {"non_field_errors": ["You must upload a master resume to your profile before applying for jobs."]}
        )

    # 5. Snapshot the resume URL at time of application
    resume_url = candidate.master_resume.url

    # 6. Create the application atomically
    with transaction.atomic():
        application = Application.objects.create(
            candidate=candidate,
            job=job,
            status='applied',
            resume_snapshot=resume_url,
            cover_letter=cover_letter or '',
        )

    logger.info(
        "Application created: %s -> %s (id=%d)",
        candidate.user.email, job.title, application.id,
    )

    # 7. Send immediate "Application Received" confirmation email
    try:
        send_submitted, _ = _get_email_helpers()
        send_submitted(application)
        logger.info("Queued application-submitted email for application %d", application.id)
    except Exception as exc:
        logger.exception("Failed to queue confirmation email for application %d: %s", application.id, exc)

    # 8. Trigger ATS scoring engine via Background Task (Celery)
    #    15-second countdown so ATS processing feels realistic
    try:
        from .tasks import process_application_ats_task
        process_application_ats_task.apply_async(args=[application.id], countdown=15)
        logger.info("Handed ATS scoring ticket to Celery (countdown=15s) for application %d", application.id)
    except Exception as exc:
        logger.exception("Failed to dispatch Celery task for application %d: %s", application.id, exc)

    return application


VALID_TRANSITIONS = {
    'applied': ['under_review', 'shortlisted', 'rejected'],
    'under_review': ['shortlisted', 'rejected', 'interviewing'],
    'shortlisted': ['ready_for_interview', 'interviewing', 'rejected', 'offered'],
    'ready_for_interview': ['interviewing', 'not_picked_up', 'rejected'],
    'interviewing': ['interview_completed', 'offered', 'rejected', 'not_picked_up'],
    'interview_completed': ['offered', 'hired', 'rejected'],
    'not_picked_up': ['ready_for_interview', 'rejected'],
    'offered': ['hired', 'rejected'],
    'hired': [],
    'rejected': ['shortlisted', 'under_review']
}

def update_application_status(application, new_status, user, notes=''):
    """
    Enforce ATS State Machine rules and log the activity.
    """
    old_status = application.status

    # Check if this is just a notes update without a status change
    if old_status == new_status:
        if notes and notes != application.employer_notes:
            with transaction.atomic():
                application.employer_notes = notes
                application.save(update_fields=['employer_notes'])
                from .models import ApplicationLog
                ApplicationLog.objects.create(
                    application=application,
                    user=user,
                    old_status=old_status,
                    new_status=new_status,
                    notes=notes
                )
        return application

    # Allow manual override for rejected apps (Day 26)
    if old_status == 'hired':
        raise ValidationError(f"Cannot change status from terminal state: {old_status}")

    valid_next_states = VALID_TRANSITIONS.get(old_status, [])
    if new_status not in valid_next_states and old_status != new_status:
        raise ValidationError(f"Invalid transition from {old_status} to {new_status}")

    # Apply changes atomically
    with transaction.atomic():
        application.status = new_status
        if notes is not None:
            application.employer_notes = notes
        
        application.save(update_fields=['status', 'employer_notes'])

        from .models import ApplicationLog
        ApplicationLog.objects.create(
            application=application,
            user=user,
            old_status=old_status,
            new_status=new_status,
            notes=notes
        )

    logger.info(
        "Application %d status updated: %s -> %s by user %s",
        application.id, old_status, new_status, user.email if user else "SYSTEM",
    )

    # ─── Trigger email notification for manual employer status changes ───
    # Only send if a real user (not SYSTEM) triggered the change
    if user and new_status in ('shortlisted', 'rejected', 'under_review'):
        try:
            _, send_change = _get_email_helpers()
            send_change(application, new_status)
            logger.info(
                "Queued %s email for application %d (manual action by %s)",
                new_status, application.id, user.email,
            )
        except Exception as exc:
            logger.exception(
                "Failed to queue %s email for application %d: %s",
                new_status, application.id, exc,
            )

    # ─── Trigger Telephony Gatekeeper when status → ready_for_interview ───
    if new_status == 'ready_for_interview':
        try:
            from .telephony_gatekeeper import trigger_gatekeeper_for_application
            trigger_gatekeeper_for_application(application, triggered_by_user=user)
            logger.info(
                "Telephony gatekeeper triggered for application %d",
                application.id,
            )
        except Exception as exc:
            logger.exception(
                "Telephony gatekeeper failed for application %d: %s",
                application.id, exc,
            )

    return application
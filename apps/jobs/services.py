import logging

from django.db import transaction
from rest_framework.exceptions import ValidationError

from .models import Application
from .validators import validate_job_is_active, validate_application_deadline, validate_no_duplicate_application

logger = logging.getLogger(__name__)


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

    # 7. (Placeholder) Trigger ATS scoring engine here later

    return application
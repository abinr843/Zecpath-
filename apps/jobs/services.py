from django.core.exceptions import ValidationError
from .models import *


def process_new_application(candidate, job):
    """
    Handles the business logic of submitting a job application.
    Future: This is where we will trigger the ATS resume parsing module.
    """
    # 1. Check if they already applied
    if Application.objects.filter(candidate=candidate, job=job).exists():
        raise ValidationError("This candidate has already applied for this job.")

    # 2. Create the application
    application = Application.objects.create(
        candidate=candidate,
        job=job,
        status='applied'
    )

    # 3. (Placeholder) Trigger ATS scoring engine here later

    return application
from django.utils import timezone
from rest_framework import serializers
from apps.jobs.models import Application


def validate_job_is_active(job):
    """
    Ensure the job is active and can accept applications.
    """
    if job and not job.is_active:
        raise serializers.ValidationError({"job": "This job is no longer active and cannot accept new applications."})


def validate_application_deadline(job):
    """
    Ensure the application deadline has not passed.
    If the job has no deadline set, applications are always accepted.
    """
    if job and job.application_deadline:
        if timezone.now().date() > job.application_deadline:
            raise serializers.ValidationError(
                {"job": f"The application deadline ({job.application_deadline.strftime('%B %d, %Y')}) has passed."}
            )


def validate_no_duplicate_application(candidate, job):
    """
    Ensure the candidate hasn't already applied to this job.
    """
    if Application.objects.filter(candidate=candidate, job=job).exists():
        raise serializers.ValidationError({"non_field_errors": ["You have already applied for this job."]})

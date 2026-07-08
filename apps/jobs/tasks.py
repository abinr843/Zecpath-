import logging
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from .models import Application, Job
from .utils.ats_engine import calculate_ats_score
from apps.jobs.services import update_application_status

logger = logging.getLogger(__name__)

@shared_task
def process_application_ats_task(application_id):
    """
    Background worker task to compute ATS score, apply threshold logic,
    and trigger auto-actions (State Machine).
    """
    try:
        application = Application.objects.select_related('candidate__user', 'job').get(id=application_id)
    except Application.DoesNotExist:
        logger.error(f"Application {application_id} not found.")
        return

    candidate = application.candidate
    job = application.job

    logger.info(f"Starting ATS processing for Application {application_id} ({candidate.user.email})")

    # 1. Compute Score
    try:
        score, details = calculate_ats_score(candidate, job)
        application.match_score = score
        application.match_details = details
        application.save(update_fields=['match_score', 'match_details'])
        logger.info(f"Calculated Score: {score}% for Application {application_id}")
    except Exception as exc:
        logger.exception(f"Failed to calculate ATS score for Application {application_id}: {exc}")
        return

    # 2. Evaluate Threshold Logic & State Machine
    new_status = None
    reason = ""

    # A) Absolute Dealbreaker check
    if job.must_have_skills:
        required_list = [s.strip().lower() for s in job.must_have_skills.split(',') if s.strip()]
        # check what skills the candidate actually has based on the matched list or candidate profile
        # For simplicity, we check if the required skills are in the matched list from the ATS details
        matched_skills = [s.lower() for s in details.get('skills', {}).get('matched', [])]
        missing_dealbreakers = [s for s in required_list if s not in matched_skills]
        
        if missing_dealbreakers:
            new_status = 'rejected'
            reason = f"Missing absolute dealbreakers: {', '.join(missing_dealbreakers)}"
            
    # B) Auto-Reject Threshold Check
    if not new_status and job.auto_reject_threshold is not None:
        if score < job.auto_reject_threshold:
            new_status = 'rejected'
            reason = f"Score {score}% is below auto-reject threshold of {job.auto_reject_threshold}%"

    # C) Auto-Shortlist Threshold Check
    if not new_status and job.auto_shortlist_threshold is not None:
        if score >= job.auto_shortlist_threshold:
            new_status = 'shortlisted'
            reason = f"Score {score}% meets/exceeds auto-shortlist threshold of {job.auto_shortlist_threshold}%"

    # 3. Auto Actions (Update Status & Notify)
    if new_status:
        logger.info(f"Auto-action triggered for Application {application_id}: {new_status} (Reason: {reason})")
        try:
            # We pass a None user because it's a system action. update_application_status handles this.
            # Assuming update_application_status allows system updates.
            update_application_status(
                application=application,
                new_status=new_status,
                user=None, # System action
                notes=f"SYSTEM AUTO-ACTION: {reason}"
            )
            
            # Send Automated Email
            _send_status_email(application, new_status)
        except Exception as exc:
            logger.exception(f"Failed to apply auto-action for Application {application_id}: {exc}")


def _send_status_email(application, status):
    """
    Sends an automated email to the candidate when an auto-action triggers a status change.
    """
    candidate_email = application.candidate.user.email
    candidate_name = application.candidate.user.first_name
    job_title = application.job.title
    company_name = application.job.employer.company_name
    
    if status == 'rejected':
        subject = f"Update on your application for {job_title} at {company_name}"
        message = f"Hi {candidate_name},\n\nThank you for applying for the {job_title} role at {company_name}.\n\nAfter reviewing your application, we have decided to move forward with other candidates at this time. We appreciate your interest and wish you the best in your job search.\n\nBest regards,\nThe {company_name} Team"
    elif status == 'shortlisted':
        subject = f"Good news! You've been shortlisted for {job_title} at {company_name}"
        message = f"Hi {candidate_name},\n\nWe are excited to let you know that you have been shortlisted for the {job_title} role at {company_name}!\n\nOur team was very impressed by your background. We will be in touch soon with the next steps.\n\nBest regards,\nThe {company_name} Team"
    else:
        return

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[candidate_email],
            fail_silently=False,
        )
        logger.info(f"Sent {status} email to {candidate_email}")
    except Exception as exc:
        logger.error(f"Failed to send {status} email to {candidate_email}: {exc}")

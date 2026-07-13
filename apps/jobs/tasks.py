import logging
from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone

from .models import Application, Job, EmailLog
from .utils.ats_engine import calculate_ats_score

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 1. Generic Async Email Task (with retries)
# ──────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_async_email_task(self, email_log_id):
    """
    Sends an email tracked by an EmailLog record.
    Retries up to 3 times on failure (30-second backoff).
    Updates the EmailLog status to 'sent' or 'failed'.
    """
    try:
        email_log = EmailLog.objects.get(id=email_log_id)
    except EmailLog.DoesNotExist:
        logger.error(f"EmailLog {email_log_id} not found. Aborting.")
        return

    try:
        # Build the email with both HTML and plain-text parts
        msg = EmailMultiAlternatives(
            subject=email_log.subject,
            body=email_log.body,  # plain-text fallback
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email_log.recipient_email],
        )

        # If we have an HTML body, try to render it from the template
        html_body = _render_html_template(email_log)
        if html_body:
            msg.attach_alternative(html_body, "text/html")

        msg.send(fail_silently=False)

        # ✅ Success
        email_log.status = 'sent'
        email_log.save(update_fields=['status', 'updated_at'])
        logger.info(f"✅ Email sent: [{email_log.email_type}] → {email_log.recipient_email}")

    except Exception as exc:
        email_log.retry_count = self.request.retries
        email_log.error_message = str(exc)

        if self.request.retries < self.max_retries:
            # Save partial state and retry
            email_log.save(update_fields=['retry_count', 'error_message', 'updated_at'])
            logger.warning(
                f"⚠️ Email send failed (attempt {self.request.retries + 1}/{self.max_retries}): "
                f"{email_log.recipient_email} — {exc}. Retrying..."
            )
            raise self.retry(exc=exc)
        else:
            # ❌ All retries exhausted
            email_log.status = 'failed'
            email_log.save(update_fields=['status', 'retry_count', 'error_message', 'updated_at'])
            logger.error(
                f"❌ Email permanently failed after {self.max_retries} retries: "
                f"[{email_log.email_type}] → {email_log.recipient_email} — {exc}"
            )


def _render_html_template(email_log):
    """
    Attempts to render the HTML email template for the given email type.
    Returns the rendered HTML string or None if no template exists.
    """
    template_map = {
        'application_submitted': 'emails/application_submitted.html',
        'shortlisted': 'emails/application_shortlisted.html',
        'rejected': 'emails/application_rejected.html',
        'under_review': 'emails/application_under_review.html',
        'welcome': 'emails/welcome.html',
    }

    template_name = template_map.get(email_log.email_type)
    if not template_name:
        return None

    # Build context from the related application
    context = {}
    if email_log.application:
        app = email_log.application
        context = {
            'candidate_name': app.candidate.user.first_name or app.candidate.user.email,
            'job_title': app.job.title,
            'company_name': app.job.employer.company_name,
            'applied_date': app.applied_on.strftime('%B %d, %Y') if app.applied_on else 'N/A',
        }
    elif email_log.email_type == 'welcome':
        # Welcome emails don't have an application
        context = {
            'user_name': email_log.recipient_email.split('@')[0],
        }

    try:
        return render_to_string(template_name, context)
    except Exception as exc:
        logger.warning(f"Could not render HTML template {template_name}: {exc}")
        return None


# ──────────────────────────────────────────────
# 2. Email Dispatch Helpers
# ──────────────────────────────────────────────

def dispatch_email(application, email_type, subject, body_text, recipient_email=None):
    """
    Creates an EmailLog record (status=pending) and queues the
    send_async_email_task via Celery.
    """
    to_email = recipient_email or application.candidate.user.email
    email_log = EmailLog.objects.create(
        application=application,
        recipient_email=to_email,
        subject=subject,
        body=body_text,
        email_type=email_type,
        status='pending',
    )
    send_async_email_task.delay(email_log.id)
    logger.info(f"📧 Queued email [{email_type}] → {to_email} (log_id={email_log.id})")
    return email_log


def send_application_submitted_email(application):
    """Dispatches the 'Application Submitted' confirmation email."""
    candidate_name = application.candidate.user.first_name or application.candidate.user.email
    job_title = application.job.title
    company_name = application.job.employer.company_name

    subject = f"Application received — {job_title} at {company_name}"
    body = render_to_string('emails/application_submitted.txt', {
        'candidate_name': candidate_name,
        'job_title': job_title,
        'company_name': company_name,
        'applied_date': timezone.now().strftime('%B %d, %Y'),
    })
    dispatch_email(application, 'application_submitted', subject, body)


def send_status_change_email(application, new_status):
    """
    Dispatches shortlisted / under_review / rejected emails.
    Called by both the ATS auto-action system and manual employer actions.
    """
    candidate_name = application.candidate.user.first_name or application.candidate.user.email
    job_title = application.job.title
    company_name = application.job.employer.company_name

    template_config = {
        'shortlisted': {
            'subject': f"Good news! You've been shortlisted for {job_title} at {company_name}",
            'txt_template': 'emails/application_shortlisted.txt',
        },
        'rejected': {
            'subject': f"Update on your application for {job_title} at {company_name}",
            'txt_template': 'emails/application_rejected.txt',
        },
        'under_review': {
            'subject': f"Your application for {job_title} at {company_name} is under review",
            'txt_template': 'emails/application_under_review.txt',
        },
    }

    config = template_config.get(new_status)
    if not config:
        return  # No email for other status transitions

    body = render_to_string(config['txt_template'], {
        'candidate_name': candidate_name,
        'job_title': job_title,
        'company_name': company_name,
    })
    dispatch_email(application, new_status, config['subject'], body)


def send_welcome_email_async(user):
    """
    Sends a welcome email to a newly registered user via the async pipeline.
    Creates an EmailLog and dispatches via Celery.
    """
    subject = "Welcome to ZecPath! 🚀"
    user_name = user.first_name or user.username or user.email.split('@')[0]
    body = render_to_string('emails/welcome.txt', {
        'user_name': user_name,
    })

    email_log = EmailLog.objects.create(
        application=None,  # No application for welcome emails
        recipient_email=user.email,
        subject=subject,
        body=body,
        email_type='welcome',
        status='pending',
    )
    send_async_email_task.delay(email_log.id)
    logger.info(f"📧 Queued welcome email → {user.email} (log_id={email_log.id})")


# ──────────────────────────────────────────────
# 3. ATS Background Processing Task
# ──────────────────────────────────────────────

@shared_task
def process_application_ats_task(application_id):
    """
    Background worker task to compute ATS score, apply threshold logic,
    and trigger auto-actions (State Machine).

    Dispatched with countdown=15 so it fires ~15 seconds after submission.

    3-Tier Logic:
        - Score >= shortlist_threshold  →  shortlisted
        - Score < shortlist_threshold AND > reject_threshold  →  under_review
        - Score <= reject_threshold  →  rejected
    """
    # Lazy import to avoid circular imports
    from apps.jobs.services import update_application_status

    try:
        application = Application.objects.select_related('candidate__user', 'job__employer').get(id=application_id)
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

    # 2. Evaluate Threshold Logic & State Machine (3-Tier)
    new_status = None
    reason = ""

    # A) Absolute Dealbreaker check
    if job.must_have_skills:
        required_list = [s.strip().lower() for s in job.must_have_skills.split(',') if s.strip()]
        matched_skills = [s.lower() for s in details.get('skills', {}).get('matched', [])]
        missing_dealbreakers = [s for s in required_list if s not in matched_skills]

        if missing_dealbreakers:
            new_status = 'rejected'
            reason = f"Missing absolute dealbreakers: {', '.join(missing_dealbreakers)}"

    # B) 3-Tier Threshold Logic (only if not already rejected by dealbreakers)
    if not new_status:
        shortlist_threshold = job.auto_shortlist_threshold
        reject_threshold = job.auto_reject_threshold

        if shortlist_threshold is not None and score >= shortlist_threshold:
            # Score meets/exceeds shortlist threshold → shortlisted
            new_status = 'shortlisted'
            reason = f"Score {score}% meets/exceeds auto-shortlist threshold of {shortlist_threshold}%"
        elif reject_threshold is not None and score <= reject_threshold:
            # Score at or below reject threshold → rejected
            new_status = 'rejected'
            reason = f"Score {score}% is at or below auto-reject threshold of {reject_threshold}%"
        elif shortlist_threshold is not None and reject_threshold is not None:
            # Score between reject and shortlist thresholds → under_review
            new_status = 'under_review'
            reason = f"Score {score}% is between reject threshold ({reject_threshold}%) and shortlist threshold ({shortlist_threshold}%) — needs manual review"
        elif shortlist_threshold is not None and score < shortlist_threshold:
            # Only shortlist threshold set, score below it → under_review
            new_status = 'under_review'
            reason = f"Score {score}% is below shortlist threshold of {shortlist_threshold}% — needs manual review"
        elif reject_threshold is not None and score > reject_threshold:
            # Only reject threshold set, score above it → under_review
            new_status = 'under_review'
            reason = f"Score {score}% is above reject threshold of {reject_threshold}% — needs manual review"

    # 3. Auto Actions (Update Status & Send Email)
    if new_status:
        logger.info(f"Auto-action triggered for Application {application_id}: {new_status} (Reason: {reason})")
        try:
            update_application_status(
                application=application,
                new_status=new_status,
                user=None,  # System action
                notes=f"SYSTEM AUTO-ACTION: {reason}"
            )

            # Send email via the async email pipeline
            send_status_change_email(application, new_status)
        except Exception as exc:
            logger.exception(f"Failed to apply auto-action for Application {application_id}: {exc}")


# ──────────────────────────────────────────────
# 4. AI Interview Call Tasks (Twilio + Groq)
# ──────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def schedule_ai_interview_task(self, session_id):
    """
    Initiates an outbound Twilio call for an AI interview session.

    Workflow:
        1. Load the InterviewSession
        2. Check if scheduled_time has arrived
        3. Call the candidate via Twilio
        4. Store the call_sid on the session
        5. On failure, retry with backoff
    """
    from apps.jobs.models import InterviewSession

    try:
        session = InterviewSession.objects.select_related(
            'application__candidate__user',
            'application__job__employer',
        ).get(id=session_id)
    except InterviewSession.DoesNotExist:
        logger.error(f"InterviewSession {session_id} not found.")
        return

    # Skip if session was already handled
    if session.status in ('completed', 'failed', 'not_picked_up', 'in_progress'):
        logger.info(f"Session {session_id} already in terminal state '{session.status}'. Skipping.")
        return

    candidate = session.application.candidate
    phone = candidate.user.phone

    if not phone or not phone.strip():
        session.status = 'failed'
        session.error_message = 'Candidate has no phone number.'
        session.save(update_fields=['status', 'error_message'])
        logger.error(f"❌ No phone for session {session_id}")
        return

    # Clean up the phone number
    phone = phone.strip().replace(' ', '')

    logger.info(
        f"📞 Initiating Twilio call for Session {session_id} "
        f"({candidate.user.email} → {session.application.job.title})"
    )

    try:
        from twilio.rest import Client
        from twilio.base.exceptions import TwilioRestException

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

        call = client.calls.create(
            to=phone,
            from_=settings.TWILIO_PHONE_NUMBER.strip().replace(' ', ''),
            url=f"{settings.NGROK_BASE_URL}/api/jobs/webhook/incoming/",
            status_callback=f"{settings.NGROK_BASE_URL}/api/jobs/webhook/twilio-status/",
            status_callback_event=['initiated', 'ringing', 'answered', 'completed'],
            status_callback_method='POST',
            method='POST',
            timeout=30,
        )

        # Store the call SID
        session.twilio_call_sid = call.sid
        session.status = 'in_progress'
        session.save(update_fields=['twilio_call_sid', 'status', 'updated_at'])

        logger.info(
            f"✅ Twilio call initiated: SID={call.sid} for Session {session_id}"
        )

    except Exception as exc:
        logger.exception(
            f"❌ Twilio call failed for Session {session_id}: {exc}"
        )

        session.retry_count += 1
        session.error_message = str(exc)

        if session.retry_count < session.max_retries:
            session.status = 'scheduled'
            session.save(update_fields=['status', 'retry_count', 'error_message', 'updated_at'])
            raise self.retry(exc=exc)
        else:
            session.status = 'failed'
            session.save(update_fields=['status', 'retry_count', 'error_message', 'updated_at'])


@shared_task
def process_interview_completion_task(session_id):
    """
    After an AI interview call completes, analyze the transcript
    using the AIBridgeService to generate a score and summary.
    """
    from apps.jobs.models import InterviewSession
    from apps.jobs.ai_bridge import AIBridgeService

    try:
        session = InterviewSession.objects.select_related(
            'application__candidate__user',
            'application__job',
        ).get(id=session_id)
    except InterviewSession.DoesNotExist:
        logger.error(f"InterviewSession {session_id} not found for scoring.")
        return

    if not session.transcript.strip():
        logger.warning(f"Empty transcript for Session {session_id}. Skipping scoring.")
        return

    ai_bridge = AIBridgeService()

    try:
        result_text = ai_bridge.score_interview(
            transcript=session.transcript,
            job_title=session.application.job.title,
            job_description=session.application.job.description
        )

        # Parse score and summary
        score = 0
        summary = result_text
        for line in result_text.split('\n'):
            if line.startswith('SCORE:'):
                try:
                    score = int(line.replace('SCORE:', '').strip())
                except ValueError:
                    score = 0
            elif line.startswith('SUMMARY:'):
                summary = line.replace('SUMMARY:', '').strip()

        session.ai_score = max(0, min(100, score))
        session.ai_summary = summary
        session.save(update_fields=['ai_score', 'ai_summary', 'updated_at'])

        # Store in application match_details
        existing = session.application.match_details or {}
        existing['ai_interview'] = {
            'score': session.ai_score,
            'summary': session.ai_summary,
            'call_duration': session.call_duration,
            'status': 'completed',
        }
        session.application.match_details = existing
        session.application.save(update_fields=['match_details'])

        logger.info(
            f"🧠 Interview scored: Session {session_id} → {score}/100"
        )

    except Exception as exc:
        logger.exception(f"Failed to score interview Session {session_id}: {exc}")


# ──────────────────────────────────────────────
# 5. Periodic / Cron Tasks (Celery Beat)
# ──────────────────────────────────────────────

@shared_task
def send_job_digest_task():
    """
    Celery Beat task — runs every Monday at 9 AM.
    Sends a digest of new jobs posted in the last 7 days to all active
    candidates who have opted in (all active candidates for now).
    """
    from datetime import timedelta
    from apps.users.models import Candidate

    one_week_ago = timezone.now() - timedelta(days=7)
    new_jobs = Job.objects.filter(
        is_active=True,
        created_at__gte=one_week_ago,
    ).order_by('-created_at')[:20]

    if not new_jobs.exists():
        logger.info("📭 No new jobs this week. Skipping digest.")
        return

    # Build the digest body
    job_lines = []
    for job in new_jobs:
        job_lines.append(
            f"• {job.title} at {job.employer.company_name} "
            f"({job.location_type}, {job.get_experience_level_display()})"
        )
    digest_body = (
        "Here are the latest jobs posted this week on ZecPath:\n\n"
        + "\n".join(job_lines)
        + "\n\nLog in to apply: https://zecpath.com/jobs"
    )

    # Send to all active candidates
    active_candidates = Candidate.objects.filter(
        is_active=True,
    ).select_related('user')

    queued_count = 0
    for candidate in active_candidates:
        email_log = EmailLog.objects.create(
            application=None,
            recipient_email=candidate.user.email,
            subject="📬 Your Weekly Job Digest from ZecPath",
            body=digest_body,
            email_type='job_digest',
            status='pending',
        )
        send_async_email_task.delay(email_log.id)
        queued_count += 1

    logger.info(f"📧 Weekly job digest queued for {queued_count} candidates ({new_jobs.count()} new jobs).")


@shared_task
def check_overdue_interviews_task():
    """
    Celery Beat task — runs every hour.
    Finds applications stuck in the 'interviewing' status for more than
    7 days and logs a warning so employers can take action.
    """
    from datetime import timedelta
    from .models import ApplicationLog

    threshold = timezone.now() - timedelta(days=7)

    # Find applications in 'interviewing' that haven't had a status
    # change logged in the last 7 days.
    interviewing_apps = Application.objects.filter(
        status='interviewing',
    ).select_related('candidate__user', 'job__employer')

    overdue_count = 0
    for app in interviewing_apps:
        last_log = ApplicationLog.objects.filter(
            application=app
        ).order_by('-created_at').first()

        if last_log and last_log.created_at < threshold:
            overdue_count += 1
            logger.warning(
                f"⏰ Overdue interview: Application {app.id} "
                f"({app.candidate.user.email} → {app.job.title}) "
                f"has been in 'interviewing' since {last_log.created_at:%Y-%m-%d}. "
                f"Employer: {app.job.employer.company_name}"
            )

    if overdue_count:
        logger.info(f"⏰ Found {overdue_count} overdue interviews.")
    else:
        logger.info("✅ No overdue interviews found.")


@shared_task
def cleanup_old_audio_files_task():
    """
    Celery Beat task — runs daily.
    Deletes generated AI interview audio files (.mp3/.wav) in media/interview_audio/
    that are older than 24 hours to prevent storage bloat.
    """
    import os
    import time

    audio_dir = os.path.join(settings.MEDIA_ROOT, 'interview_audio')
    if not os.path.exists(audio_dir):
        return

    now = time.time()
    cutoff = now - (24 * 60 * 60)  # 24 hours ago
    deleted_count = 0

    for filename in os.listdir(audio_dir):
        filepath = os.path.join(audio_dir, filename)
        if os.path.isfile(filepath):
            if os.stat(filepath).st_mtime < cutoff:
                try:
                    os.remove(filepath)
                    deleted_count += 1
                except Exception as exc:
                    logger.warning(f"Could not delete old audio file {filepath}: {exc}")

    if deleted_count > 0:
        logger.info(f"🗑️ Cleaned up {deleted_count} old interview audio files.")


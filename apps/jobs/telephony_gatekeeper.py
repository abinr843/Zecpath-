"""
Telephony Gatekeeper — Day 33 Decision Engine

Validates eligibility, calculates safe call times respecting
candidate timezones / working hours / weekdays, and queues
interviews in score-priority order with staggered scheduling.
"""

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone as dj_timezone

logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────
MIN_SCORE_THRESHOLD = 75          # Default if job has no auto_shortlist_threshold
WORKING_HOURS_START = time(9, 0)  # 09:00 local
WORKING_HOURS_END = time(18, 0)   # 18:00 local
DEFAULT_CALL_TIME = time(10, 0)   # 10:00 local if no preference
STAGGER_MINUTES = 10              # Buffer between consecutive calls


def validate_eligibility(application):
    """
    Check if this application is eligible for an AI interview call.

    Returns:
        (is_eligible: bool, reason: str)
    """
    # 1. Job must still be active
    if not application.job.is_active:
        return False, "Job is no longer active."

    # 2. Score threshold
    threshold = application.job.auto_shortlist_threshold or MIN_SCORE_THRESHOLD
    if application.match_score < threshold:
        return False, (
            f"Match score {application.match_score}% is below threshold "
            f"of {threshold}%."
        )

    # 3. Candidate must have a phone number
    phone = application.candidate.user.phone
    if not phone or not phone.strip():
        return False, "Candidate has no phone number on file."

    # 4. No currently active interview session
    from apps.jobs.models import InterviewSession
    active_sessions = InterviewSession.objects.filter(
        application=application,
        status__in=['queued', 'scheduled', 'in_progress'],
    ).exists()
    if active_sessions:
        return False, "An active interview session already exists."

    return True, "Eligible for AI interview."


def calculate_safe_call_time(candidate):
    """
    Determine the next safe call time for a candidate using their preferred time range.
    """
    try:
        tz = ZoneInfo(candidate.timezone)
    except (KeyError, Exception):
        logger.warning(
            "Invalid timezone '%s' for candidate %s, falling back to Asia/Kolkata",
            candidate.timezone, candidate.user.email,
        )
        tz = ZoneInfo('Asia/Kolkata')

    now_local = datetime.now(tz)
    
    # 1. Determine Target Time
    if candidate.preferred_interview_time_start and candidate.preferred_interview_time_end:
        # Pick a random minute between start and end
        start_mins = candidate.preferred_interview_time_start.hour * 60 + candidate.preferred_interview_time_start.minute
        end_mins = candidate.preferred_interview_time_end.hour * 60 + candidate.preferred_interview_time_end.minute
        
        if end_mins <= start_mins:
            end_mins = start_mins + 60 # fallback if invalid range
            
        import random
        target_mins = random.randint(start_mins, end_mins)
        target_time = time(hour=target_mins // 60, minute=target_mins % 60)
    elif candidate.preferred_interview_time_start:
        target_time = candidate.preferred_interview_time_start
    else:
        target_time = DEFAULT_CALL_TIME

    # 2. Build Target Datetime
    target_dt = now_local.replace(
        hour=target_time.hour,
        minute=target_time.minute,
        second=0, microsecond=0,
    )

    # 3. Time Travel (Past Time / Weekends)
    if target_dt <= now_local:
        target_dt += timedelta(days=1)

    while target_dt.weekday() >= 5: # 5=Sat, 6=Sun
        target_dt += timedelta(days=1)

    # 4. Fallback to Working Hours (only if no preference was set)
    if not candidate.preferred_interview_time_start:
        local_time = target_dt.time()
        if local_time < WORKING_HOURS_START:
            target_dt = target_dt.replace(hour=WORKING_HOURS_START.hour, minute=WORKING_HOURS_START.minute)
        elif local_time >= WORKING_HOURS_END:
            target_dt += timedelta(days=1)
            target_dt = target_dt.replace(hour=WORKING_HOURS_START.hour, minute=WORKING_HOURS_START.minute)
            while target_dt.weekday() >= 5:
                target_dt += timedelta(days=1)

    return target_dt.astimezone(ZoneInfo('UTC'))


def trigger_gatekeeper_for_application(application, triggered_by_user=None):
    """
    Called when an application moves to 'ready_for_interview'.
    Validates eligibility and creates a queued InterviewSession.
    
    Args:
        application: The Application instance
        triggered_by_user: The CustomUser who initiated this (None = system rule)
    """
    from apps.jobs.models import InterviewSession, Notification, SystemAuditLog

    is_eligible, reason = validate_eligibility(application)

    if not is_eligible:
        # ─── Audit Log: Rejected ───
        SystemAuditLog.objects.create(
            action_type='GATEKEEPER_REJECTED',
            triggered_by=triggered_by_user,
            application=application,
            reason=f'Gatekeeper rejected Application {application.id}: {reason}',
            metadata={
                'match_score': application.match_score,
                'threshold': application.job.auto_shortlist_threshold or MIN_SCORE_THRESHOLD,
            },
        )

        logger.info(
            "⛔ Gatekeeper rejected Application %d: %s",
            application.id, reason,
        )
        return None

    candidate = application.candidate
    scheduled_time = calculate_safe_call_time(candidate)

    with transaction.atomic():
        session = InterviewSession.objects.create(
            application=application,
            status='scheduled',
            scheduled_time=scheduled_time,
        )

        # Create a notification for the candidate
        Notification.objects.create(
            user=candidate.user,
            notification_type='interview_scheduled',
            title=f'AI Interview Scheduled — {application.job.title}',
            message=(
                f'Your AI interview for "{application.job.title}" at '
                f'{application.job.employer.company_name} has been scheduled '
                f'for {scheduled_time.strftime("%B %d, %Y at %I:%M %p")} UTC. '
                f'Please ensure your phone is available.'
            ),
            related_application=application,
        )

        # ─── Audit Log: Approved ───
        actor_desc = triggered_by_user.email if triggered_by_user else 'SYSTEM (auto-rule)'
        SystemAuditLog.objects.create(
            action_type='GATEKEEPER_APPROVED',
            triggered_by=triggered_by_user,
            application=application,
            session=session,
            reason=(
                f'Gatekeeper approved Application {application.id}. '
                f'Score {application.match_score}% met threshold of '
                f'{application.job.auto_shortlist_threshold or MIN_SCORE_THRESHOLD}%. '
                f'Triggered by: {actor_desc}. '
                f'Call scheduled at {scheduled_time.isoformat()}.'
            ),
            metadata={
                'match_score': application.match_score,
                'threshold': application.job.auto_shortlist_threshold or MIN_SCORE_THRESHOLD,
                'scheduled_time': scheduled_time.isoformat(),
                'candidate_phone': candidate.user.phone or '',
                'candidate_timezone': candidate.timezone,
            },
        )

    # Dispatch to Celery with ETA
    from apps.jobs.tasks import schedule_ai_interview_task
    schedule_ai_interview_task.apply_async(
        args=[session.id],
        eta=scheduled_time,
    )

    logger.info(
        "✅ Gatekeeper approved Application %d → InterviewSession %d "
        "scheduled at %s (score: %d)",
        application.id, session.id, scheduled_time, application.match_score,
    )
    return session


def queue_interviews_by_priority(job_id):
    """
    Queue all ready_for_interview applications for a job,
    ordered by match_score DESC (highest first), with 10-minute
    stagger between calls.
    """
    from apps.jobs.models import Application

    applications = (
        Application.objects
        .filter(job_id=job_id, status='ready_for_interview')
        .select_related('candidate__user', 'job__employer')
        .order_by('-match_score')
    )

    queued = 0
    for i, app in enumerate(applications):
        session = trigger_gatekeeper_for_application(app)
        if session:
            # Stagger: add i * 10 minutes to the scheduled time
            if i > 0:
                new_time = session.scheduled_time + timedelta(minutes=i * STAGGER_MINUTES)
                session.scheduled_time = new_time
                session.save(update_fields=['scheduled_time'])

                # Re-dispatch with new ETA
                from apps.jobs.tasks import schedule_ai_interview_task
                schedule_ai_interview_task.apply_async(
                    args=[session.id],
                    eta=new_time,
                )
            queued += 1

    logger.info(
        "📋 Queued %d interviews for Job %d (priority-ordered, %d-min stagger)",
        queued, job_id, STAGGER_MINUTES,
    )
    return queued

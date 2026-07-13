"""
Twilio Webhook Views — Day 33

Handles the real-time AI phone interview conversation loop:
  1. Incoming call → Groq Whisper V3 (STT) → Groq LLaMA 3.3 70B (Brain) → Edge TTS → TwiML
  2. Call status updates → state machine transitions + notifications

All views validate Twilio request signatures for security.
Audio files are saved to media/interview_audio/.
"""

import os
import io
import uuid
import asyncio
import logging
import tempfile

from django.conf import settings
from django.http import HttpResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.db import transaction
from django.utils import timezone as dj_timezone

from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.request_validator import RequestValidator

logger = logging.getLogger(__name__)


def validate_twilio_request(request, url_path):
    """
    Validate that the incoming request is actually from Twilio.
    Returns True if valid, False otherwise.
    """
    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    # Build the full URL Twilio used to sign the request
    full_url = f"{settings.NGROK_BASE_URL}{url_path}"

    signature = request.META.get('HTTP_X_TWILIO_SIGNATURE', '')
    params = request.POST.dict()

    return validator.validate(full_url, params, signature)


def generate_tts_audio(text, filename=None):
    """
    Generate speech audio from text using Edge TTS.
    Saves the audio file to media/interview_audio/ and returns the public URL.

    Uses asyncio to run the async edge-tts library.
    """
    import edge_tts

    if not filename:
        filename = f"{uuid.uuid4().hex}.mp3"

    audio_dir = os.path.join(settings.MEDIA_ROOT, 'interview_audio')
    os.makedirs(audio_dir, exist_ok=True)
    filepath = os.path.join(audio_dir, filename)

    async def _generate():
        communicate = edge_tts.Communicate(text, settings.EDGE_TTS_VOICE)
        await communicate.save(filepath)

    # Run the async function
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're in an already-running loop (e.g. inside Django async)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                pool.submit(lambda: asyncio.run(_generate())).result()
        else:
            loop.run_until_complete(_generate())
    except RuntimeError:
        asyncio.run(_generate())

    # Return the public URL
    audio_url = f"{settings.NGROK_BASE_URL}{settings.MEDIA_URL}interview_audio/{filename}"
    return audio_url




@method_decorator(csrf_exempt, name='dispatch')
class IncomingCallWebhookView(View):
    """
    POST /api/jobs/webhook/incoming/

    Called by Twilio when the outbound call connects or when the candidate
    speaks (via <Gather> callback). Handles the full AI conversation loop.

    Flow per turn:
      1. Validate Twilio signature
      2. If first connection → instantly transition Application to 'interviewing'
      3. If speech received → STT via Groq Whisper, VAD check
      4. LLM response via Groq LLaMA 3.3 70B (streaming)
      5. TTS via Edge TTS → saved to media/
      6. Return TwiML: <Play> audio + <Gather> for next speech
    """

    def post(self, request):
        # Validate Twilio request signature
        if not validate_twilio_request(request, '/api/jobs/webhook/incoming/'):
            logger.warning("⛔ Invalid Twilio signature on incoming webhook")
            return HttpResponse("Forbidden", status=403)

        from apps.jobs.ai_bridge import AIBridgeService
        ai_bridge = AIBridgeService()

        call_sid = request.POST.get('CallSid', '')
        speech_result = request.POST.get('SpeechResult', '')

        # Look up the InterviewSession by call_sid
        from apps.jobs.models import (
            InterviewSession, AIQuestion, AIAnswer, SystemAuditLog
        )
        try:
            session = InterviewSession.objects.select_related(
                'application__candidate__user',
                'application__job__employer',
            ).get(twilio_call_sid=call_sid)
        except InterviewSession.DoesNotExist:
            logger.error("No InterviewSession found for CallSid %s", call_sid)
            response = VoiceResponse()
            response.say("Sorry, we couldn't connect your interview session. Goodbye.")
            response.hangup()
            return HttpResponse(str(response), content_type='text/xml')

        application = session.application
        candidate = application.candidate
        job = application.job
        now = dj_timezone.now()

        # ─── INSTANT STATUS LOCK: ready_for_interview → interviewing ───
        if application.status == 'ready_for_interview':
            with transaction.atomic():
                application.status = 'interviewing'
                application.save(update_fields=['status'])

                from apps.jobs.models import ApplicationLog
                ApplicationLog.objects.create(
                    application=application,
                    user=None,
                    old_status='ready_for_interview',
                    new_status='interviewing',
                    notes='SYSTEM: AI interview call connected — status locked.',
                )

                # ─── Audit Log: Call Connected ───
                SystemAuditLog.objects.create(
                    action_type='TELEPHONY_TRIGGER',
                    application=application,
                    session=session,
                    reason=(
                        f'AI interview call connected for Application {application.id}. '
                        f'Candidate {candidate.user.email} answered. '
                        f'Status locked to "interviewing".'
                    ),
                    metadata={
                        'call_sid': call_sid,
                        'candidate_phone': candidate.user.phone or '',
                    },
                )

            session.status = 'in_progress'
            session.save(update_fields=['status'])

            logger.info(
                "🔒 Application %d locked to 'interviewing' (call connected)",
                application.id,
            )

        # ─── Determine current sequence number ───
        current_seq = session.ai_questions.count()

        # ─── Process candidate speech (STT + AIAnswer) ───
        if speech_result and speech_result.strip():
            # Candidate spoke — record as AIAnswer linked to the last question
            session.transcript += f"\nCANDIDATE: {speech_result}"

            # Append to structured transcript_data
            transcript_data = session.transcript_data or []
            current_seq_for_answer = current_seq  # current question count
            transcript_data.append({
                'role': 'candidate',
                'content': speech_result,
                'timestamp': now.isoformat(),
                'sequence': current_seq_for_answer,
            })
            session.transcript_data = transcript_data
            session.save(update_fields=['transcript', 'transcript_data'])

            # Create AIAnswer linked to the last AIQuestion
            last_question = session.ai_questions.order_by('-sequence_number').first()
            if last_question:
                latency = (now - last_question.created_at).total_seconds()
                AIAnswer.objects.create(
                    question=last_question,
                    text=speech_result,
                    latency_seconds=round(latency, 2),
                )

            logger.info("🎙️ Candidate speech: %s", speech_result[:100])

        elif request.POST.get('SpeechResult') is not None:
            # VAD: Gather fired but speech was empty/silence → re-prompt
            logger.info("🔇 VAD: silence detected, re-prompting")

        # ─── LLM Response ───
        ai_text = ai_bridge.generate_interview_response(
            transcript=session.transcript,
            job_title=job.title,
            job_description=job.description,
            candidate_name=candidate.user.first_name or candidate.user.username,
            skills=candidate.skills or ''
        )

        # Next sequence number for this AI turn
        next_seq = current_seq + 1

        # Append AI response to legacy transcript
        session.transcript += f"\nAI: {ai_text}"

        # Append to structured transcript_data
        transcript_data = session.transcript_data or []
        transcript_data.append({
            'role': 'ai',
            'content': ai_text,
            'timestamp': dj_timezone.now().isoformat(),
            'sequence': next_seq,
        })
        session.transcript_data = transcript_data
        session.save(update_fields=['transcript', 'transcript_data'])

        # Create AIQuestion record
        AIQuestion.objects.create(
            session=session,
            sequence_number=next_seq,
            text=ai_text,
        )

        # ─── TTS: Generate audio file ───
        audio_filename = f"session_{session.id}_{uuid.uuid4().hex[:8]}.mp3"
        audio_url = generate_tts_audio(ai_text, filename=audio_filename)

        # ─── Build TwiML Response ───
        response = VoiceResponse()
        response.play(audio_url)

        # Gather next speech input
        gather = Gather(
            input='speech',
            action=f"{settings.NGROK_BASE_URL}/api/jobs/webhook/incoming/",
            method='POST',
            speech_timeout='auto',
            language='en-US',
        )
        response.append(gather)

        # If no speech gathered, say goodbye
        response.say("Thank you for your time. Goodbye!")
        response.hangup()

        return HttpResponse(str(response), content_type='text/xml')


@method_decorator(csrf_exempt, name='dispatch')
class TwilioCallStatusWebhookView(View):
    """
    POST /api/jobs/webhook/twilio-status/

    Receives async status callbacks from Twilio when the call state changes:
      initiated, ringing, answered, completed, busy, no-answer, failed, canceled

    Handles:
      - completed → mark session done, trigger AI scoring
      - busy/no-answer → retry with backoff (max 3), then not_picked_up
      - failed → mark failed + notification
    """

    def post(self, request):
        # Validate Twilio request signature
        if not validate_twilio_request(request, '/api/jobs/webhook/twilio-status/'):
            logger.warning("⛔ Invalid Twilio signature on status webhook")
            return HttpResponse("Forbidden", status=403)

        call_sid = request.POST.get('CallSid', '')
        call_status = request.POST.get('CallStatus', '')
        call_duration = request.POST.get('CallDuration', '0')
        sip_code = request.POST.get('SipResponseCode', '')

        logger.info("📞 Twilio status callback: CallSid=%s Status=%s", call_sid, call_status)

        from apps.jobs.models import (
            InterviewSession, Notification, CallLog, SystemAuditLog
        )

        try:
            session = InterviewSession.objects.select_related(
                'application__candidate__user',
                'application__job__employer',
            ).get(twilio_call_sid=call_sid)
        except InterviewSession.DoesNotExist:
            logger.warning("No InterviewSession found for CallSid %s", call_sid)
            return HttpResponse("OK", status=200)

        application = session.application
        candidate_user = application.candidate.user
        job_title = application.job.title

        # ─── Always create a CallLog for every status event ───
        CallLog.objects.create(
            session=session,
            event_type=call_status,
            sip_code=sip_code,
            carrier_data=request.POST.dict(),
        )

        if call_status == 'completed':
            # ─── CALL COMPLETED SUCCESSFULLY ───
            with transaction.atomic():
                session.status = 'completed'
                session.call_duration = int(call_duration) if call_duration else 0
                session.save(update_fields=['status', 'call_duration', 'updated_at'])

                application.status = 'interview_completed'
                application.save(update_fields=['status'])

                from apps.jobs.models import ApplicationLog
                ApplicationLog.objects.create(
                    application=application,
                    user=None,
                    old_status='interviewing',
                    new_status='interview_completed',
                    notes='SYSTEM: Twilio call completed successfully.'
                )

            # Audit log
            SystemAuditLog.objects.create(
                action_type='INTERVIEW_COMPLETED',
                application=application,
                session=session,
                reason=(
                    f'AI interview call completed for Application {application.id}. '
                    f'Duration: {call_duration}s. '
                    f'Questions asked: {session.ai_questions.count()}.'
                ),
                metadata={
                    'call_sid': call_sid,
                    'call_duration': int(call_duration) if call_duration else 0,
                    'sip_code': sip_code,
                },
            )

            # Dispatch async task to score the interview via LLM
            from apps.jobs.tasks import process_interview_completion_task
            process_interview_completion_task.delay(session.id)

            # Notify candidate
            Notification.objects.create(
                user=candidate_user,
                notification_type='interview_completed',
                title=f'AI Interview Completed — {job_title}',
                message=(
                    f'Your AI interview for "{job_title}" has been completed. '
                    f'Duration: {call_duration} seconds. Results will be available shortly.'
                ),
                related_application=application,
            )

            logger.info(
                "✅ Interview completed: Session %d, Duration %ss",
                session.id, call_duration,
            )

        elif call_status in ('busy', 'no-answer', 'canceled'):
            # ─── CANDIDATE DIDN'T PICK UP ───
            session.retry_count += 1

            if session.retry_count < session.max_retries:
                # Schedule retry with 2-hour backoff
                from datetime import timedelta
                retry_eta = dj_timezone.now() + timedelta(hours=2)

                session.status = 'scheduled'
                session.scheduled_time = retry_eta
                session.twilio_call_sid = ''  # Clear for re-use
                session.error_message = f"Attempt {session.retry_count}: {call_status}"
                session.save(update_fields=[
                    'status', 'retry_count', 'scheduled_time',
                    'twilio_call_sid', 'error_message', 'updated_at',
                ])

                # Audit log: retry
                SystemAuditLog.objects.create(
                    action_type='CALL_RETRY',
                    application=application,
                    session=session,
                    reason=(
                        f'Call attempt {session.retry_count}/{session.max_retries} '
                        f'failed ({call_status}). Retry scheduled for {retry_eta.isoformat()}.'
                    ),
                    metadata={
                        'call_sid': call_sid,
                        'attempt': session.retry_count,
                        'call_status': call_status,
                        'retry_eta': retry_eta.isoformat(),
                    },
                )

                # Re-queue the Celery task
                from apps.jobs.tasks import schedule_ai_interview_task
                schedule_ai_interview_task.apply_async(
                    args=[session.id],
                    eta=retry_eta,
                )

                logger.info(
                    "🔄 Retry %d/%d for Session %d — next attempt at %s",
                    session.retry_count, session.max_retries, session.id, retry_eta,
                )
            else:
                # ─── ALL 3 ATTEMPTS EXHAUSTED ───
                with transaction.atomic():
                    session.status = 'not_picked_up'
                    session.error_message = (
                        f"All {session.max_retries} call attempts exhausted. "
                        f"Last status: {call_status}"
                    )
                    session.save(update_fields=['status', 'retry_count', 'error_message', 'updated_at'])

                    # Update application status
                    application.status = 'not_picked_up'
                    application.save(update_fields=['status'])

                    from apps.jobs.models import ApplicationLog
                    ApplicationLog.objects.create(
                        application=application,
                        user=None,
                        old_status='ready_for_interview',
                        new_status='not_picked_up',
                        notes=(
                            f'SYSTEM: Candidate did not answer after '
                            f'{session.max_retries} attempts.'
                        ),
                    )

                # Audit log: exhausted
                SystemAuditLog.objects.create(
                    action_type='CALL_EXHAUSTED',
                    application=application,
                    session=session,
                    reason=(
                        f'All {session.max_retries} call attempts exhausted for '
                        f'Application {application.id}. Last status: {call_status}.'
                    ),
                    metadata={
                        'call_sid': call_sid,
                        'total_attempts': session.max_retries,
                        'last_status': call_status,
                    },
                )

                # Push notification to candidate dashboard
                Notification.objects.create(
                    user=candidate_user,
                    notification_type='interview_not_picked_up',
                    title=f'Missed AI Interview — {job_title}',
                    message=(
                        f'We tried to reach you {session.max_retries} times for your '
                        f'AI interview for "{job_title}" at '
                        f'{application.job.employer.company_name}, but could not connect. '
                        f'Please contact the employer for next steps.'
                    ),
                    related_application=application,
                )

                logger.warning(
                    "📵 All %d attempts exhausted for Session %d — marked not_picked_up",
                    session.max_retries, session.id,
                )

        elif call_status == 'failed':
            # ─── TECHNICAL FAILURE ───
            with transaction.atomic():
                session.status = 'failed'
                session.error_message = f"Twilio call failed: {call_status}"
                session.save(update_fields=['status', 'error_message', 'updated_at'])

            # Audit log
            SystemAuditLog.objects.create(
                action_type='TELEPHONY_TRIGGER',
                application=application,
                session=session,
                reason=f'Twilio call failed with SIP code {sip_code}. Session {session.id}.',
                metadata={
                    'call_sid': call_sid,
                    'sip_code': sip_code,
                    'raw_payload': request.POST.dict(),
                },
            )

            Notification.objects.create(
                user=candidate_user,
                notification_type='interview_failed',
                title=f'Interview Call Failed — {job_title}',
                message=(
                    f'There was a technical issue with your AI interview call for '
                    f'"{job_title}". Our team has been notified.'
                ),
                related_application=application,
            )

            logger.error("❌ Call failed for Session %d", session.id)

        return HttpResponse("OK", status=200)

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 1. Async Resume Parsing Task
# ──────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def parse_resume_task(self, candidate_id, file_path, filename):
    """
    Background task to parse a candidate's uploaded resume.

    This offloads the CPU-intensive PDF/DOCX text extraction and NLP
    processing to a Celery worker so the API can respond instantly.

    Args:
        candidate_id: The ID of the Candidate profile to update.
        file_path: Absolute path to the uploaded file on disk.
        filename: Original filename (used to determine file type).

    Workflow:
        1. Open the file from disk
        2. Run text extraction (PDF/DOCX → plain text)
        3. Run NLP parsing (spaCy + regex → structured JSON)
        4. Store the parsed result on the Candidate profile
    """
    from apps.users.models import Candidate
    from apps.users.utils.resume_parser import process_resume
    from apps.users.utils.resume_nlp import parse_resume_to_json

    try:
        candidate = Candidate.objects.select_related('user').get(id=candidate_id)
    except Candidate.DoesNotExist:
        logger.error(f"Candidate {candidate_id} not found. Aborting resume parse.")
        return {'status': 'error', 'message': f'Candidate {candidate_id} not found'}

    logger.info(
        f"📄 Starting resume parsing for Candidate {candidate_id} "
        f"({candidate.user.email}), file: {filename}"
    )

    try:
        # Step 1: Open file and extract text
        with open(file_path, 'rb') as f:
            result = process_resume(f, filename)

        # Step 2: NLP extraction
        parsed_data = parse_resume_to_json(result['cleaned_text'])

        logger.info(
            f"✅ Resume parsed successfully for Candidate {candidate_id}: "
            f"{result['character_count']} chars, {result['line_count']} lines"
        )

        return {
            'status': 'completed',
            'candidate_id': candidate_id,
            'filename': filename,
            'file_type': result['file_type'],
            'cleaned_text': result['cleaned_text'],
            'character_count': result['character_count'],
            'line_count': result['line_count'],
            'parsed_data': parsed_data,
        }

    except ValueError as exc:
        logger.warning(
            f"⚠️ Resume parsing value error for Candidate {candidate_id}: {exc}"
        )
        return {'status': 'error', 'message': str(exc)}

    except Exception as exc:
        logger.exception(
            f"❌ Resume parsing failed for Candidate {candidate_id}: {exc}"
        )
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────
# 2. Expired Token Cleanup (Celery Beat — Nightly)
# ──────────────────────────────────────────────

@shared_task
def cleanup_expired_tokens_task():
    """
    Celery Beat task — runs every night at midnight.

    Cleans up expired and blacklisted JWT tokens from the
    `rest_framework_simplejwt.token_blacklist` app to keep
    the database lean.

    This calls Django's built-in management command:
        python manage.py flushexpiredtokens
    """
    from django.core.management import call_command

    logger.info("🧹 Starting expired token cleanup...")

    try:
        call_command('flushexpiredtokens')
        logger.info("✅ Expired tokens flushed successfully.")
    except Exception as exc:
        logger.exception(f"❌ Token cleanup failed: {exc}")

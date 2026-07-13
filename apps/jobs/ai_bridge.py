import os
import logging
import tempfile
import requests
from django.conf import settings
from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, stop_after_delay

logger = logging.getLogger(__name__)

class AIBridgeError(Exception):
    """Custom exception for AI Bridge failures."""
    pass

class AIBridgeService:
    """
    Centralized service for handling all AI and Voice API integrations.
    Includes robust retry mechanisms and error handling to ensure
    active phone calls do not drop due to transient API failures.
    """
    
    def __init__(self):
        self.client = Groq(api_key=settings.GROQ_API_KEY)

    @retry(
        stop=stop_after_attempt(2) | stop_after_delay(5),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def _execute_stt_request(self, audio_file_path):
        with open(audio_file_path, 'rb') as audio_file:
            return self.client.audio.transcriptions.create(
                file=("recording.wav", audio_file),
                model=settings.GROQ_STT_MODEL,
                language="en",
                response_format="text",
            )

    def transcribe_audio(self, recording_url):
        """
        Fetch audio from a Twilio recording URL and transcribe it
        using Groq Whisper Large V3.
        """
        # Download the audio from Twilio
        try:
            response = requests.get(recording_url, timeout=10)
            if response.status_code != 200:
                logger.error("Failed to download recording from %s: %s", recording_url, response.status_code)
                return ""
        except requests.RequestException as e:
            logger.error("Network error downloading recording: %s", e)
            return ""

        # Create a temporary file for the audio
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        try:
            transcription = self._execute_stt_request(tmp_path)
            return transcription.strip() if transcription else ""
        except Exception as exc:
            logger.exception("AIBridge: Groq STT completely failed after retries: %s", exc)
            return ""
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _execute_llm_request(self, messages, max_tokens=200):
        # We don't use streaming here because we need the full text for TTS anyway,
        # and streaming makes retries more complicated. Since it's a short text,
        # latency difference is negligible.
        response = self.client.chat.completions.create(
            model=settings.GROQ_LLM_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    @retry(
        stop=stop_after_attempt(2) | stop_after_delay(5),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def _live_llm_request_with_retry(self, messages, max_tokens=200):
        return self._execute_llm_request(messages, max_tokens)

    def generate_interview_response(self, transcript, job_title, job_description, candidate_name, skills):
        """
        Send the conversation transcript to Groq LLaMA 3.3 70B and get the
        interviewer response.
        """
        system_prompt = f"""You are an AI interviewer conducting a phone screening interview for the position of "{job_title}".

Job Description: {job_description}

Candidate Name: {candidate_name}
Candidate Skills: {skills}

Instructions:
- Be professional, warm, and conversational.
- Ask relevant technical and behavioral questions one at a time.
- Listen carefully to the candidate's responses and ask follow-up questions.
- Keep your responses concise (2-3 sentences max) since this is a phone call.
- If the candidate seems confused, rephrase your question.
- After 4-5 questions, wrap up the interview naturally.
- Do NOT use markdown, bullet points, or any text formatting — speak naturally."""

        messages = [{"role": "system", "content": system_prompt}]

        # Parse the transcript into alternating messages
        if transcript:
            for line in transcript.strip().split('\n'):
                if line.startswith('CANDIDATE:'):
                    messages.append({"role": "user", "content": line[10:].strip()})
                elif line.startswith('AI:'):
                    messages.append({"role": "assistant", "content": line[3:].strip()})
        else:
            # First turn — no candidate speech yet
            messages.append({
                "role": "user",
                "content": "(The candidate just picked up the phone. Greet them and introduce yourself as the AI interviewer.)",
            })

        try:
            full_response = self._live_llm_request_with_retry(messages, max_tokens=200)
            return full_response.strip()
        except Exception as exc:
            logger.exception("AIBridge: Groq LLM failed after retries: %s", exc)
            return "I apologize, I'm having a brief technical difficulty. Could you repeat that?"

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def score_interview(self, transcript, job_title, job_description):
        """
        Analyze the interview transcript to generate a score and summary.
        Since this runs in a background celery task, we can afford more retries/longer wait.
        """
        scoring_prompt = f"""You are an expert hiring manager. Analyze this AI phone interview transcript and provide:

1. A score from 0-100 based on:
   - Communication clarity (20 pts)
   - Technical knowledge (30 pts)
   - Problem-solving ability (25 pts)
   - Cultural fit and enthusiasm (25 pts)

2. A brief 3-4 sentence summary of the candidate's performance.

Job Title: {job_title}
Job Description: {job_description[:500]}

Transcript:
{transcript}

Respond in EXACTLY this format:
SCORE: [number]
SUMMARY: [your summary]"""

        messages = [{"role": "user", "content": scoring_prompt}]
        
        try:
            return self._execute_llm_request(messages, max_tokens=500)
        except Exception as exc:
            logger.exception("AIBridge: Groq LLM scoring failed after retries: %s", exc)
            raise AIBridgeError("Failed to score interview via AI Bridge") from exc

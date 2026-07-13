import os
import datetime
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

from django.test import TestCase, Client
from django.utils import timezone
from django.urls import reverse

from apps.users.models import CustomUser, Employer, Candidate
from apps.jobs.models import Job, Application, InterviewSession
from apps.jobs.telephony_gatekeeper import calculate_safe_call_time


class Day33EngineTests(TestCase):
    def setUp(self):
        # Create users (signals auto-create Employer/Candidate profiles)
        self.employer_user = CustomUser.objects.create_user(username='employer', email='employer@test.com', password='pw', role='EMPLOYER')
        self.employer = Employer.objects.get(user=self.employer_user)
        self.employer.company_name = 'Test Co'
        self.employer.save()

        self.candidate_user = CustomUser.objects.create_user(username='candidate', email='candidate@test.com', password='pw', role='CANDIDATE', phone='+1234567890')
        self.candidate = Candidate.objects.get(user=self.candidate_user)
        self.candidate.timezone = 'America/New_York'
        self.candidate.save()

        # Create job
        self.job = Job.objects.create(
            employer=self.employer,
            title='Test Job',
            is_active=True
        )

        # Create application
        self.application = Application.objects.create(
            candidate=self.candidate,
            job=self.job,
            status='applied',
            match_score=80
        )

        self.client = Client()

    @patch('apps.jobs.telephony_gatekeeper.datetime')
    def test_gatekeeper_scheduling_late_night(self, mock_datetime):
        """
        Verify that if an application becomes 'ready_for_interview' at 11:00 PM local time,
        the call is scheduled for the next morning (09:00 AM or 10:00 AM).
        """
        tz = ZoneInfo('America/New_York')
        
        # Simulate current time: 11:00 PM on a Wednesday
        # Wed, May 13, 2026 23:00:00 EST
        mock_now = datetime.datetime(2026, 5, 13, 23, 0, tzinfo=tz)
        mock_datetime.now.return_value = mock_now
        
        # Calculate safe call time
        safe_time = calculate_safe_call_time(self.candidate)
        
        # Convert result back to candidate timezone
        safe_time_local = safe_time.astimezone(tz)
        
        # Assert it's scheduled for the NEXT day (Thursday)
        self.assertEqual(safe_time_local.day, 14)
        # Default target time is 10:00 AM
        self.assertEqual(safe_time_local.hour, 10)
        self.assertEqual(safe_time_local.minute, 0)

    @patch('apps.jobs.views_webhooks.validate_twilio_request')
    @patch('apps.jobs.views_webhooks.generate_tts_audio')
    @patch('apps.jobs.ai_bridge.AIBridgeService.generate_interview_response')
    def test_webhook_vad_silence(self, mock_llm, mock_tts, mock_validate):
        """
        Verify that if Twilio sends an empty SpeechResult (VAD detects silence),
        the system handles it gracefully and re-prompts without crashing.
        """
        mock_validate.return_value = True
        mock_llm.return_value = "Hello? Are you there?"
        mock_tts.return_value = "http://test.url/audio.mp3"

        # Create active session
        session = InterviewSession.objects.create(
            application=self.application,
            status='in_progress',
            twilio_call_sid='CA12345',
            transcript=''
        )

        # Simulate incoming request with empty SpeechResult
        response = self.client.post(
            reverse('jobs:twilio-incoming'),
            {'CallSid': 'CA12345', 'SpeechResult': ''},
            HTTP_X_TWILIO_SIGNATURE='mocked_signature'
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<Gather', response.content)
        self.assertIn(b'<Play>http://test.url/audio.mp3</Play>', response.content)

        # Verify transcript did not add candidate speech (since it was empty)
        session.refresh_from_db()
        self.assertNotIn('CANDIDATE:', session.transcript)
        self.assertIn('AI: Hello? Are you there?', session.transcript)

    @patch('apps.jobs.views_webhooks.validate_twilio_request')
    @patch('apps.jobs.tasks.process_interview_completion_task.delay')
    def test_webhook_silent_hangup(self, mock_task_delay, mock_validate):
        """
        Verify that if the call is 'completed' but the transcript is very short (hang up edge case),
        it still safely transitions state and queues the scoring task.
        """
        mock_validate.return_value = True

        session = InterviewSession.objects.create(
            application=self.application,
            status='in_progress',
            twilio_call_sid='CA98765',
            transcript='AI: Hello.'
        )

        # Simulate Twilio status callback for completed call
        response = self.client.post(
            reverse('jobs:twilio-status'),
            {'CallSid': 'CA98765', 'CallStatus': 'completed', 'CallDuration': '12'},
            HTTP_X_TWILIO_SIGNATURE='mocked_signature'
        )

        self.assertEqual(response.status_code, 200)

        session.refresh_from_db()
        self.assertEqual(session.status, 'completed')
        self.assertEqual(session.call_duration, 12)

        # Verify the Celery task was triggered for scoring
        mock_task_delay.assert_called_once_with(session.id)

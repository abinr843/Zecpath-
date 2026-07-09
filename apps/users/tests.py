"""
Day 29 — Hardening Phase: Automated Test Suite for Zecpath
===========================================================
Tests cover:
  1. Auth enforcement (401s on unauthenticated requests)
  2. Access-control isolation (403s for non-admin roles on admin endpoints)
  3. Happy-path flow (Register → Login → Apply → verify DB row)
  4. Data-exposure prevention (UserSerializer field audit)
  5. File-upload security (reject .exe / .sh files on resume upload)
"""
import io
import logging

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import CustomUser, Candidate, Employer
from apps.users.serializers import UserSerializer
from apps.jobs.models import Job, Application

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _create_candidate(email='candidate@test.com', password='TestPass123!'):
    """Create and return a candidate user + their profile."""
    user = CustomUser.objects.create_user(
        username=email.split('@')[0],
        email=email,
        password=password,
        role='CANDIDATE',
    )
    # Signal auto-creates the Candidate profile
    user.refresh_from_db()
    return user


def _create_employer(email='employer@test.com', password='TestPass123!'):
    """Create and return an employer user + their profile."""
    user = CustomUser.objects.create_user(
        username=email.split('@')[0],
        email=email,
        password=password,
        role='EMPLOYER',
    )
    user.refresh_from_db()
    return user


def _create_admin(email='admin@test.com', password='TestPass123!'):
    """Create and return an admin user."""
    user = CustomUser.objects.create_user(
        username=email.split('@')[0],
        email=email,
        password=password,
        role='ADMIN',
    )
    user.refresh_from_db()
    return user


def _get_tokens(client, email, password):
    """Log in and return the access + refresh tokens."""
    response = client.post('/api/users/login/', {
        'email': email,
        'password': password,
    })
    return response.data


def _auth_header(token):
    """Return an Authorization header dict."""
    return {'HTTP_AUTHORIZATION': f'Bearer {token}'}


# ═══════════════════════════════════════════════════════════════════════════
#  1. AUTH ENFORCEMENT TESTS  —  proving 401s fire correctly
# ═══════════════════════════════════════════════════════════════════════════

class AuthEnforcementTests(TestCase):
    """
    Verify that protected endpoints reject requests with
    missing, malformed, or invalid tokens.
    """

    def setUp(self):
        self.client = APIClient()

    def test_missing_token_returns_401(self):
        """No Authorization header → 401 on a protected endpoint."""
        response = self.client.get('/api/jobs/listings/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_malformed_token_returns_401(self):
        """A garbage token → 401."""
        self.client.credentials(HTTP_AUTHORIZATION='Bearer this-is-not-a-token')
        response = self.client.get('/api/jobs/listings/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expired_or_fake_jwt_returns_401(self):
        """A syntactically plausible but fake JWT → 401."""
        fake_jwt = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjo5OTl9.fake_signature'
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {fake_jwt}')
        response = self.client.get('/api/jobs/listings/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_bearer_prefix_returns_401(self):
        """Token sent without the 'Bearer' prefix → 401."""
        user = _create_candidate()
        tokens = _get_tokens(self.client, user.email, 'TestPass123!')
        # Send the raw token without "Bearer " prefix
        self.client.credentials(HTTP_AUTHORIZATION=tokens['access'])
        response = self.client.get('/api/jobs/listings/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ═══════════════════════════════════════════════════════════════════════════
#  2. ACCESS LEAK TESTS  —  proving role-based 403s fire correctly
# ═══════════════════════════════════════════════════════════════════════════

class AccessLeakTests(TestCase):
    """
    Verify that a regular Candidate user cannot access admin-only endpoints.
    They should receive 403 Forbidden, NOT 200 OK.
    """

    def setUp(self):
        self.client = APIClient()
        self.candidate_user = _create_candidate()
        tokens = _get_tokens(self.client, self.candidate_user.email, 'TestPass123!')
        self.access_token = tokens['access']

    def test_candidate_cannot_access_platform_stats(self):
        """GET /api/admin/stats/platform/ as a candidate → 403."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
        response = self.client.get('/api/admin/stats/platform/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_candidate_cannot_access_admin_user_list(self):
        """GET /api/admin/users/ as a candidate → 403."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
        response = self.client.get('/api/admin/users/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_candidate_cannot_access_audit_logs(self):
        """GET /api/admin/audit-logs/ as a candidate → 403."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
        response = self.client.get('/api/admin/audit-logs/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_access_platform_stats(self):
        """GET /api/admin/stats/platform/ as an admin → 200."""
        admin_user = _create_admin()
        tokens = _get_tokens(self.client, admin_user.email, 'TestPass123!')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {tokens["access"]}')
        response = self.client.get('/api/admin/stats/platform/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_employer_cannot_access_platform_stats(self):
        """GET /api/admin/stats/platform/ as an employer → 403."""
        employer_user = _create_employer()
        tokens = _get_tokens(self.client, employer_user.email, 'TestPass123!')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {tokens["access"]}')
        response = self.client.get('/api/admin/stats/platform/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_candidate_cannot_access_employer_analytics(self):
        """GET /api/jobs/listings/analytics/ as a candidate → 403."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
        response = self.client.get('/api/jobs/listings/analytics/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ═══════════════════════════════════════════════════════════════════════════
#  3. HAPPY-PATH FLOW TEST  —  Register → Login → Apply → verify DB row
# ═══════════════════════════════════════════════════════════════════════════

class HappyPathFlowTests(TestCase):
    """
    End-to-end integration test simulating a realistic user flow:
      1. Candidate registers
      2. Candidate logs in (gets JWT)
      3. Employer creates a job
      4. Candidate applies for the job
      5. Verify the Application row exists in the database
    """

    def setUp(self):
        self.client = APIClient()

    @override_settings(
        CELERY_TASK_ALWAYS_EAGER=True,
        CELERY_TASK_EAGER_PROPAGATES=True,
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    )
    def test_register_login_apply_flow(self):
        # ── Step 1: Register a candidate ──
        reg_payload = {
            'username': 'flowtest_candidate',
            'email': 'flowtest@zecpath.com',
            'password': 'StrongPass2025!',
            'role': 'CANDIDATE',
        }
        reg_response = self.client.post('/api/users/register/', reg_payload)
        self.assertEqual(reg_response.status_code, status.HTTP_201_CREATED)

        # Verify user and candidate profile exist
        user = CustomUser.objects.get(email='flowtest@zecpath.com')
        self.assertEqual(user.role, 'CANDIDATE')
        self.assertTrue(hasattr(user, 'candidate'))

        # ── Step 2: Login to get JWT tokens ──
        tokens = _get_tokens(self.client, 'flowtest@zecpath.com', 'StrongPass2025!')
        self.assertIn('access', tokens)
        self.assertIn('refresh', tokens)
        access_token = tokens['access']

        # ── Step 3: Create a job (as an employer) ──
        employer_user = _create_employer()
        employer_profile = employer_user.employer
        employer_profile.company_name = 'ZecTest Corp'
        employer_profile.is_verified = True
        employer_profile.save()

        job = Job.objects.create(
            employer=employer_profile,
            title='Python Developer',
            description='Build awesome things with Django.',
            employment_type='full_time',
            location_type='remote',
            is_active=True,
        )

        # ── Step 4: Candidate uploads a master resume (required for apply) ──
        candidate = user.candidate
        fake_pdf = SimpleUploadedFile(
            'resume.pdf',
            b'%PDF-1.4 fake resume content',
            content_type='application/pdf',
        )
        candidate.master_resume = fake_pdf
        candidate.save()

        # ── Step 5: Candidate applies for the job ──
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        apply_response = self.client.post('/api/jobs/applications/', {
            'job': job.id,
            'cover_letter': 'I am very interested in this role.',
        })
        self.assertEqual(apply_response.status_code, status.HTTP_201_CREATED)

        # ── Step 6: Verify the Application row exists in the database ──
        applications = Application.objects.filter(candidate=candidate, job=job)
        self.assertEqual(applications.count(), 1)
        application = applications.first()
        self.assertEqual(application.status, 'applied')
        self.assertEqual(application.cover_letter, 'I am very interested in this role.')
        self.assertIsNotNone(application.resume_snapshot)


# ═══════════════════════════════════════════════════════════════════════════
#  4. DATA EXPOSURE TESTS  —  serializer field audit
# ═══════════════════════════════════════════════════════════════════════════

class DataExposureTests(TestCase):
    """
    Verify that the UserSerializer never exposes dangerous internal
    fields like password, is_superuser, is_staff, groups, user_permissions.
    """

    def test_user_serializer_does_not_expose_password_hash(self):
        """The serialized output must NOT include 'password'."""
        user = _create_candidate()
        serializer = UserSerializer(user)
        self.assertNotIn('password', serializer.data)

    def test_user_serializer_does_not_expose_superuser_flag(self):
        """The serialized output must NOT include 'is_superuser'."""
        user = _create_candidate()
        serializer = UserSerializer(user)
        self.assertNotIn('is_superuser', serializer.data)

    def test_user_serializer_does_not_expose_staff_flag(self):
        """The serialized output must NOT include 'is_staff'."""
        user = _create_candidate()
        serializer = UserSerializer(user)
        self.assertNotIn('is_staff', serializer.data)

    def test_user_serializer_does_not_expose_groups(self):
        """The serialized output must NOT include 'groups'."""
        user = _create_candidate()
        serializer = UserSerializer(user)
        self.assertNotIn('groups', serializer.data)

    def test_user_serializer_does_not_expose_user_permissions(self):
        """The serialized output must NOT include 'user_permissions'."""
        user = _create_candidate()
        serializer = UserSerializer(user)
        self.assertNotIn('user_permissions', serializer.data)

    def test_user_serializer_does_not_expose_last_login(self):
        """The serialized output must NOT include 'last_login'."""
        user = _create_candidate()
        serializer = UserSerializer(user)
        self.assertNotIn('last_login', serializer.data)


# ═══════════════════════════════════════════════════════════════════════════
#  5. FILE UPLOAD SECURITY TESTS
# ═══════════════════════════════════════════════════════════════════════════

class FileUploadSecurityTests(TestCase):
    """
    Verify that the resume validators reject dangerous file types
    and enforce size limits.
    """

    def test_exe_file_rejected_by_validator(self):
        """An .exe file must be rejected by validate_resume_ext."""
        from apps.users.validators import validate_resume_ext
        from django.core.exceptions import ValidationError

        exe_file = SimpleUploadedFile('malware.exe', b'\x00' * 100)
        with self.assertRaises(ValidationError):
            validate_resume_ext(exe_file)

    def test_sh_file_rejected_by_validator(self):
        """A .sh file must be rejected by validate_resume_ext."""
        from apps.users.validators import validate_resume_ext
        from django.core.exceptions import ValidationError

        sh_file = SimpleUploadedFile('script.sh', b'#!/bin/bash\nrm -rf /')
        with self.assertRaises(ValidationError):
            validate_resume_ext(sh_file)

    def test_pdf_file_accepted_by_validator(self):
        """A .pdf file must pass validate_resume_ext without error."""
        from apps.users.validators import validate_resume_ext

        pdf_file = SimpleUploadedFile('resume.pdf', b'%PDF-1.4 content')
        # Should not raise
        validate_resume_ext(pdf_file)

    def test_docx_file_accepted_by_validator(self):
        """A .docx file must pass validate_resume_ext without error."""
        from apps.users.validators import validate_resume_ext

        docx_file = SimpleUploadedFile('resume.docx', b'PK\x03\x04 content')
        # Should not raise
        validate_resume_ext(docx_file)

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=100)
    def test_oversized_file_rejected_by_validator(self):
        """A file exceeding the size limit must be rejected."""
        from apps.users.validators import validate_resume_size
        from django.core.exceptions import ValidationError

        big_file = SimpleUploadedFile('big.pdf', b'\x00' * 200)
        with self.assertRaises(ValidationError):
            validate_resume_size(big_file)

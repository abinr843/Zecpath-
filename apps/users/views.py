import logging
import os

from rest_framework import generics, status, permissions
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import CustomUser, Candidate
from .serializers import UserSerializer, CandidateSerializer, EmployerSerializer, CustomTokenObtainPairSerializer
from .services import create_candidate_account, create_employer_account
from .permissions import IsProfileOwnerOrAdmin

logger = logging.getLogger(__name__)

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


# ---------------------------------------------------------------------------
# List views
# ---------------------------------------------------------------------------

class UserList(APIView):
    """Return all registered users."""

    def get(self, request):
        users = CustomUser.objects.all()
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CandidateList(generics.ListAPIView):
    """Return all candidate profiles, with search and filtering capabilities."""
    queryset = Candidate.objects.filter(is_active=True)
    serializer_class = CandidateSerializer
    filter_backends = (DjangoFilterBackend, SearchFilter)
    search_fields = ('skills', 'headline', 'bio', 'location', 'education', 'user__first_name', 'user__last_name', 'user__email')
    filterset_fields = ('willing_to_relocate', 'experience_years')


# ---------------------------------------------------------------------------
# Registration (skinny view — logic lives in services.py)
# ---------------------------------------------------------------------------

class RegisterUser(APIView):
    """
    Public endpoint for user registration.
    Validates the payload, then delegates account creation to the
    appropriate service function based on the requested role.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        registration_payload = request.data

        # Step 1 — validate the incoming data
        serializer = UserSerializer(data=registration_payload)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data

        # Step 2 — delegate to the right service based on role
        role = validated_data.get('role', 'CANDIDATE').strip().upper()

        try:
            if role == 'EMPLOYER':
                create_employer_account(validated_data)
            else:
                create_candidate_account(validated_data)
        except Exception as exc:
            logger.exception("Registration failed for %s", validated_data.get('email'))
            return Response(
                {'error': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {'message': 'User created successfully'},
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Profile CRUD (retrieve / update / soft-delete)
# ---------------------------------------------------------------------------

class EmployerProfile(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = EmployerSerializer
    permission_classes = [permissions.IsAuthenticated, IsProfileOwnerOrAdmin]

    def get_object(self):
        return self.request.user.employer

    def perform_destroy(self, instance):
        instance.is_active = False  # soft delete logic
        instance.save()


class CandidateProfile(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CandidateSerializer
    permission_classes = [permissions.IsAuthenticated, IsProfileOwnerOrAdmin]

    def get_object(self):
        return self.request.user.candidate

    def perform_update(self, serializer):
        # Extract phone from request data and update the user model
        phone = self.request.data.get('phone')
        if phone is not None:
            self.request.user.phone = phone
            self.request.user.save(update_fields=['phone', 'updated_at'])
        serializer.save()

    def perform_destroy(self, instance):
        instance.is_active = False  # soft delete logic
        instance.save()


# ---------------------------------------------------------------------------
# Resume Parsing
# ---------------------------------------------------------------------------

class ParseResumeAPIView(APIView):
    """
    POST /api/users/parse-resume/
    Upload a PDF or DOCX resume file and kick off async background parsing.

    Accepts: multipart/form-data with a 'resume' file field.
    Returns: JSON with task_id for polling the result, or immediate error
             for invalid file types.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        resume_file = request.FILES.get('resume')

        if not resume_file:
            return Response(
                {'error': 'No resume file provided. Send a file under the "resume" field.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        filename = resume_file.name
        ext = os.path.splitext(filename)[1].lower()

        if ext not in {'.pdf', '.docx', '.doc'}:
            return Response(
                {'error': f'Unsupported file type "{ext}". Allowed: .pdf, .docx, .doc'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Save the uploaded file to a temp location so the Celery worker
        # can read it from disk (uploaded InMemoryFiles are not serializable)
        from django.conf import settings as django_settings
        import uuid

        temp_dir = os.path.join(django_settings.MEDIA_ROOT, 'temp_resumes')
        os.makedirs(temp_dir, exist_ok=True)

        safe_name = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(temp_dir, safe_name)

        with open(file_path, 'wb+') as dest:
            for chunk in resume_file.chunks():
                dest.write(chunk)

        # Dispatch the parsing to Celery
        from apps.users.tasks import parse_resume_task

        candidate = request.user.candidate
        task = parse_resume_task.delay(candidate.id, file_path, filename)

        logger.info(
            "Resume parse dispatched to Celery: task_id=%s, candidate=%s, file=%s",
            task.id, candidate.id, filename,
        )

        return Response({
            'message': 'Resume parsing has been queued. Check back shortly.',
            'task_id': task.id,
        }, status=status.HTTP_202_ACCEPTED)

class TaskStatusAPIView(APIView):
    """
    GET /api/users/task-status/<task_id>/
    Check the status of a Celery background task (e.g. resume parsing).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, task_id):
        from celery.result import AsyncResult
        result = AsyncResult(task_id)
        
        if result.ready():
            return Response({
                'status': 'completed',
                'result': result.result
            }, status=status.HTTP_200_OK)
        
        return Response({
            'status': 'pending'
        }, status=status.HTTP_200_OK)


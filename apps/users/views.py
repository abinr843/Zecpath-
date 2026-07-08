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
from .utils.resume_parser import process_resume
from .utils.resume_nlp import parse_resume_to_json

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

    def perform_destroy(self, instance):
        instance.is_active = False  # soft delete logic
        instance.save()


# ---------------------------------------------------------------------------
# Resume Parsing
# ---------------------------------------------------------------------------

class ParseResumeAPIView(APIView):
    """
    POST /api/users/parse-resume/
    Upload a PDF or DOCX resume file and receive cleaned, extracted text.

    Accepts: multipart/form-data with a 'resume' file field.
    Returns: JSON with file_type, cleaned_text, character_count, line_count.
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

        try:
            result = process_resume(resume_file, filename)
        except ValueError as exc:
            return Response(
                {'error': str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except Exception as exc:
            logger.exception("Resume parsing failed for %s", filename)
            return Response(
                {'error': 'An unexpected error occurred while parsing the resume.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        # Run NLP extraction on the cleaned text
        parsed_data = parse_resume_to_json(result['cleaned_text'])

        return Response({
            'filename': filename,
            'file_type': result['file_type'],
            'cleaned_text': result['cleaned_text'],
            'character_count': result['character_count'],
            'line_count': result['line_count'],
            'parsed_data': parsed_data,
        }, status=status.HTTP_200_OK)

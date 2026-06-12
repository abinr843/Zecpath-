import logging

from rest_framework import generics, status, permissions
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CustomUser, Candidate
from .serializers import UserSerializer, CandidateSerializer, EmployerSerializer
from .services import create_candidate_account, create_employer_account
from .permissions import IsProfileOwnerOrAdmin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# List views
# ---------------------------------------------------------------------------

class UserList(APIView):
    """Return all registered users."""

    def get(self, request):
        users = CustomUser.objects.all()
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CandidateList(APIView):
    """Return all candidate profiles."""

    def get(self, request):
        candidates = Candidate.objects.all()
        serializer = CandidateSerializer(candidates, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


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

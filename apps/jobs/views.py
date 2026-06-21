import logging

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend

from apps.users.models import Employer, Candidate
from apps.jobs.permissions import IsEmployer, IsCandidate, IsApplicationOwnerOrEmployer, IsJobOwner, IsJobAuthor
from .models import Job, Application, ApplicationLog
from .serializers import JobSerializer, ApplicationSerializer, ApplicationStatusUpdateSerializer, ApplicationReadSerializer, ApplicationLogSerializer
from .services import process_new_application, update_application_status
from .filters import ApplicationFilter

logger = logging.getLogger(__name__)


from django.db.models import Count

class JobViewSet(viewsets.ModelViewSet):
    serializer_class = JobSerializer
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    filterset_fields = ('employment_type', 'location', 'employer', 'location_type')
    search_fields = ('title', 'description', 'skills_required')
    ordering_fields = ('created_at', 'salary_min')
    ordering = ('-created_at',)

    def get_queryset(self):
        qs = Job.objects.select_related('employer').annotate(applicant_count=Count('applications'))
        if self.request.user.is_authenticated and self.request.user.role == 'EMPLOYER':
            return qs.filter(employer__user=self.request.user)
        return qs.filter(is_active=True)

    def get_permissions(self):
        # If the user is just viewing jobs (GET request), they only need to be logged in
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        # If they are trying to Create, Update, or Delete a job, enforce the Employer bouncer and Job Authorship
        return [IsEmployer(), IsJobAuthor()]

    def perform_create(self, serializer):
        # Securely fetch the employer profile linked to the JWT token and attach it
        employer_profile = Employer.objects.get(user=self.request.user)
        serializer.save(employer=employer_profile)

    @action(detail=True, methods=['patch'], url_path='close')
    def close_hiring(self, request, pk=None):
        job = self.get_object()
        job.is_active = False
        job.save()
        return Response({'status': 'Hiring closed'}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='analytics')
    def analytics(self, request):
        if request.user.role != 'EMPLOYER':
            return Response({'error': 'Only employers can access analytics.'}, status=status.HTTP_403_FORBIDDEN)
        
        employer = request.user.employer
        jobs = Job.objects.filter(employer=employer)
        active_jobs_count = jobs.filter(is_active=True).count()
        
        applications = Application.objects.filter(job__employer=employer)
        total_applicants = applications.count()
        
        shortlisted_and_beyond = applications.filter(status__in=['shortlisted', 'interviewing', 'hired']).count()
        shortlist_ratio = (shortlisted_and_beyond / total_applicants * 100) if total_applicants > 0 else 0
        
        interviewing = applications.filter(status='interviewing').count()
        hired = applications.filter(status='hired').count()
        
        return Response({
            'activeJobs': active_jobs_count,
            'totalApplicants': total_applicants,
            'shortlistRatio': round(shortlist_ratio, 1),
            'interviewing': interviewing,
            'hired': hired,
        })


class ApplicationViewSet(viewsets.ModelViewSet):
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    filterset_class = ApplicationFilter
    search_fields = ['candidate__user__first_name', 'candidate__user__last_name', 'candidate__user__email', 'candidate__skills']
    ordering_fields = ('applied_on', 'status')
    ordering = ('-applied_on',)

    def get_serializer_class(self):
        if self.request.method in permissions.SAFE_METHODS:
            return ApplicationReadSerializer
        return ApplicationSerializer

    def get_permissions(self):
        # Only Candidates can submit new applications
        if self.request.method == 'POST':
            return [IsCandidate()]

        # Require authentication and ownership checking for everything else
        return [permissions.IsAuthenticated(), IsApplicationOwnerOrEmployer()]

    def get_queryset(self):
        """
        Data Isolation — the core SaaS security feature.
        Candidates only see their own applications.
        Employers only see applications for the jobs they posted.
        Uses select_related to eliminate N+1 queries.
        """
        user = self.request.user

        if user.role == 'CANDIDATE':
            return (
                Application.objects
                .filter(candidate__user=user)
                .select_related('candidate__user', 'job__employer')
            )
        elif user.role == 'EMPLOYER':
            return (
                Application.objects
                .filter(job__employer__user=user)
                .select_related('candidate__user', 'job__employer')
            )

        # Admin or unknown fallback gets nothing
        return Application.objects.none()

    def perform_create(self, serializer):
        """
        Delegate ALL application creation logic to the service layer.
        The view stays skinny — matching the pattern from apps/users.
        """
        candidate_profile = Candidate.objects.get(user=self.request.user)
        job = serializer.validated_data['job']
        cover_letter = serializer.validated_data.get('cover_letter', '')

        # The service handles all validation, resume binding, and creation
        process_new_application(
            candidate=candidate_profile,
            job=job,
            cover_letter=cover_letter,
        )

    @action(detail=True, methods=['patch'], url_path='status-update')
    def status_update(self, request, pk=None):
        """
        PATCH /api/jobs/applications/{id}/status-update/

        Allows only the Employer who owns the job to update the
        application's ATS status and employer notes.

        Example payload:
            { "status": "shortlisted", "employer_notes": "Strong candidate" }
        """
        application = self.get_object()

        # Security: verify this employer owns the job
        if request.user.role != 'EMPLOYER' or application.job.employer.user != request.user:
            return Response(
                {'error': 'You do not have permission to update this application.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ApplicationStatusUpdateSerializer(
            application,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data.get('status', application.status)
        new_notes = serializer.validated_data.get('employer_notes', application.employer_notes)

        try:
            update_application_status(application, new_status, request.user, new_notes)
        except Exception as e:
            from rest_framework.exceptions import ValidationError
            if isinstance(e, ValidationError):
                return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ApplicationSerializer(application).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='logs')
    def logs(self, request, pk=None):
        """
        GET /api/jobs/applications/{id}/logs/
        Returns the audit trail for this application.
        """
        application = self.get_object()
        
        # Security: verify this employer owns the job
        if request.user.role != 'EMPLOYER' or application.job.employer.user != request.user:
            return Response(
                {'error': 'You do not have permission to view logs for this application.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        logs = application.logs.all()
        serializer = ApplicationLogSerializer(logs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
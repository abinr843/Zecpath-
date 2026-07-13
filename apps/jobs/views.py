import logging

from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend

from apps.users.models import Employer, Candidate
from apps.jobs.permissions import IsEmployer, IsCandidate, IsApplicationOwnerOrEmployer, IsJobOwner, IsJobAuthor
from .models import Job, Application, ApplicationLog, SavedJob, Offer, Notification
from .serializers import (
    JobSerializer, ApplicationSerializer, ApplicationStatusUpdateSerializer,
    ApplicationReadSerializer, ApplicationLogSerializer,
    SavedJobReadSerializer, SavedJobCreateSerializer, OfferSerializer,
    NotificationSerializer
)
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
        qs = Job.objects.select_related('employer__user').annotate(applicant_count=Count('applications'))
        if self.request.user.is_authenticated and self.request.user.role == 'EMPLOYER':
            return qs.filter(employer__user=self.request.user)
        return qs.filter(is_active=True)

    @method_decorator(cache_page(60 * 5))  # Cache job listings for 5 minutes
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

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

    @method_decorator(cache_page(60 * 2))  # Cache analytics for 2 minutes
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

    @method_decorator(cache_page(60 * 5))  # Cache recommendations for 5 minutes
    @action(detail=False, methods=['get'], url_path='recommended', permission_classes=[IsCandidate])
    def recommended(self, request):
        """
        GET /api/jobs/listings/recommended/
        Returns jobs matching the candidate's profile skills.
        Ranks by number of overlapping skills.
        """
        try:
            candidate = request.user.candidate
        except Candidate.DoesNotExist:
            return Response({'error': 'Candidate profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        candidate_skills = [
            s.strip().lower()
            for s in (candidate.skills or '').split(',')
            if s.strip()
        ]

        if not candidate_skills:
            return Response([], status=status.HTTP_200_OK)

        # Build Q filter: match any job that contains at least one candidate skill
        skill_query = Q()
        for skill in candidate_skills:
            skill_query |= Q(skills_required__icontains=skill)

        jobs = (
            Job.objects
            .filter(skill_query, is_active=True)
            .select_related('employer__user')
            .distinct()
        )

        # Rank by overlap count (Python-side for simplicity with SQLite)
        def overlap_count(job):
            job_skills = [s.strip().lower() for s in (job.skills_required or '').split(',')]
            return sum(1 for cs in candidate_skills if cs in job_skills)

        ranked = sorted(jobs, key=overlap_count, reverse=True)[:10]
        serializer = JobSerializer(ranked, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ApplicationViewSet(viewsets.ModelViewSet):
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    filterset_class = ApplicationFilter
    search_fields = ['candidate__user__first_name', 'candidate__user__last_name', 'candidate__user__email', 'candidate__skills']
    ordering_fields = ('applied_on', 'status', 'match_score')
    ordering = ('-match_score', '-applied_on')

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

        if user.role == 'ADMIN' or user.is_superuser:
            return Application.objects.select_related('candidate__user', 'job__employer__user').all()

        if user.role == 'CANDIDATE':
            return (
                Application.objects
                .filter(candidate__user=user)
                .select_related('candidate__user', 'job__employer__user')
            )
        elif user.role == 'EMPLOYER':
            return (
                Application.objects
                .filter(job__employer__user=user)
                .select_related('candidate__user', 'job__employer__user')
            )

        # Unknown fallback gets nothing
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

    @method_decorator(cache_page(60 * 2))  # Cache candidate analytics for 2 minutes
    @action(detail=False, methods=['get'], url_path='candidate-analytics', permission_classes=[IsCandidate])
    def candidate_analytics(self, request):
        """
        GET /api/jobs/applications/candidate-analytics/
        Returns dashboard counts for the candidate.
        """
        try:
            candidate = request.user.candidate
        except Candidate.DoesNotExist:
            return Response({'error': 'Candidate profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        applications = Application.objects.filter(candidate=candidate)
        saved_count = SavedJob.objects.filter(candidate=candidate).count()

        return Response({
            'applied': applications.count(),
            'saved': saved_count,
            'interviewing': applications.filter(status='interviewing').count(),
            'shortlisted': applications.filter(status='shortlisted').count(),
            'hired': applications.filter(status='hired').count(),
        })

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

    @method_decorator(cache_page(60))  # Cache logs for 1 minute
    @action(detail=True, methods=['get'], url_path='logs')
    def logs(self, request, pk=None):
        """
        GET /api/jobs/applications/{id}/logs/
        Returns the audit trail for this application.
        Accessible by both the owning Employer and the Candidate.
        """
        application = self.get_object()

        # Security: allow employer who owns the job OR the candidate who applied
        is_employer_owner = (
            request.user.role == 'EMPLOYER'
            and application.job.employer.user == request.user
        )
        is_candidate_owner = (
            request.user.role == 'CANDIDATE'
            and application.candidate.user == request.user
        )

        if not (is_employer_owner or is_candidate_owner):
            return Response(
                {'error': 'You do not have permission to view logs for this application.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        logs = application.logs.select_related('user').all()
        serializer = ApplicationLogSerializer(logs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='interview-details')
    def interview_details(self, request, pk=None):
        """
        GET /api/jobs/applications/{id}/interview-details/
        Returns the structured interview session data (transcript_data, questions, answers, latency).
        """
        application = self.get_object()

        # Security: allow employer who owns the job OR the candidate who applied OR ADMIN
        is_employer_owner = (
            request.user.role == 'EMPLOYER'
            and application.job.employer.user == request.user
        )
        is_candidate_owner = (
            request.user.role == 'CANDIDATE'
            and application.candidate.user == request.user
        )
        is_admin = request.user.role == 'ADMIN' or request.user.is_superuser

        if not (is_employer_owner or is_candidate_owner or is_admin):
            return Response(
                {'error': 'You do not have permission to view interview details for this application.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Get the latest interview session
        session = application.interview_sessions.order_by('-created_at').first()
        if not session:
            return Response(
                {'error': 'No interview session found for this application.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        from .serializers import InterviewSessionDetailSerializer
        serializer = InterviewSessionDetailSerializer(session)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SavedJobViewSet(viewsets.ModelViewSet):
    """
    CRUD for candidate saved/bookmarked jobs.
    Only candidates can access this — enforced via IsCandidate permission.
    """
    permission_classes = [IsCandidate]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_serializer_class(self):
        if self.request.method in permissions.SAFE_METHODS:
            return SavedJobReadSerializer
        return SavedJobCreateSerializer

    def get_queryset(self):
        return (
            SavedJob.objects
            .filter(candidate__user=self.request.user)
            .select_related('job__employer')
        )

    def perform_create(self, serializer):
        candidate = Candidate.objects.get(user=self.request.user)
        serializer.save(candidate=candidate)


class OfferViewSet(viewsets.ModelViewSet):
    serializer_class = OfferSerializer
    filter_backends = (DjangoFilterBackend, OrderingFilter)
    filterset_fields = ('status',)
    ordering_fields = ('created_at',)
    ordering = ('-created_at',)

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsEmployer()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'EMPLOYER':
            return Offer.objects.filter(employer__user=user).select_related('candidate__user', 'job')
        elif user.role == 'CANDIDATE':
            return Offer.objects.filter(candidate__user=user).select_related('employer__user', 'job')
        return Offer.objects.none()

    def perform_create(self, serializer):
        employer_profile = Employer.objects.get(user=self.request.user)
        serializer.save(employer=employer_profile)


class NotificationViewSet(viewsets.ModelViewSet):
    """Candidate notifications (interview updates, status changes)."""
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return Response({'unread_count': count})

    @action(detail=False, methods=['patch'])
    def mark_all_read(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({'status': 'ok'})
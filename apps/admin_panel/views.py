import logging
from datetime import timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import generics, status, filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import CustomUser, Employer
from apps.jobs.models import Job, Application
from .models import AdminActionLog
from .permissions import IsAdminRole
from .serializers import (
    AdminActionLogSerializer,
    AdminUserSerializer,
    AdminEmployerSerializer,
    AdminJobSerializer,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_client_ip(request):
    """Extract client IP from the request."""
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def log_admin_action(request, action_type, target_type, target_id, description=''):
    """Create an immutable audit log entry."""
    AdminActionLog.objects.create(
        admin_user=request.user,
        action_type=action_type,
        target_content_type=target_type,
        target_object_id=target_id,
        description=description,
        ip_address=get_client_ip(request),
    )


# ===========================================================================
# 1. SYSTEM MONITORING APIs
# ===========================================================================

class PlatformStatsView(APIView):
    """
    GET /api/admin/stats/platform/
    Returns aggregate platform statistics.
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        data = {
            'total_users': CustomUser.objects.count(),
            'total_candidates': CustomUser.objects.filter(role='CANDIDATE').count(),
            'total_employers': CustomUser.objects.filter(role='EMPLOYER').count(),
            'total_admins': CustomUser.objects.filter(role='ADMIN').count(),
            'verified_employers': Employer.objects.filter(is_verified=True).count(),
            'pending_employers': Employer.objects.filter(is_verified=False).count(),
            'total_jobs': Job.objects.count(),
            'active_jobs': Job.objects.filter(is_active=True).count(),
            'flagged_jobs': Job.objects.filter(is_flagged=True).count(),
            'total_applications': Application.objects.count(),
            'flagged_users': CustomUser.objects.filter(is_flagged=True).count(),
            'blocked_users': CustomUser.objects.filter(is_active=False).count(),
        }
        return Response(data, status=status.HTTP_200_OK)


class UserGrowthStatsView(APIView):
    """
    GET /api/admin/stats/users/
    Returns user signups aggregated by day for the last 30 days.
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        thirty_days_ago = timezone.now() - timedelta(days=30)
        signups = (
            CustomUser.objects
            .filter(date_joined__gte=thirty_days_ago)
            .annotate(date=TruncDate('date_joined'))
            .values('date')
            .annotate(count=Count('id'))
            .order_by('date')
        )
        data = [{'date': entry['date'].isoformat(), 'count': entry['count']} for entry in signups]
        return Response(data, status=status.HTTP_200_OK)


class JobActivityStatsView(APIView):
    """
    GET /api/admin/stats/jobs/
    Returns job postings aggregated by day for the last 30 days.
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        thirty_days_ago = timezone.now() - timedelta(days=30)
        jobs = (
            Job.objects
            .filter(created_at__gte=thirty_days_ago)
            .annotate(date=TruncDate('created_at'))
            .values('date')
            .annotate(count=Count('id'))
            .order_by('date')
        )
        data = [{'date': entry['date'].isoformat(), 'count': entry['count']} for entry in jobs]
        return Response(data, status=status.HTTP_200_OK)


# ===========================================================================
# 2. ADMIN PRIVILEGE SYSTEM
# ===========================================================================

class ApproveEmployerView(APIView):
    """
    POST /api/admin/employers/<pk>/approve/
    Sets employer.is_verified = True.
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request, pk):
        try:
            employer = Employer.objects.get(pk=pk)
        except Employer.DoesNotExist:
            return Response({'error': 'Employer not found.'}, status=status.HTTP_404_NOT_FOUND)

        if employer.is_verified:
            return Response({'message': 'Employer is already verified.'}, status=status.HTTP_200_OK)

        employer.is_verified = True
        employer.save(update_fields=['is_verified'])

        log_admin_action(
            request, 'approve_employer', 'employer', pk,
            f"Approved employer '{employer.company_name}' (User: {employer.user.email})"
        )
        return Response({'message': f"Employer '{employer.company_name}' has been approved."}, status=status.HTTP_200_OK)


class BlockUserView(APIView):
    """
    POST /api/admin/users/<pk>/block/
    Sets user.is_active = False.
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request, pk):
        try:
            target_user = CustomUser.objects.get(pk=pk)
        except CustomUser.DoesNotExist:
            return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        if target_user.role == 'ADMIN':
            return Response({'error': 'Cannot block another admin.'}, status=status.HTTP_403_FORBIDDEN)

        if not target_user.is_active:
            return Response({'message': 'User is already blocked.'}, status=status.HTTP_200_OK)

        target_user.is_active = False
        target_user.save(update_fields=['is_active'])

        log_admin_action(
            request, 'block_user', 'user', pk,
            f"Blocked user '{target_user.email}' (role: {target_user.role})"
        )
        return Response({'message': f"User '{target_user.email}' has been blocked."}, status=status.HTTP_200_OK)


class UnblockUserView(APIView):
    """
    POST /api/admin/users/<pk>/unblock/
    Sets user.is_active = True.
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request, pk):
        try:
            target_user = CustomUser.objects.get(pk=pk)
        except CustomUser.DoesNotExist:
            return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        if target_user.is_active:
            return Response({'message': 'User is already active.'}, status=status.HTTP_200_OK)

        target_user.is_active = True
        target_user.save(update_fields=['is_active'])

        log_admin_action(
            request, 'unblock_user', 'user', pk,
            f"Unblocked user '{target_user.email}' (role: {target_user.role})"
        )
        return Response({'message': f"User '{target_user.email}' has been unblocked."}, status=status.HTTP_200_OK)


# ===========================================================================
# 3. CONTENT MODERATION
# ===========================================================================

class FlagUserView(APIView):
    """
    POST /api/admin/users/<pk>/flag/
    Toggles user.is_flagged.
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request, pk):
        try:
            target_user = CustomUser.objects.get(pk=pk)
        except CustomUser.DoesNotExist:
            return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        target_user.is_flagged = not target_user.is_flagged
        target_user.save(update_fields=['is_flagged'])

        action = 'flag_user' if target_user.is_flagged else 'unflag_user'
        verb = 'Flagged' if target_user.is_flagged else 'Unflagged'

        log_admin_action(
            request, action, 'user', pk,
            f"{verb} user '{target_user.email}'"
        )
        return Response({
            'message': f"User '{target_user.email}' has been {verb.lower()}.",
            'is_flagged': target_user.is_flagged,
        }, status=status.HTTP_200_OK)


class FlagJobView(APIView):
    """
    POST /api/admin/jobs/<pk>/flag/
    Toggles job.is_flagged.
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request, pk):
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response({'error': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)

        job.is_flagged = not job.is_flagged
        job.save(update_fields=['is_flagged'])

        action = 'flag_job' if job.is_flagged else 'unflag_job'
        verb = 'Flagged' if job.is_flagged else 'Unflagged'

        log_admin_action(
            request, action, 'job', pk,
            f"{verb} job '{job.title}' (Employer: {job.employer.company_name})"
        )
        return Response({
            'message': f"Job '{job.title}' has been {verb.lower()}.",
            'is_flagged': job.is_flagged,
        }, status=status.HTTP_200_OK)


class RemoveJobView(APIView):
    """
    POST /api/admin/jobs/<pk>/remove/
    Sets job.is_active = False (soft delete).
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request, pk):
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response({'error': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not job.is_active:
            return Response({'message': 'Job is already removed.'}, status=status.HTTP_200_OK)

        job.is_active = False
        job.save(update_fields=['is_active'])

        log_admin_action(
            request, 'remove_job', 'job', pk,
            f"Removed job '{job.title}' (Employer: {job.employer.company_name})"
        )
        return Response({'message': f"Job '{job.title}' has been removed."}, status=status.HTTP_200_OK)


class RestoreJobView(APIView):
    """
    POST /api/admin/jobs/<pk>/restore/
    Sets job.is_active = True.
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request, pk):
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response({'error': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)

        if job.is_active:
            return Response({'message': 'Job is already active.'}, status=status.HTTP_200_OK)

        job.is_active = True
        job.save(update_fields=['is_active'])

        log_admin_action(
            request, 'restore_job', 'job', pk,
            f"Restored job '{job.title}' (Employer: {job.employer.company_name})"
        )
        return Response({'message': f"Job '{job.title}' has been restored."}, status=status.HTTP_200_OK)


# ===========================================================================
# 4. DATA LISTING (for frontend tables)
# ===========================================================================

class AdminUserListView(generics.ListAPIView):
    """
    GET /api/admin/users/
    Paginated, searchable list of all users.
    Supports ?search=, ?role=, ?is_flagged=, ?is_active= query params.
    """
    serializer_class = AdminUserSerializer
    permission_classes = [IsAuthenticated, IsAdminRole]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['username', 'email']
    ordering_fields = ['date_joined', 'email', 'role']
    ordering = ['-date_joined']

    def get_queryset(self):
        qs = CustomUser.objects.all()

        role = self.request.query_params.get('role')
        if role:
            qs = qs.filter(role=role.upper())

        is_flagged = self.request.query_params.get('is_flagged')
        if is_flagged is not None:
            qs = qs.filter(is_flagged=is_flagged.lower() == 'true')

        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == 'true')

        return qs


class AdminEmployerListView(generics.ListAPIView):
    """
    GET /api/admin/employers/
    Paginated list of all employers with verification status.
    Supports ?is_verified= query param.
    """
    serializer_class = AdminEmployerSerializer
    permission_classes = [IsAuthenticated, IsAdminRole]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['company_name', 'user__email']
    ordering = ['-created_at']

    def get_queryset(self):
        qs = Employer.objects.select_related('user').all()

        is_verified = self.request.query_params.get('is_verified')
        if is_verified is not None:
            qs = qs.filter(is_verified=is_verified.lower() == 'true')

        return qs


class AdminJobListView(generics.ListAPIView):
    """
    GET /api/admin/jobs/
    Paginated list of all jobs for moderation.
    Supports ?is_active=, ?is_flagged= query params.
    """
    serializer_class = AdminJobSerializer
    permission_classes = [IsAuthenticated, IsAdminRole]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'employer__company_name']
    ordering = ['-created_at']

    def get_queryset(self):
        qs = Job.objects.select_related('employer').all()

        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == 'true')

        is_flagged = self.request.query_params.get('is_flagged')
        if is_flagged is not None:
            qs = qs.filter(is_flagged=is_flagged.lower() == 'true')

        return qs


# ===========================================================================
# 5. AUDIT LOGS
# ===========================================================================

class AuditLogListView(generics.ListAPIView):
    """
    GET /api/admin/audit-logs/
    Paginated, filterable list of admin action logs.
    Supports ?action_type= query param.
    """
    serializer_class = AdminActionLogSerializer
    permission_classes = [IsAuthenticated, IsAdminRole]
    ordering = ['-created_at']

    def get_queryset(self):
        qs = AdminActionLog.objects.select_related('admin_user').all()

        action_type = self.request.query_params.get('action_type')
        if action_type:
            qs = qs.filter(action_type=action_type)

        return qs

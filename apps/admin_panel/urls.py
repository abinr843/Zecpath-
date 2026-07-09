from django.urls import path
from .views import (
    PlatformStatsView,
    UserGrowthStatsView,
    JobActivityStatsView,
    ApproveEmployerView,
    BlockUserView,
    UnblockUserView,
    FlagUserView,
    FlagJobView,
    RemoveJobView,
    RestoreJobView,
    AdminUserListView,
    AdminEmployerListView,
    AdminJobListView,
    AuditLogListView,
    AdminEmailLogListView,
    EmailLogStatsView,
)

app_name = 'admin_panel'

urlpatterns = [
    # --- System Monitoring ---
    path('stats/platform/', PlatformStatsView.as_view(), name='platform-stats'),
    path('stats/users/', UserGrowthStatsView.as_view(), name='user-growth-stats'),
    path('stats/jobs/', JobActivityStatsView.as_view(), name='job-activity-stats'),

    # --- Data Listing ---
    path('users/', AdminUserListView.as_view(), name='admin-user-list'),
    path('employers/', AdminEmployerListView.as_view(), name='admin-employer-list'),
    path('jobs/', AdminJobListView.as_view(), name='admin-job-list'),

    # --- Admin Privileges ---
    path('employers/<int:pk>/approve/', ApproveEmployerView.as_view(), name='approve-employer'),
    path('users/<int:pk>/block/', BlockUserView.as_view(), name='block-user'),
    path('users/<int:pk>/unblock/', UnblockUserView.as_view(), name='unblock-user'),

    # --- Content Moderation ---
    path('users/<int:pk>/flag/', FlagUserView.as_view(), name='flag-user'),
    path('jobs/<int:pk>/flag/', FlagJobView.as_view(), name='flag-job'),
    path('jobs/<int:pk>/remove/', RemoveJobView.as_view(), name='remove-job'),
    path('jobs/<int:pk>/restore/', RestoreJobView.as_view(), name='restore-job'),

    # --- Audit Logs ---
    path('audit-logs/', AuditLogListView.as_view(), name='audit-logs'),

    # --- Email Logs ---
    path('email-logs/', AdminEmailLogListView.as_view(), name='admin-email-logs'),
    path('email-logs/stats/', EmailLogStatsView.as_view(), name='admin-email-logs-stats'),
]

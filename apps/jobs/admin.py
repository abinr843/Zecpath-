from django.contrib import admin
from apps.jobs.models import *

class JobAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'employer', 'employment_type', 'is_active', 'created_at')
    list_filter = ('is_active', 'employment_type', 'experience_level')

class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('id', 'candidate', 'job', 'status', 'applied_on')
    list_filter = ('status',)

class SavedJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'candidate', 'job', 'saved_at')
    list_filter = ('saved_at',)

admin.site.register(Application, ApplicationAdmin)
admin.site.register(Job, JobAdmin)
admin.site.register(SavedJob, SavedJobAdmin)


class EmailLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'email_type', 'recipient_email', 'status', 'retry_count', 'created_at', 'updated_at')
    list_filter = ('status', 'email_type')
    search_fields = ('recipient_email', 'subject')
    readonly_fields = ('application', 'recipient_email', 'subject', 'body', 'email_type', 'status', 'error_message', 'retry_count', 'created_at', 'updated_at')

admin.site.register(EmailLog, EmailLogAdmin)


class InterviewSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'application', 'status', 'retry_count', 'scheduled_time', 'ai_score', 'call_duration', 'created_at')
    list_filter = ('status',)
    search_fields = ('twilio_call_sid', 'application__candidate__user__email')
    readonly_fields = ('twilio_call_sid', 'transcript', 'ai_summary', 'error_message', 'created_at', 'updated_at')

admin.site.register(InterviewSession, InterviewSessionAdmin)


class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'notification_type', 'title', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read')
    search_fields = ('user__email', 'title')

admin.site.register(Notification, NotificationAdmin)

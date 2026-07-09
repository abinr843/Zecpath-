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

from django.contrib import admin
from apps.jobs.models import *

class JobAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'employer', 'employment_type', 'is_active', 'created_at')
    list_filter = ('is_active', 'employment_type', 'experience_level')

class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('id', 'candidate', 'job', 'status', 'applied_on')
    list_filter = ('status',)

admin.site.register(Application, ApplicationAdmin)
admin.site.register(Job, JobAdmin)

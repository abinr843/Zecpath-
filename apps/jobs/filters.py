from django_filters import rest_framework as django_filters
from .models import *


class JobFilter(django_filters.FilterSet):
    min_salary = django_filters.NumberFilter(field_name='salary_min', lookup_expr='gte')
    max_salary = django_filters.NumberFilter(field_name='salary_max', lookup_expr='lte')
    skill = django_filters.CharFilter(field_name='skills_required', lookup_expr='icontains')

    class Meta:
        model = Job
        fields = ('employer', 'employment_type', 'location_type', 'experience_level')


class ApplicationFilter(django_filters.FilterSet):
    """Filter applications by status and job for dashboard views."""

    class Meta:
        model = Application
        fields = ('status', 'job')

from django_filters import rest_framework as django_filters
from .models import *


class JobFilter(django_filters.FilterSet):
    min_salary = django_filters.NumberFilter(field_name='salary', lookup_expr='gte')
    max_salary = django_filters.NumberFilter(field_name='salary', lookup_expr='lte')
    skill = django_filters.CharFilter(field_name='skill', lookup_expr='icontains')

    class Meta:
        model = Job
        fields = ('employer','employment_type','salary','skill')

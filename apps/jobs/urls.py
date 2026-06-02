from django.urls import path
from .views import *

urlpatterns = [
    path('jobs/', JobList.as_view(), name='job-list-create'),
    path('application/', ApplicationList.as_view(), name='Application-list'),



]
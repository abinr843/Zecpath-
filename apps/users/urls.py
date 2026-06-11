from django.urls import path
from .views import *

urlpatterns = [

    path('users/', UserList.as_view(), name='user-list'),
    path('Employer/', EmployerList.as_view(), name='Employer-list'),
    path('candidate/', CandidateList.as_view(), name='Candidate-list'),


]
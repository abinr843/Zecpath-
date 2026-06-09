from django.urls import path
from .views import *
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
urlpatterns = [

    path('users/', UserList.as_view(), name='user-list'),
    path('register/', RegisterUser.as_view(), name='register'),
    path('profile/candidate/', CandidateProfile.as_view(), name='candidate_profile'),
    path('profile/employer/', EmployerProfile.as_view(), name='employer_profile'),
    path('candidate/', CandidateList.as_view(), name='Candidate-list'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('login/', TokenObtainPairView.as_view(), name='login'),



]
from django.urls import path
from django.conf.urls.static import static
from django.conf import settings
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
    path('parse-resume/', ParseResumeAPIView.as_view(), name='parse-resume'),
    path('task-status/<str:task_id>/', TaskStatusAPIView.as_view(), name='task-status'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('login/', CustomTokenObtainPairView.as_view(), name='login'),



]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
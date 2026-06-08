from rest_framework import viewsets, permissions
from apps.users.models import *
from apps.jobs.permissions import IsEmployer, IsCandidate
from .models import *
from .serializers import *

class JobViewSet(viewsets.ModelViewSet):
    # Only show active jobs, newest first
    queryset = Job.objects.filter(is_active=True).order_by('-created_at')
    serializer_class = JobSerializer

    def get_permissions(self):
        # If the user is just viewing jobs (GET request), they only need to be logged in
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        # If they are trying to Create, Update, or Delete a job, enforce the Employer bouncer
        return [IsEmployer()]

    def perform_create(self, serializer):
        # Securely fetch the employer profile linked to the JWT token and attach it
        employer_profile = Employer.objects.get(user=self.request.user)
        serializer.save(employer=employer_profile)


class ApplicationViewSet(viewsets.ModelViewSet):
    serializer_class = ApplicationSerializer

    def get_permissions(self):
        # Only Candidates can submit new applications
        if self.request.method == 'POST':
            return [IsCandidate()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        # Massive SaaS Feature: Data Isolation
        # Candidates should only see their own applications.
        # Employers should only see applications for the jobs they posted.
        user = self.request.user

        if user.role =='CANDIDATE':
            return Application.objects.filter(candidate__user=user)
        elif user.role == 'EMPLOYER':
            return Application.objects.filter(job__employer__user=user)

        # Admin or unknown fallback gets nothing
        return Application.objects.none()

    def perform_create(self, serializer):
        # Securely fetch the candidate profile linked to the JWT token and attach it
        candidate_profile = Candidate.objects.get(user=self.request.user)
        serializer.save(candidate=candidate_profile)
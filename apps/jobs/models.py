from django.db import models
from apps.users.models import Employer, Candidate


class Job(models.Model):
    # Professional Dropdown Choices
    EMPLOYMENT_TYPE_CHOICES = (
        ('full_time', 'Full-time'),
        ('part_time', 'Part-time'),
        ('contract', 'Contract'),
        ('internship', 'Internship'),
    )
    LOCATION_TYPE_CHOICES = (
        ('onsite', 'On-site'),
        ('remote', 'Remote'),
        ('hybrid', 'Hybrid'),
    )
    EXPERIENCE_LEVEL_CHOICES = (
        ('entry', 'Entry Level'),
        ('mid', 'Mid Level'),
        ('senior', 'Senior Level'),
        ('executive', 'Executive / Director'),
    )

    # Core Relationships
    employer = models.ForeignKey(Employer, on_delete=models.CASCADE, related_name='jobs')

    # Core Job Details
    title = models.CharField(max_length=200)
    description = models.TextField()

    # Advanced Platform Fields
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, default='full_time')
    location_type = models.CharField(max_length=20, choices=LOCATION_TYPE_CHOICES, default='onsite')
    location = models.CharField(max_length=255, blank=True, null=True, help_text="e.g., Adoor, Kerala or Remote")
    salary_min = models.PositiveIntegerField(blank=True, null=True, help_text="Minimum salary limit")
    salary_max = models.PositiveIntegerField(blank=True, null=True, help_text="Maximum salary limit")
    experience_level = models.CharField(max_length=20, choices=EXPERIENCE_LEVEL_CHOICES, default='entry')
    skills_required = models.CharField(max_length=255, blank=True, null=True,
                                       help_text="Comma-separated skills (e.g., Python, Django, React)")
    application_deadline = models.DateField(blank=True, null=True)

    # System Fields
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} at {self.employer.company_name}"


class Application(models.Model):
    # Expanded Application Tracking System (ATS) Stages
    STATUS_CHOICES = (
        ('applied', 'Applied'),
        ('under_review', 'Under Review'),
        ('shortlisted', 'Shortlisted'),
        ('interviewing', 'Interviewing'),
        ('rejected', 'Rejected'),
        ('hired', 'Hired'),
    )

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='applications')
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='applications')

    # Professional Application Attachments
    resume_snapshot = models.URLField(max_length=500, blank=True, null=True, help_text="Snapshot of the candidate's master resume URL at the time of application")
    resume = models.FileField(upload_to='resumes/', blank=True, null=True)
    cover_letter = models.TextField(blank=True, null=True)
    employer_notes = models.TextField(blank=True, null=True,
                                      help_text="Private notes for the employer to review the candidate")

    status = models.CharField(choices=STATUS_CHOICES, default='applied', max_length=100)
    applied_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (('candidate', 'job'),)

    def __str__(self):
        return f"{self.candidate.user.username} -> {self.job.title}"


class ApplicationLog(models.Model):
    """
    Audit Tracking Log for Application status changes and notes.
    Provides a permanent history of ATS actions.
    """
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='logs')
    user = models.ForeignKey('users.CustomUser', on_delete=models.SET_NULL, null=True, help_text="The user who made the change")
    old_status = models.CharField(max_length=100)
    new_status = models.CharField(max_length=100)
    notes = models.TextField(blank=True, null=True, help_text="Optional context or notes added during the transition")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"App {self.application_id}: {self.old_status} -> {self.new_status} by {self.user}"
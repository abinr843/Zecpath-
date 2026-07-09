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
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, default='full_time', db_index=True)
    location_type = models.CharField(max_length=20, choices=LOCATION_TYPE_CHOICES, default='onsite', db_index=True)
    location = models.CharField(max_length=255, blank=True, null=True, db_index=True, help_text="e.g., Adoor, Kerala or Remote")
    salary_min = models.PositiveIntegerField(blank=True, null=True, help_text="Minimum salary limit")
    salary_max = models.PositiveIntegerField(blank=True, null=True, help_text="Maximum salary limit")
    experience_level = models.CharField(max_length=20, choices=EXPERIENCE_LEVEL_CHOICES, default='entry')
    skills_required = models.CharField(max_length=255, blank=True, null=True,
                                       help_text="Comma-separated skills (e.g., Python, Django, React)")
    application_deadline = models.DateField(blank=True, null=True)

    # ATS Automation Thresholds
    auto_reject_threshold = models.IntegerField(blank=True, null=True, help_text="Auto-reject if match score is below this %")
    auto_shortlist_threshold = models.IntegerField(blank=True, null=True, help_text="Auto-shortlist if match score is above this %")
    must_have_skills = models.CharField(max_length=255, blank=True, null=True, help_text="Comma-separated absolute dealbreakers")

    # System Fields
    is_active = models.BooleanField(default=True, db_index=True)
    is_flagged = models.BooleanField(default=False, db_index=True, help_text="Flagged by admin for moderation review")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

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

    status = models.CharField(choices=STATUS_CHOICES, default='applied', max_length=100, db_index=True)
    match_score = models.IntegerField(default=0, help_text="ATS suitability score (0-100)")
    match_details = models.JSONField(default=dict, blank=True, help_text="Scoring breakdown by category")
    applied_on = models.DateTimeField(auto_now_add=True, db_index=True)

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


class SavedJob(models.Model):
    """
    Allows candidates to bookmark/save jobs they are interested in.
    """
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='saved_jobs')
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='saved_by')
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (('candidate', 'job'),)
        ordering = ['-saved_at']

    def __str__(self):
        return f"{self.candidate.user.email} saved {self.job.title}"


class Offer(models.Model):
    """
    Direct job offer from an Employer to a Candidate.
    """
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
    )
    employer = models.ForeignKey(Employer, on_delete=models.CASCADE, related_name='offers_made')
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='offers_received')
    job = models.ForeignKey(Job, on_delete=models.SET_NULL, null=True, blank=True, related_name='offers', help_text="Optional associated job listing")
    message = models.TextField(blank=True, help_text="Message to the candidate")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Offer from {self.employer.company_name} to {self.candidate.user.email}"


class EmailLog(models.Model):
    """
    Tracks every outgoing email for audit, debugging, and retry visibility.
    Each record represents one email send attempt.
    """
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    )

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE,
        related_name='email_logs', null=True, blank=True,
        help_text="The application this email relates to (if any)"
    )
    recipient_email = models.EmailField(help_text="Recipient email address")
    subject = models.CharField(max_length=500)
    body = models.TextField(blank=True, help_text="Email body content")
    email_type = models.CharField(
        max_length=50, blank=True,
        help_text="E.g. application_submitted, shortlisted, rejected"
    )
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='pending'
    )
    error_message = models.TextField(
        blank=True, help_text="Error details if the send failed"
    )
    retry_count = models.PositiveIntegerField(
        default=0, help_text="Number of retry attempts made"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Email Log'
        verbose_name_plural = 'Email Logs'

    def __str__(self):
        return f"[{self.status}] {self.email_type} → {self.recipient_email} ({self.created_at:%Y-%m-%d %H:%M})"
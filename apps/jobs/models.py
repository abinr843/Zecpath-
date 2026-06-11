from django.db import models

from apps.users.models import Employer, Candidate


class Job(models.Model):
    employer = models.ForeignKey(Employer, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField()
    is_active = models.BooleanField(default=True)
    posted_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} at {self.employer.company_name}"

class Application(models.Model):
    STATUS_CHOICES = (
        ('applied', 'Applied'),
        ('shortlisted', 'Shortlisted'),
        ('rejected', 'Rejected'),
    )
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE)
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    status = models.CharField(choices=STATUS_CHOICES, default='applied', max_length=100)
    applied_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (('candidate', 'job'),)

    def __str__(self):
        # Fixed the attribute error to correctly fetch the username
        return f"{self.candidate.user.username} -> {self.job.title}"

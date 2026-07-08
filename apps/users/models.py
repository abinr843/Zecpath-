from django.db import models
from django.contrib.auth.models import AbstractUser
from .validators import *


class CustomUser(AbstractUser):
    # 1. Define the Roles
    ROLE_CHOICES = (
        ('ADMIN', 'admin'),
        ('EMPLOYER', 'employer'),
        ('CANDIDATE', 'candidate'),
        ('DEFAULT', 'default'),
    )

    # 2. Add the Custom Fields
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15, blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='CANDIDATE')

    is_verified = models.BooleanField(default=False)
    is_flagged = models.BooleanField(default=False, help_text="Flagged by admin for moderation review")

    # but we can explicitly add an updated field:
    updated_at = models.DateTimeField(auto_now=True)

    # 3. Tell Django to use Email for login, not Username
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']  # Username is still required by AbstractUser behind the scenes

    def __str__(self):
        return f"{self.email} - {self.role}"


class Employer(models.Model):
    SIZE_CHOICES = (
        ('1-10', '1-10 Employees'),
        ('11-50', '11-50 Employees'),
        ('51-200', '51-200 Employees'),
        ('201-500', '201-500 Employees'),
        ('500+', '500+ Employees'),
    )
    INDUSTRY_CHOICES = (
        ('tech', 'Technology & Software'),
        ('finance', 'Finance & Banking'),
        ('healthcare', 'Healthcare'),
        ('education', 'Education'),
        ('manufacturing', 'Manufacturing'),
        ('other', 'Other'),
    )

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='employer')

    # Branding & Identity
    company_name = models.CharField(max_length=255, blank=True)
    logo = models.ImageField(upload_to='employer_logos/', blank=True, null=True)
    banner_image = models.ImageField(upload_to='employer_banners/', blank=True, null=True)
    description = models.TextField(blank=True, help_text="Detailed about section for the company")

    # Core Metadata
    industry = models.CharField(max_length=50, choices=INDUSTRY_CHOICES, default='other')
    company_size = models.CharField(max_length=20, choices=SIZE_CHOICES, default='1-10')
    established_year = models.PositiveIntegerField(blank=True, null=True)
    headquarters = models.CharField(max_length=255, blank=True, help_text="e.g., Berlin, Germany")

    # Digital Footprint
    domain = models.URLField(blank=True, null=True, help_text="Company Website")
    linkedin_url = models.URLField(blank=True, null=True)
    twitter_url = models.URLField(blank=True, null=True)

    # System Controls
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.company_name or self.user.email


class Candidate(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='candidate')

    # Identity & Presentation
    profile_picture = models.ImageField(upload_to='candidate_pics/', blank=True, null=True)
    headline = models.CharField(max_length=255, blank=True, help_text="e.g., Full Stack Python Developer")
    bio = models.TextField(blank=True, help_text="A short professional summary")

    # Professional Metadata
    skills = models.CharField(max_length=500, blank=True, help_text="e.g., Python, Django, React, Neo4j")
    languages = models.CharField(max_length=255, blank=True, help_text="e.g., English, Malayalam, German")
    education = models.CharField(max_length=255, blank=True, help_text="Highest degree or current study")
    experience_years = models.FloatField(default=0.0)
    expected_salary = models.PositiveIntegerField(blank=True, null=True, help_text="Expected annual salary")

    # Location & Logistics
    location = models.CharField(max_length=255, blank=True, help_text="e.g., Adoor, Kerala")
    willing_to_relocate = models.BooleanField(default=False)

    # Digital Portfolio
    master_resume = models.FileField(
        upload_to='master_resumes/',
        blank=True,
        null=True,
        validators=[validate_resume_ext, validate_resume_size],
        help_text="Upload PDF or DOCX (Max 5MB)"
    )
    portfolio_url = models.URLField(blank=True, null=True, help_text="Link to personal site or projects like TourEase")
    github_url = models.URLField(blank=True, null=True)
    linkedin_url = models.URLField(blank=True, null=True)

    # System Controls
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.user.email





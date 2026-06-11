from django.db import models
from django.contrib.auth.models import AbstractUser


class CustomUser(AbstractUser):
    # 1. Define the Roles
    ROLE_CHOICES = (
        ('ADMIN', 'admin'),
        ('EMPLOYER', 'employer'),
        ('CANDIDATE', 'candidate'),
    )

    # 2. Add the Custom Fields
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15, blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='CANDIDATE')

    is_verified = models.BooleanField(default=False)

    # but we can explicitly add an updated field:
    updated_at = models.DateTimeField(auto_now=True)

    # 3. Tell Django to use Email for login, not Username
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']  # Username is still required by AbstractUser behind the scenes

    def __str__(self):
        return f"{self.email} - {self.role}"


class Employer(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='employer')
    company_name = models.CharField(max_length=100)
    company_website= models.URLField(max_length=500,null=True,blank=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.company_name

class Candidate(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='candidate')
    phone_no = models.CharField(max_length=100, blank=True, null=True)
    resume_url = models.URLField(max_length=500, null=True,blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.user.username






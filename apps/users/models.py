from django.db import models
from django.contrib.auth.models import User

class Employer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='employer profile'),
    company_name = models.CharField(max_length=100),
    company_website= models.URLField(max_length=500,null=True,blank=True),
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.company_name

class Candidate(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='candidate profile'),
    phone_no = models.CharField(max_length=100),
    resume_url = models.URLField(max_length=500, null=True,blank=True),
    created_date = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.user.username






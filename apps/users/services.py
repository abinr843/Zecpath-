from django.contrib.auth.models import User
from django.db import transaction
from .models import *


def create_candidate_account(username, email, password, phone_no):
    """
    Handles the secure creation of a User and their linked Candidate profile.
    Uses database transactions to ensure both succeed, or neither do.
    """
    with transaction.atomic():
        # 1. Create the base user and hash the password
        user = User.objects.create_user(username=username, email=email, password=password)

        # 2. Create the linked profile
        candidate = Candidate.objects.create(
            user=user,
            phone_no=phone_no
        )

        # 3. (Future) Trigger welcome email here

        return candidate
from rest_framework import serializers

from apps.jobs.models import Job, Application
from apps.users.models import Candidate, CustomUser


class JobSerializer(serializers.ModelSerializer):
    applicant_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Job
        fields = '__all__'
        read_only_fields = ('id','employer','created_at')


class NestedUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ('id', 'username', 'email', 'first_name', 'last_name')


class NestedCandidateSerializer(serializers.ModelSerializer):
    user = NestedUserSerializer(read_only=True)

    class Meta:
        model = Candidate
        fields = ('id', 'user', 'profile_picture', 'headline', 'bio', 'skills', 'experience_years', 'education')


class NestedJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = ('id', 'title', 'location_type', 'employment_type')


class ApplicationReadSerializer(serializers.ModelSerializer):
    candidate = NestedCandidateSerializer(read_only=True)
    job = NestedJobSerializer(read_only=True)

    class Meta:
        model = Application
        fields = '__all__'



class ApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Application
        fields = '__all__'
        read_only_fields = ['id', 'candidate', 'status', 'employer_notes', 'applied_on', 'resume_snapshot']

    def validate(self, attrs):
        job = attrs.get('job')

        from .validators import validate_job_is_active, validate_application_deadline, validate_no_duplicate_application
        validate_job_is_active(job)
        validate_application_deadline(job)

        request = self.context.get('request')
        if request and request.user.is_authenticated and hasattr(request.user, 'candidate'):
            candidate = request.user.candidate
            validate_no_duplicate_application(candidate, job)

        return attrs


class ApplicationStatusUpdateSerializer(serializers.ModelSerializer):
    """
    Minimal serializer for employers to update the ATS pipeline stage.
    Only exposes status and employer_notes — everything else is read-only.
    """
    class Meta:
        model = Application
        fields = ['id', 'status', 'employer_notes']
        read_only_fields = ['id']

    def validate_status(self, value):
        valid_statuses = dict(Application.STATUS_CHOICES).keys()
        if value not in valid_statuses:
            raise serializers.ValidationError(
                f"Invalid status '{value}'. Must be one of: {', '.join(valid_statuses)}"
            )
        return value
from rest_framework import serializers

from apps.jobs.models import Job, Application, ApplicationLog, SavedJob, Offer, InterviewSession, Notification, AIQuestion, AIAnswer
from apps.users.models import Candidate, CustomUser, Employer


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
    match_score = serializers.IntegerField(read_only=True)
    match_details = serializers.JSONField(read_only=True)

    class Meta:
        model = Application
        fields = '__all__'



class ApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Application
        fields = '__all__'
        read_only_fields = ['id', 'candidate', 'status', 'employer_notes', 'applied_on', 'resume_snapshot', 'match_score', 'match_details']

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


class ApplicationLogSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationLog
        fields = ('id', 'old_status', 'new_status', 'notes', 'created_at', 'user_name')

    def get_user_name(self, obj):
        if obj.user:
            return obj.user.get_full_name() or obj.user.username
        return "System"


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


class SavedJobReadSerializer(serializers.ModelSerializer):
    """Read serializer that nests full job details for the dashboard."""
    job = NestedJobSerializer(read_only=True)

    class Meta:
        model = SavedJob
        fields = ('id', 'job', 'saved_at')


class SavedJobCreateSerializer(serializers.ModelSerializer):
    """Write serializer that accepts a job ID to save."""
    class Meta:
        model = SavedJob
        fields = ('id', 'job')
        read_only_fields = ('id',)


class NestedEmployerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employer
        fields = ('id', 'company_name', 'logo')


class OfferSerializer(serializers.ModelSerializer):
    employer_details = NestedEmployerSerializer(source='employer', read_only=True)
    candidate_details = NestedCandidateSerializer(source='candidate', read_only=True)
    job_details = NestedJobSerializer(source='job', read_only=True)

    class Meta:
        model = Offer
        fields = ('id', 'employer', 'candidate', 'job', 'message', 'status', 'created_at', 'updated_at', 'employer_details', 'candidate_details', 'job_details')
        read_only_fields = ('id', 'employer', 'created_at', 'updated_at')


class InterviewSessionSerializer(serializers.ModelSerializer):
    candidate_name = serializers.SerializerMethodField()
    job_title = serializers.SerializerMethodField()

    class Meta:
        model = InterviewSession
        fields = ('id', 'application', 'status', 'scheduled_time',
                  'twilio_call_sid', 'transcript', 'ai_score', 'ai_summary',
                  'retry_count', 'max_retries', 'error_message',
                  'call_duration', 'created_at', 'updated_at',
                  'candidate_name', 'job_title')
        read_only_fields = ('id', 'application', 'twilio_call_sid', 'transcript',
                           'ai_score', 'ai_summary', 'retry_count',
                           'created_at', 'updated_at')

    def get_candidate_name(self, obj):
        user = obj.application.candidate.user
        return user.get_full_name() or user.username

    def get_job_title(self, obj):
        return obj.application.job.title


class AIAnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIAnswer
        fields = ('id', 'text', 'latency_seconds', 'created_at')


class AIQuestionSerializer(serializers.ModelSerializer):
    answer = AIAnswerSerializer(read_only=True)

    class Meta:
        model = AIQuestion
        fields = ('id', 'sequence_number', 'text', 'created_at', 'answer')


class InterviewSessionDetailSerializer(serializers.ModelSerializer):
    candidate_name = serializers.SerializerMethodField()
    job_title = serializers.SerializerMethodField()
    questions = AIQuestionSerializer(source='ai_questions', many=True, read_only=True)
    total_questions = serializers.SerializerMethodField()
    avg_latency = serializers.SerializerMethodField()

    class Meta:
        model = InterviewSession
        fields = ('id', 'application', 'status', 'scheduled_time',
                  'twilio_call_sid', 'transcript', 'transcript_data',
                  'ai_score', 'ai_summary', 'retry_count', 'max_retries',
                  'error_message', 'call_duration', 'created_at', 'updated_at',
                  'candidate_name', 'job_title', 'questions',
                  'total_questions', 'avg_latency')

    def get_candidate_name(self, obj):
        user = obj.application.candidate.user
        return user.get_full_name() or user.username

    def get_job_title(self, obj):
        return obj.application.job.title

    def get_total_questions(self, obj):
        return obj.ai_questions.count()

    def get_avg_latency(self, obj):
        answers = AIAnswer.objects.filter(question__session=obj, latency_seconds__isnull=False)
        if not answers.exists():
            return None
        from django.db.models import Avg
        return round(answers.aggregate(avg=Avg('latency_seconds'))['avg'] or 0, 2)


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ('id', 'notification_type', 'title', 'message', 'is_read',
                 'related_application', 'created_at')
        read_only_fields = ('id', 'notification_type', 'title', 'message',
                           'related_application', 'created_at')
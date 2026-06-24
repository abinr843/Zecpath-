from rest_framework import serializers
from .models import AdminActionLog
from apps.users.models import CustomUser, Employer
from apps.jobs.models import Job


class AdminActionLogSerializer(serializers.ModelSerializer):
    admin_username = serializers.CharField(source='admin_user.username', read_only=True, default='')
    admin_email = serializers.EmailField(source='admin_user.email', read_only=True, default='')
    action_type_display = serializers.CharField(source='get_action_type_display', read_only=True)

    class Meta:
        model = AdminActionLog
        fields = [
            'id', 'admin_user', 'admin_username', 'admin_email',
            'action_type', 'action_type_display',
            'target_content_type', 'target_object_id',
            'description', 'ip_address', 'created_at',
        ]
        read_only_fields = fields


class AdminUserSerializer(serializers.ModelSerializer):
    """User data for admin management tables."""

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'role',
            'is_active', 'is_flagged', 'is_verified',
            'phone', 'date_joined', 'updated_at',
        ]
        read_only_fields = fields


class AdminEmployerSerializer(serializers.ModelSerializer):
    """Employer data for admin approval tables."""
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = Employer
        fields = [
            'id', 'user', 'user_email', 'user_username',
            'company_name', 'industry', 'company_size',
            'headquarters', 'domain',
            'is_verified', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields


class AdminJobSerializer(serializers.ModelSerializer):
    """Job data for admin moderation tables."""
    employer_name = serializers.CharField(source='employer.company_name', read_only=True, default='')
    employer_id = serializers.IntegerField(source='employer.id', read_only=True)

    class Meta:
        model = Job
        fields = [
            'id', 'title', 'employer', 'employer_name', 'employer_id',
            'employment_type', 'location_type', 'location',
            'experience_level', 'skills_required',
            'is_active', 'is_flagged',
            'created_at',
        ]
        read_only_fields = fields

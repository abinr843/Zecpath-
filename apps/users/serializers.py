from rest_framework import serializers, permissions
from rest_framework.permissions import AllowAny

from .models import *


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = CustomUser
        fields = '__all__'
        read_only_fields = ('id',)


    def create(self, validated_data ):
            email = validated_data['email']
            username = validated_data['username']
            user = CustomUser.objects.create_user(
                username=username,
                email=email,
                password=validated_data['password'],
                role = validated_data.get('role','default'))

            return user






class CandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Candidate
        fields = '__all__'
        read_only_fields = ['id','user','is_active']

    def validate_experience_years(self, value):
        if value < 0:
            raise serializers.ValidationError("Experience years cannot be negative.")
        if value > 50:
            raise serializers.ValidationError("Please enter a valid number of years.")
        return value

class EmployerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employer
        fields = '__all__'
        read_only_fields = ('id','user','is_active','is_verified')


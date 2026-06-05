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
        read_only_fields = ('id',)

class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employer
        fields = '__all__'
        read_only_fields = ('id',)


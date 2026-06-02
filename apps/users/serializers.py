from rest_framework import serializers
from .models import *


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = '__all__'
        read_only_fields = ('id',)



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


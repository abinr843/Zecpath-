from django.db.migrations import serializer
from django.shortcuts import render
from django.http import JsonResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status, response
from .serializers import *
from django.db import IntegrityError
from .services import *




class UserList(APIView):
    def get(self, request):
        users = User.objects.all()
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)



class CandidateList(APIView):
    def get(self, request):
        candidates = Candidate.objects.all()
        serializer = CandidateSerializer(candidates, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)



class RegisterUser(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializers = UserSerializer(data=request.data)
        if serializers.is_valid():
            serializers.save()
            return Response({
                'message':'user created successfully'},
                 status=status.HTTP_201_CREATED)
        return Response(serializers.errors, status=status.HTTP_400_BAD_REQUEST)


            
class EmployerList(APIView):
    def get(self, request):
        employee = Employer.objects.all()
        serializer = CandidateSerializer(employee, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SecureDashboard(APIView):
    permission_classes = [IsAuthenticated]
    def get (self, request):
        
        return Response({
            "message": f"Welcome to the secure zone, {request.user.email}!",
            "role": request.user.role
        })






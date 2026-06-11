from django.db.migrations import serializer
from django.shortcuts import render
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
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

    from django.db import IntegrityError
    from .services import create_candidate_account

    class CandidateRegistrationAPI(APIView):
        def post(self, request):
            # 1. Grab the raw data sent from Postman (or your future React frontend)
            username = request.data.get('username')
            email = request.data.get('email')
            password = request.data.get('password')
            phone_no = request.data.get('phone_no')

            # Basic traffic check: Did they send everything?
            if not all([username, email, password, phone_no]):
                return Response(
                    {"error": "All fields (username, email, password, phone_no) are required."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                # 2. Hand it off to the Service Layer (The Brains!)
                candidate = create_candidate_account(username, email, password, phone_no)

                # 3. Return the success signal
                return Response({
                    "message": "Account created successfully!",
                    "username": candidate.user.username,
                    "phone": candidate.phone_no
                }, status=status.HTTP_201_CREATED)

            except IntegrityError:
                # The database will throw this if the username already exists
                return Response(
                    {"error": "That username is already taken. Please choose another."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            except Exception as e:
                # A safety net for any other unexpected crashes
                return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            
class EmployerList(APIView):
    def get(self, request):
        employee = Employer.objects.all()
        serializer = CandidateSerializer(employee, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)





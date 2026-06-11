from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import *
from .serializers import *
from .services import *

class JobList(APIView):
    def get(self, request):
        jobs = Job.objects.all()
        serializer = JobSerializer(jobs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = JobSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ApplicationList(APIView):
        def get(self, request):
            applications = Application.objects.all()
            serializer = ApplicationSerializer(applications, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        def post(self, request, job_id):
            try:
                # 1. Grab the data
                job = Job.objects.get(id=job_id)
                # Hardcoding candidate for now until auth is fully hooked up
                candidate = Candidate.objects.first()

                # 2. Call the Service Layer (The Clean Architecture part!)
                application = process_new_application(candidate, job)

                # 3. Return the response
                return Response(
                    {"message": "Application submitted successfully!", "id": application.id},
                    status=status.HTTP_201_CREATED
                )

            except Job.DoesNotExist:
                return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)
            except ValidationError as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

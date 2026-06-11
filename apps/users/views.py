
from rest_framework import generics,status
from rest_framework.response import Response
from rest_framework.views import APIView
from .serializers import *
from .services import *
from .permissions import *




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


            
class EmployerProfile(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = EmployerSerializer
    permission_classes = [permissions.IsAuthenticated,IsProfileOwnerOrAdmin]
    def get_object(self):
        return self.request.user.candidate

    def perform_destroy(self,instance):
        instance.is_active = False #soft delete logic
        instance.save()

class CandidateProfile(generics.RetrieveUpdateDestroyAPIView):
   serializer_class = CandidateSerializer
   permission_classes = [permissions.IsAuthenticated,IsProfileOwnerOrAdmin]


   def get_object(self):
    return self.request.user.candidate


   def perform_destroy(self, instance):
    instance.is_active = False  # soft delete logic
    instance.save()










from .views import *
from django.urls import path, include
from rest_framework.routers import DefaultRouter


app_name = 'jobs'

# The Router automatically generates all the complex URL patterns for us!
router = DefaultRouter()
router.register(r'listings', JobViewSet, basename='job')
router.register(r'applications', ApplicationViewSet, basename='application')

urlpatterns = [
    path('', include(router.urls)),
]






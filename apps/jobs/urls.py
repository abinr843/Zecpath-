
from .views import *
from .views_webhooks import IncomingCallWebhookView, TwilioCallStatusWebhookView
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.conf.urls.static import static
from django.conf import settings

app_name = 'jobs'

# The Router automatically generates all the complex URL patterns for us!
router = DefaultRouter()
router.register(r'listings', JobViewSet, basename='job')
router.register(r'applications', ApplicationViewSet, basename='application')
router.register(r'saved-jobs', SavedJobViewSet, basename='saved-job')
router.register(r'offers', OfferViewSet, basename='offer')
router.register(r'notifications', NotificationViewSet, basename='notification')

urlpatterns = [
    path('', include(router.urls)),

    # Twilio Webhooks (CSRF exempt via the view, signature validated)
    path('webhook/incoming/', IncomingCallWebhookView.as_view(), name='twilio-incoming'),
    path('webhook/twilio-status/', TwilioCallStatusWebhookView.as_view(), name='twilio-status'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

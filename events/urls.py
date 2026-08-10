from django.urls import path, include
from rest_framework.routers import DefaultRouter
from events.views import EventViewSet, TicketTypeViewSet

router = DefaultRouter()
router.register(r'events', EventViewSet, basename='event')
router.register(r'ticket-types', TicketTypeViewSet, basename='tickettype')

urlpatterns = [
    path('', include(router.urls)),
]

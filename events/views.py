from rest_framework import viewsets, permissions
from events.models import Event, TicketType
from events.serializers import EventSerializer, TicketTypeSerializer


class EventViewSet(viewsets.ModelViewSet):
    throttle_scope = 'events_list'
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = EventSerializer
    queryset = Event.objects.prefetch_related('ticket_types').all()

    def perform_create(self, serializer):
        serializer.save(organizer=self.request.user)


class TicketTypeViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.AllowAny]
    serializer_class = TicketTypeSerializer
    queryset = TicketType.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()
        event_id = self.request.query_params.get('event_id')
        if event_id:
            queryset = queryset.filter(event_id=event_id)
        return queryset

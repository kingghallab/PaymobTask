from rest_framework import serializers
from orders.models import Reservation, ReservationStatus
from events.serializers import TicketTypeSerializer


class ReservationSerializer(serializers.ModelSerializer):
    ticket_type_detail = TicketTypeSerializer(source='ticket_type', read_only=True)

    class Meta:
        model = Reservation
        fields = (
            'id', 'user', 'ticket_type', 'ticket_type_detail',
            'quantity', 'status', 'expires_at', 'created_at'
        )
        read_only_fields = ('id', 'user', 'status', 'expires_at', 'created_at')


class ReservationCreateSerializer(serializers.Serializer):
    ticket_type_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)

from rest_framework import serializers
from events.models import Event, TicketType


class TicketTypeSerializer(serializers.ModelSerializer):
    computed_available = serializers.IntegerField(read_only=True)

    class Meta:
        model = TicketType
        fields = (
            'id', 'event', 'name', 'total_capacity',
            'sold', 'held', 'computed_available',
            'price_cents', 'status', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'sold', 'held', 'created_at', 'updated_at')


class EventSerializer(serializers.ModelSerializer):
    ticket_types = TicketTypeSerializer(many=True, read_only=True)

    class Meta:
        model = Event
        fields = (
            'id', 'title', 'description', 'start_date', 'end_date',
            'venue', 'status', 'organizer', 'hold_duration_minutes',
            'ticket_types', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        start_date = attrs.get('start_date')
        end_date = attrs.get('end_date')
        if start_date and end_date and start_date >= end_date:
            raise serializers.ValidationError({"end_date": "End date must be after start date."})
        return attrs

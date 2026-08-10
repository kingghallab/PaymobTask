from rest_framework import serializers
from orders.models import Reservation, Order, Ticket, Refund
from events.serializers import TicketTypeSerializer, EventSerializer


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


class TicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ('id', 'order', 'status', 'created_at')
        read_only_fields = ('id', 'order', 'created_at')


class OrderSerializer(serializers.ModelSerializer):
    tickets = TicketSerializer(many=True, read_only=True)
    ticket_type_detail = TicketTypeSerializer(source='ticket_type', read_only=True)
    event_detail = EventSerializer(source='event', read_only=True)

    class Meta:
        model = Order
        fields = (
            'id', 'user', 'event', 'event_detail', 'reservation',
            'ticket_type', 'ticket_type_detail', 'idempotency_key',
            'quantity', 'unit_price_cents', 'total_cents', 'status',
            'payment_id', 'payment_provider', 'tickets', 'confirmed_at', 'created_at'
        )
        read_only_fields = ('id', 'user', 'created_at')


class PurchaseRequestSerializer(serializers.Serializer):
    reservation_id = serializers.UUIDField()


class RefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        fields = (
            'id', 'order', 'ticket', 'amount_cents', 'reason',
            'status', 'initiated_by', 'payment_refund_id', 'processed_at', 'created_at'
        )
        read_only_fields = ('id', 'status', 'payment_refund_id', 'processed_at', 'created_at')


class RefundRequestSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()
    ticket_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=None,
        help_text="Optional list of ticket IDs for partial refund. Omit for full order refund."
    )
    reason = serializers.CharField(required=False, allow_blank=True, default="")

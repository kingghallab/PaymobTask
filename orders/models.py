import uuid
from django.db import models
from django.conf import settings
from events.models import Event, TicketType


class ReservationStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    CONFIRMED = 'confirmed', 'Confirmed'
    EXPIRED = 'expired', 'Expired'
    CANCELLED = 'cancelled', 'Cancelled'


class OrderStatus(models.TextChoices):
    PROCESSING = 'processing', 'Processing'
    CONFIRMED = 'confirmed', 'Confirmed'
    PARTIALLY_REFUNDED = 'partially_refunded', 'Partially Refunded'
    REFUNDED = 'refunded', 'Refunded'
    FAILED = 'failed', 'Failed'


class TicketStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    REFUNDED = 'refunded', 'Refunded'
    CANCELLED = 'cancelled', 'Cancelled'


class Reservation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reservations'
    )
    ticket_type = models.ForeignKey(
        TicketType,
        on_delete=models.CASCADE,
        related_name='reservations'
    )
    quantity = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=ReservationStatus.choices,
        default=ReservationStatus.ACTIVE
    )
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['expires_at'],
                condition=models.Q(status='active'),
                name='idx_reservation_expiry'
            )
        ]

    def __str__(self):
        return f"Reservation {self.id} ({self.quantity} x {self.ticket_type.name}) - {self.status}"


class Order(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='orders'
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='orders'
    )
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.CASCADE,
        related_name='orders'
    )
    ticket_type = models.ForeignKey(
        TicketType,
        on_delete=models.CASCADE,
        related_name='orders'
    )
    idempotency_key = models.CharField(max_length=255, unique=True)
    quantity = models.PositiveIntegerField()
    unit_price_cents = models.PositiveIntegerField()
    total_cents = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PROCESSING
    )
    payment_id = models.CharField(max_length=255, blank=True)
    payment_provider = models.CharField(max_length=50, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at'], name='idx_order_user'),
            models.Index(fields=['event', 'status'], name='idx_order_event_status'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(total_cents__gte=0),
                name='chk_total_positive'
            )
        ]

    def __str__(self):
        return f"Order {self.id} - {self.status} (${self.total_cents / 100:.2f})"


class Ticket(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='tickets'
    )
    status = models.CharField(
        max_length=20,
        choices=TicketStatus.choices,
        default=TicketStatus.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Ticket {self.id} ({self.status})"

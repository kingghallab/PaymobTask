import uuid
from django.db import models
from django.conf import settings
from events.models import TicketType


class ReservationStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    CONFIRMED = 'confirmed', 'Confirmed'
    EXPIRED = 'expired', 'Expired'
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

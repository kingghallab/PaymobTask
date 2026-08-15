import uuid
from django.db import models
from django.conf import settings


class EventStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    PUBLISHED = 'published', 'Published'
    CANCELLED = 'cancelled', 'Cancelled'
    COMPLETED = 'completed', 'Completed'


class TicketTypeStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    PAUSED = 'paused', 'Paused'
    SOLD_OUT = 'sold_out', 'Sold Out'


class Event(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    venue = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=EventStatus.choices,
        default=EventStatus.DRAFT
    )
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='organized_events'
    )
    hold_duration_minutes = models.PositiveIntegerField(default=10)
    sales_paused = models.BooleanField(default=False, help_text="Ops kill switch: blocks new reservations and pending purchase confirmations for this event.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return self.title


class TicketType(models.Model):
    # Note: Waitlist functionality is reserved for future implementation.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='ticket_types'
    )
    name = models.CharField(max_length=100)
    total_capacity = models.PositiveIntegerField()
    sold = models.PositiveIntegerField(default=0)
    held = models.PositiveIntegerField(default=0)
    price_cents = models.PositiveIntegerField(help_text="Price in integer cents (e.g., 1000 = $10.00)")
    service_fee_cents = models.PositiveIntegerField(default=0, help_text="Flat per-ticket service fee, in integer cents")
    tax_cents = models.PositiveIntegerField(default=0, help_text="Flat per-ticket tax, in integer cents")
    status = models.CharField(
        max_length=20,
        choices=TicketTypeStatus.choices,
        default=TicketTypeStatus.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['price_cents']
        constraints = [
            models.CheckConstraint(
                check=models.Q(sold__gte=0),
                name='chk_sold_non_negative'
            ),
            models.CheckConstraint(
                check=models.Q(held__gte=0),
                name='chk_held_non_negative'
            ),
            models.CheckConstraint(
                check=models.Q(sold__lte=models.F('total_capacity') - models.F('held')),
                name='chk_no_oversell'
            ),
            models.CheckConstraint(
                check=models.Q(price_cents__gte=0),
                name='chk_price_positive'
            ),
        ]

    @property
    def computed_available(self) -> int:
        """Returns remaining available capacity (total_capacity - sold - held)."""
        return self.total_capacity - self.sold - self.held

    def __str__(self):
        return f"{self.event.title} - {self.name}"

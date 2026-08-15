from datetime import timedelta
from django.db import transaction
from django.db.models import F
from django.utils.timezone import now
from events.models import TicketType
from core.models import AuditLog
from orders.models import Reservation, ReservationStatus
from orders.exceptions import InsufficientCapacityError, ReservationAccessDeniedError, SalesPausedError


def create_reservation(user, ticket_type_id, quantity: int) -> Reservation:
    """
    Creates a ticket reservation holding inventory using SELECT FOR UPDATE row-level locking.
    """
    with transaction.atomic():
        ticket_type = (
            TicketType.objects
            .select_for_update()
            .select_related('event')
            .get(id=ticket_type_id, status='active')
        )

        if ticket_type.event.sales_paused:
            raise SalesPausedError(f"Sales are paused for event {ticket_type.event_id}.")

        available = ticket_type.total_capacity - ticket_type.sold - ticket_type.held
        if available < quantity:
            raise InsufficientCapacityError(
                f"Requested {quantity} tickets, but only {available} available."
            )

        ticket_type.held += quantity
        ticket_type.save(update_fields=['held', 'updated_at'])

        expires_at = now() + timedelta(minutes=ticket_type.event.hold_duration_minutes)

        reservation = Reservation.objects.create(
            user=user,
            ticket_type=ticket_type,
            quantity=quantity,
            status=ReservationStatus.ACTIVE,
            expires_at=expires_at
        )

        AuditLog.record(
            entity_type='ticket_type',
            entity_id=ticket_type.id,
            action='inventory_held',
            actor=user.email,
            changes={
                'held_delta': quantity,
                'reservation_id': str(reservation.id)
            },
            reason="User reserved tickets"
        )

    return reservation


def cancel_reservation(reservation_id, user) -> Reservation:
    """
    Cancels an active reservation and releases held inventory back to ticket_type.
    """
    with transaction.atomic():
        reservation = (
            Reservation.objects
            .select_for_update()
            .select_related('ticket_type')
            .get(id=reservation_id)
        )

        if reservation.user_id != user.id and not user.is_staff:
            raise ReservationAccessDeniedError("You do not have permission to cancel this reservation.")

        if reservation.status == ReservationStatus.ACTIVE:
            ticket_type = reservation.ticket_type
            ticket_type.held = F('held') - reservation.quantity
            ticket_type.save(update_fields=['held', 'updated_at'])

            reservation.status = ReservationStatus.CANCELLED
            reservation.save(update_fields=['status'])

            AuditLog.record(
                entity_type='reservation',
                entity_id=reservation.id,
                action='reservation_cancelled',
                actor=user.email,
                changes={
                    'status_old': ReservationStatus.ACTIVE,
                    'status_new': ReservationStatus.CANCELLED,
                    'quantity_released': reservation.quantity
                },
                reason="User cancelled reservation"
            )

    return reservation

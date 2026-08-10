from django.db import transaction
from django.utils.timezone import now
from core.models import AuditLog
from orders.models import Reservation, ReservationStatus, Order, OrderStatus, Ticket, TicketStatus
from orders.exceptions import ReservationNotActiveError, ReservationExpiredError, PaymentFailedError
from payments.providers import get_payment_provider


def process_purchase(reservation_id, idempotency_key: str, actor_email: str) -> Order:
    """
    Executes the purchase transaction for an active reservation:
    1. Locks reservation row via SELECT FOR UPDATE
    2. Validates reservation status and expiration
    3. Calls PaymentProvider to capture funds
    4. Transitions inventory: held -= quantity, sold += quantity
    5. Creates Order record with unit_price_cents snapshot
    6. Bulk-creates individual Ticket rows
    7. Sets Reservation.status = CONFIRMED
    8. Records AuditLog
    """
    with transaction.atomic():
        reservation = (
            Reservation.objects
            .select_for_update()
            .select_related('ticket_type', 'ticket_type__event', 'user')
            .get(id=reservation_id)
        )

        if reservation.status != ReservationStatus.ACTIVE:
            raise ReservationNotActiveError(f"Reservation {reservation_id} is in status '{reservation.status}'.")

        if reservation.expires_at < now():
            reservation.status = ReservationStatus.EXPIRED
            reservation.save(update_fields=['status'])
            raise ReservationExpiredError(f"Reservation {reservation_id} has expired.")

        ticket_type = reservation.ticket_type
        total_cents = ticket_type.price_cents * reservation.quantity

        # Capture payment via strategy pattern provider
        provider = get_payment_provider()
        result = provider.capture(
            amount_cents=total_cents,
            token="user_payment_token",
            idempotency_key=idempotency_key
        )

        if not result.success:
            raise PaymentFailedError(result.error or "Payment capture failed.")

        # Transition inventory from held to sold
        ticket_type.held -= reservation.quantity
        ticket_type.sold += reservation.quantity
        ticket_type.save(update_fields=['held', 'sold', 'updated_at'])

        # Create Order record
        order = Order.objects.create(
            user=reservation.user,
            event=ticket_type.event,
            reservation=reservation,
            ticket_type=ticket_type,
            idempotency_key=idempotency_key,
            quantity=reservation.quantity,
            unit_price_cents=ticket_type.price_cents,
            total_cents=total_cents,
            status=OrderStatus.CONFIRMED,
            payment_id=result.payment_id or "unknown",
            payment_provider=provider.name,
            confirmed_at=now()
        )

        # Create individual tickets for tracking/refunds
        Ticket.objects.bulk_create([
            Ticket(order=order, status=TicketStatus.ACTIVE)
            for _ in range(reservation.quantity)
        ])

        # Mark reservation confirmed
        reservation.status = ReservationStatus.CONFIRMED
        reservation.save(update_fields=['status'])

        AuditLog.record(
            entity_type='ticket_type',
            entity_id=ticket_type.id,
            action='inventory_sold',
            actor=actor_email,
            changes={
                'held_delta': -reservation.quantity,
                'sold_delta': reservation.quantity,
                'order_id': str(order.id),
                'total_cents': total_cents
            },
            reason="Successful ticket purchase"
        )

    return order

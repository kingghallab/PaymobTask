from django.db import transaction, IntegrityError
from django.db.models import F
from django.utils.timezone import now
from core.models import AuditLog
from events.models import TicketType
from orders.models import Reservation, ReservationStatus, Order, OrderStatus, Ticket, TicketStatus
from orders.exceptions import ReservationNotActiveError, ReservationExpiredError, PaymentFailedError, SalesPausedError
from payments.providers import get_payment_provider


def process_purchase(reservation_id, idempotency_key: str, actor_email: str) -> Order:
    """
    Executes the purchase transaction for an active reservation:
    1. Locks reservation row via SELECT FOR UPDATE
    2. If a request for this Idempotency-Key already completed (e.g. a
       concurrent duplicate that got here first while this call was
       blocked on the lock above), returns that Order untouched instead of
       re-validating a reservation someone else already confirmed.
    3. Validates reservation status and expiration
    4. Creates the Order eagerly, inside a savepoint. The unique
       idempotency_key constraint is the real dedup enforcement - a
       duplicate racing this one on a *different* reservation hits
       IntegrityError here and is handed the winner's Order, rather than
       relying on a pre-check SELECT that can lose a race.
    5. Calls PaymentProvider to capture funds
    6. Transitions inventory: held -= quantity, sold += quantity, via an
       atomic F()-expression UPDATE (not a Python read-modify-write) so two
       concurrent purchases against different reservations of the same
       ticket type can't lose an update.
    7. Bulk-creates individual Ticket rows
    8. Sets Order + Reservation status to confirmed
    9. Records AuditLog

    On a decline, PaymentFailedError is raised AFTER the atomic block below
    exits (not from inside it) - raising from inside would roll back the
    whole transaction, including the Order's FAILED status save, since an
    exception propagating out of transaction.atomic() rolls back everything
    committed within it.
    """
    payment_error = None

    with transaction.atomic():
        reservation = (
            Reservation.objects
            .select_for_update()
            .select_related('ticket_type', 'ticket_type__event', 'user')
            .get(id=reservation_id)
        )

        existing_order = Order.objects.filter(idempotency_key=idempotency_key).first()
        if existing_order is not None:
            AuditLog.record(
                entity_type='order',
                entity_id=existing_order.id,
                action='idempotency_collision',
                actor=actor_email,
                changes={'idempotency_key': idempotency_key},
                reason="Duplicate purchase request with the same Idempotency-Key"
            )
            return existing_order

        if reservation.ticket_type.event.sales_paused:
            raise SalesPausedError(f"Sales are paused for event {reservation.ticket_type.event_id}.")

        if reservation.status != ReservationStatus.ACTIVE:
            raise ReservationNotActiveError(f"Reservation {reservation_id} is in status '{reservation.status}'.")

        if reservation.expires_at < now():
            reservation.status = ReservationStatus.EXPIRED
            reservation.save(update_fields=['status'])
            raise ReservationExpiredError(f"Reservation {reservation_id} has expired.")

        ticket_type = reservation.ticket_type
        total_cents = ticket_type.price_cents * reservation.quantity
        total_fees_cents = ticket_type.service_fee_cents * reservation.quantity
        total_tax_cents = ticket_type.tax_cents * reservation.quantity

        try:
            with transaction.atomic():
                order = Order.objects.create(
                    user=reservation.user,
                    event=ticket_type.event,
                    reservation=reservation,
                    ticket_type=ticket_type,
                    idempotency_key=idempotency_key,
                    quantity=reservation.quantity,
                    unit_price_cents=ticket_type.price_cents,
                    total_cents=total_cents,
                    total_fees_cents=total_fees_cents,
                    total_tax_cents=total_tax_cents,
                    status=OrderStatus.PROCESSING,
                )
        except IntegrityError:
            existing_order = Order.objects.get(idempotency_key=idempotency_key)
            AuditLog.record(
                entity_type='order',
                entity_id=existing_order.id,
                action='idempotency_collision',
                actor=actor_email,
                changes={'idempotency_key': idempotency_key},
                reason="Duplicate purchase request with the same Idempotency-Key"
            )
            return existing_order

        # Capture payment via strategy pattern provider
        provider = get_payment_provider()
        result = provider.capture(
            amount_cents=total_cents + total_fees_cents + total_tax_cents,
            token="user_payment_token",
            idempotency_key=idempotency_key
        )

        if not result.success:
            order.status = OrderStatus.FAILED
            order.save(update_fields=['status'])
            payment_error = result.error or "Payment capture failed."
        else:
            # Transition inventory from held to sold via an atomic F()-update
            TicketType.objects.filter(id=ticket_type.id).update(
                held=F('held') - reservation.quantity,
                sold=F('sold') + reservation.quantity,
            )

            # Create individual tickets for tracking/refunds
            Ticket.objects.bulk_create([
                Ticket(order=order, status=TicketStatus.ACTIVE)
                for _ in range(reservation.quantity)
            ])

            order.status = OrderStatus.CONFIRMED
            order.payment_id = result.payment_id or "unknown"
            order.payment_provider = provider.name
            order.confirmed_at = now()
            order.save(update_fields=['status', 'payment_id', 'payment_provider', 'confirmed_at'])

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

    if payment_error is not None:
        raise PaymentFailedError(payment_error)

    return order

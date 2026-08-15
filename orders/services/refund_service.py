from django.db import transaction
from django.db.models import F
from django.utils.timezone import now
from core.models import AuditLog
from events.models import TicketType
from orders.models import Order, OrderStatus, Ticket, TicketStatus, Refund, RefundStatus
from orders.exceptions import InvalidRefundError, PaymentRefundFailedError
from payments.providers import get_payment_provider


def issue_refund(order_id, user, ticket_ids: list = None, reason: str = "", actor_email: str = "") -> Refund:
    """
    Issues a full or partial refund for an order:
    1. Locks Order row via SELECT FOR UPDATE, scoped to the requesting user
       unless they're staff (mirrors reservation_service.cancel_reservation's
       ownership check)
    2. Validates active tickets available for refund
    3. Calls PaymentProvider to refund captured funds - price plus a
       proportional share of fees/tax for the refunded tickets
    4. Creates Refund audit record
    5. Marks target tickets as 'refunded'
    6. Restores inventory by decrementing TicketType.sold by ticket_count
    7. Updates Order status to 'refunded' or 'partially_refunded'
    8. Records AuditLog
    """
    with transaction.atomic():
        if user is not None and not user.is_staff:
            order = Order.objects.select_for_update().get(id=order_id, user=user)
        else:
            order = Order.objects.select_for_update().get(id=order_id)

        if order.status in (OrderStatus.REFUNDED, OrderStatus.FAILED):
            raise InvalidRefundError(f"Cannot refund order {order_id} with status '{order.status}'.")

        if ticket_ids:
            tickets = Ticket.objects.filter(id__in=ticket_ids, order=order, status=TicketStatus.ACTIVE)
        else:
            tickets = Ticket.objects.filter(order=order, status=TicketStatus.ACTIVE)

        if not tickets.exists():
            raise InvalidRefundError("No active tickets available for refund on this order.")

        ticket_count = tickets.count()

        # Fee/tax are flat-per-unit amounts multiplied by quantity to get the
        # order total, so dividing back by quantity recovers the exact
        # per-unit amount with no rounding - a partial refund gets a fair
        # share of fees/tax, not just a share of the price.
        unit_fee_cents = order.total_fees_cents // order.quantity
        unit_tax_cents = order.total_tax_cents // order.quantity
        refund_amount_cents = (order.unit_price_cents + unit_fee_cents + unit_tax_cents) * ticket_count

        # Call payment provider refund interface
        provider = get_payment_provider()
        result = provider.refund(payment_id=order.payment_id, amount_cents=refund_amount_cents)

        if not result.success:
            raise PaymentRefundFailedError(result.error or "Refund gateway call failed.")

        # Create Refund record
        refund = Refund.objects.create(
            order=order,
            amount_cents=refund_amount_cents,
            reason=reason,
            status=RefundStatus.PROCESSED,
            initiated_by=actor_email,
            payment_refund_id=result.payment_id or "unknown",
            processed_at=now()
        )

        # Mark targeted tickets as refunded
        ticket_list = list(tickets)
        tickets.update(status=TicketStatus.REFUNDED)

        if ticket_ids and len(ticket_list) == 1:
            refund.ticket = ticket_list[0]
            refund.save(update_fields=['ticket'])

        # Restore inventory: decrement sold counter atomically
        TicketType.objects.filter(id=order.ticket_type_id).update(
            sold=F('sold') - ticket_count
        )

        # Update order status based on remaining active tickets
        remaining_active = Ticket.objects.filter(order=order, status=TicketStatus.ACTIVE).count()
        order.status = OrderStatus.REFUNDED if remaining_active == 0 else OrderStatus.PARTIALLY_REFUNDED
        order.save(update_fields=['status'])

        AuditLog.record(
            entity_type='refund',
            entity_id=refund.id,
            action='refund_issued',
            actor=actor_email,
            changes={
                'order_id': str(order.id),
                'refund_amount_cents': refund_amount_cents,
                'tickets_refunded': ticket_count,
                'order_status_new': order.status
            },
            reason=reason or "Customer refund requested"
        )

    return refund

import csv
import io
from django.db.models import Sum
from core.models import AuditLog
from core.reconciliation import compute_actual_counts
from events.models import Event, TicketType
from orders.models import Order, Ticket, Refund, OrderStatus


def generate_sales_csv(start_date=None, end_date=None) -> str:
    """
    Generates a daily sales CSV report: one row per (event, day) that had at
    least one order placed, where "day" is the date the order was actually
    created - not the event's start date. Refunds are attributed to the day
    of the original order, not the day the refund itself was issued.

    Fees/tax are reported as their own columns rather than folded into a
    single total - together with Order storing price/fee/tax as separate
    totals and one Ticket row per unit, this is the "line-item breakdown"
    finance needs (brief §2); no separate OrderLineItem entity is needed for
    a project where every order is for exactly one ticket type.

    Columns: date, event_id, event_title, orders_count, gross_revenue_cents,
             total_fees_cents, total_tax_cents, total_refunds_cents, net_revenue_cents
    net_revenue_cents = gross_revenue_cents + total_fees_cents + total_tax_cents - total_refunds_cents
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'date', 'event_id', 'event_title', 'orders_count',
        'gross_revenue_cents', 'total_fees_cents', 'total_tax_cents',
        'total_refunds_cents', 'net_revenue_cents'
    ])

    orders_query = Order.objects.filter(
        status__in=[OrderStatus.CONFIRMED, OrderStatus.PARTIALLY_REFUNDED, OrderStatus.REFUNDED]
    ).select_related('event')
    if start_date:
        orders_query = orders_query.filter(created_at__date__gte=start_date)
    if end_date:
        orders_query = orders_query.filter(created_at__date__lte=end_date)

    orders = list(orders_query)
    refund_totals = dict(
        Refund.objects.filter(order__in=orders)
        .values('order_id')
        .annotate(total=Sum('amount_cents'))
        .values_list('order_id', 'total')
    )

    buckets = {}
    for order in orders:
        key = (order.event_id, order.created_at.date())
        bucket = buckets.setdefault(key, {
            'event_title': order.event.title,
            'orders_count': 0,
            'gross_revenue_cents': 0,
            'total_fees_cents': 0,
            'total_tax_cents': 0,
            'total_refunds_cents': 0,
        })
        bucket['orders_count'] += 1
        bucket['gross_revenue_cents'] += order.total_cents
        bucket['total_fees_cents'] += order.total_fees_cents
        bucket['total_tax_cents'] += order.total_tax_cents
        bucket['total_refunds_cents'] += refund_totals.get(order.id, 0)

    for (event_id, day), bucket in sorted(buckets.items(), key=lambda kv: (kv[0][1], kv[1]['event_title'])):
        gross = bucket['gross_revenue_cents']
        fees = bucket['total_fees_cents']
        tax = bucket['total_tax_cents']
        refunds = bucket['total_refunds_cents']
        net = gross + fees + tax - refunds
        writer.writerow([
            day.isoformat(), str(event_id), bucket['event_title'],
            bucket['orders_count'], gross, fees, tax, refunds, net
        ])

    return output.getvalue()


def generate_attendee_csv(event_id=None) -> str:
    """
    Generates an attendee CSV export with contact info and check-in status
    (brief §6). Checked-in status is `checked_in_at is not None` - the
    column reports the timestamp directly; an empty value means not
    checked in.
    Columns: ticket_id, order_id, first_name, last_name, user_email, phone,
             ticket_type, unit_price_cents, ticket_status, checked_in_at
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ticket_id', 'order_id', 'first_name', 'last_name', 'user_email', 'phone',
        'ticket_type', 'unit_price_cents', 'ticket_status', 'checked_in_at'
    ])

    tickets_query = Ticket.objects.select_related('order', 'order__user', 'order__ticket_type').all()
    if event_id:
        tickets_query = tickets_query.filter(order__event_id=event_id)

    for ticket in tickets_query:
        writer.writerow([
            str(ticket.id),
            str(ticket.order_id),
            ticket.order.user.first_name,
            ticket.order.user.last_name,
            ticket.order.user.email,
            ticket.order.user.phone,
            ticket.order.ticket_type.name,
            ticket.order.unit_price_cents,
            ticket.status,
            ticket.checked_in_at.isoformat() if ticket.checked_in_at else ''
        ])

    return output.getvalue()


def generate_audit_csv(start_date=None, end_date=None) -> str:
    """
    Generates an audit export for inventory/order lifecycle changes (brief
    §6). AuditLog already has every field this needs - no model change.
    Columns: timestamp, entity_type, entity_id, action, actor, reason
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['timestamp', 'entity_type', 'entity_id', 'action', 'actor', 'reason'])

    logs = AuditLog.objects.all().order_by('created_at')
    if start_date:
        logs = logs.filter(created_at__date__gte=start_date)
    if end_date:
        logs = logs.filter(created_at__date__lte=end_date)

    for log in logs:
        writer.writerow([
            log.created_at.isoformat(), log.entity_type, str(log.entity_id),
            log.action, log.actor, log.reason
        ])

    return output.getvalue()


def generate_reconciliation_csv(event_id=None) -> str:
    """
    Generates an inventory reconciliation CSV report comparing stored counters against derived database counts.
    Columns: ticket_type_id, name, total_capacity, sold, held, computed_available, actual_sold, actual_held, drift_sold, drift_held, status
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ticket_type_id', 'name', 'total_capacity',
        'sold', 'held', 'computed_available',
        'actual_sold', 'actual_held',
        'drift_sold', 'drift_held', 'status'
    ])

    ticket_types = TicketType.objects.select_related('event').all()
    if event_id:
        ticket_types = ticket_types.filter(event_id=event_id)

    for tt in ticket_types:
        actual_sold, actual_held = compute_actual_counts(tt)

        drift_sold = actual_sold - tt.sold
        drift_held = actual_held - tt.held
        status_str = "OK" if (drift_sold == 0 and drift_held == 0) else "DRIFT_DETECTED"

        writer.writerow([
            str(tt.id), tt.name, tt.total_capacity,
            tt.sold, tt.held, tt.computed_available,
            actual_sold, actual_held,
            drift_sold, drift_held, status_str
        ])

    return output.getvalue()

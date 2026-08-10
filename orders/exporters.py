import csv
import io
from django.db.models import Sum, Count, Q
from events.models import Event, TicketType
from orders.models import Order, Ticket, Reservation, OrderStatus, TicketStatus, ReservationStatus


def generate_sales_csv(start_date=None, end_date=None) -> str:
    """
    Generates a daily sales CSV report.
    Columns: date, event_id, event_title, orders_count, gross_revenue_cents, total_refunds_cents, net_revenue_cents
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'date', 'event_id', 'event_title',
        'orders_count', 'gross_revenue_cents',
        'total_refunds_cents', 'net_revenue_cents'
    ])

    orders_query = Order.objects.filter(status__in=[OrderStatus.CONFIRMED, OrderStatus.PARTIALLY_REFUNDED, OrderStatus.REFUNDED])
    if start_date:
        orders_query = orders_query.filter(created_at__date__gte=start_date)
    if end_date:
        orders_query = orders_query.filter(created_at__date__lte=end_date)

    events = Event.objects.all()

    for event in events:
        event_orders = orders_query.filter(event=event)
        orders_count = event_orders.count()
        if orders_count == 0:
            continue

        gross_cents = event_orders.aggregate(total=Sum('total_cents'))['total'] or 0
        refunds_cents = 0

        for order in event_orders:
            refunded_count = order.tickets.filter(status=TicketStatus.REFUNDED).count()
            refunds_cents += refunded_count * order.unit_price_cents

        net_cents = gross_cents - refunds_cents
        date_str = event.start_date.strftime('%Y-%m-%d')

        writer.writerow([
            date_str, str(event.id), event.title,
            orders_count, gross_cents, refunds_cents, net_cents
        ])

    return output.getvalue()


def generate_attendee_csv(event_id=None) -> str:
    """
    Generates an attendee CSV export.
    Columns: ticket_id, order_id, user_email, ticket_type, unit_price_cents, ticket_status
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ticket_id', 'order_id', 'user_email',
        'ticket_type', 'unit_price_cents', 'ticket_status'
    ])

    tickets_query = Ticket.objects.select_related('order', 'order__user', 'order__ticket_type').all()
    if event_id:
        tickets_query = tickets_query.filter(order__event_id=event_id)

    for ticket in tickets_query:
        writer.writerow([
            str(ticket.id),
            str(ticket.order_id),
            ticket.order.user.email,
            ticket.order.ticket_type.name,
            ticket.order.unit_price_cents,
            ticket.status
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
        actual_sold = Ticket.objects.filter(order__ticket_type=tt, status=TicketStatus.ACTIVE).count()
        actual_held = Reservation.objects.filter(ticket_type=tt, status=ReservationStatus.ACTIVE).count()

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

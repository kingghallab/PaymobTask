from django.db.models import Sum
from orders.models import Ticket, Reservation, TicketStatus, ReservationStatus


def compute_actual_counts(ticket_type):
    """
    Derives the true sold/held counts for a TicketType directly from Ticket
    and Reservation rows, for comparison against the stored counters.

    actual_sold counts Ticket ROWS because Ticket rows are exploded one per
    unit at purchase time. actual_held must SUM Reservation.quantity instead
    of counting rows, because a single Reservation row represents its whole
    quantity - counting rows undercounts any reservation with quantity > 1.
    """
    actual_sold = Ticket.objects.filter(order__ticket_type=ticket_type, status=TicketStatus.ACTIVE).count()
    actual_held = Reservation.objects.filter(
        ticket_type=ticket_type, status=ReservationStatus.ACTIVE
    ).aggregate(total=Sum('quantity'))['total'] or 0
    return actual_sold, actual_held

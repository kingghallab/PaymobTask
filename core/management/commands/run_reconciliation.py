import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from events.models import TicketType
from orders.models import Ticket, TicketStatus, Reservation, ReservationStatus

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Runs inventory reconciliation comparing stored sold/held counters against active database records."

    def add_arguments(self, parser):
        parser.add_argument('--event-id', type=str, help='Optional Event UUID filter')
        parser.add_argument('--fix', action='store_true', help='Auto-correct counter drift in DB')

    def handle(self, *args, **options):
        event_id = options.get('event_id')
        fix = options.get('fix')

        ticket_types = TicketType.objects.select_related('event').all()
        if event_id:
            ticket_types = ticket_types.filter(event_id=event_id)

        drift_found = 0

        self.stdout.write(self.style.SUCCESS("Starting inventory reconciliation audit..."))

        for tt in ticket_types:
            actual_sold = Ticket.objects.filter(order__ticket_type=tt, status=TicketStatus.ACTIVE).count()
            actual_held = Reservation.objects.filter(ticket_type=tt, status=ReservationStatus.ACTIVE).count()

            drift_sold = actual_sold - tt.sold
            drift_held = actual_held - tt.held

            if drift_sold != 0 or drift_held != 0:
                drift_found += 1
                msg = f"DRIFT DETECTED for TicketType '{tt.name}' ({tt.id}): Stored (sold={tt.sold}, held={tt.held}) vs Actual (sold={actual_sold}, held={actual_held}). Drift: sold_delta={drift_sold}, held_delta={drift_held}"
                self.stdout.write(self.style.ERROR(msg))
                logger.error(msg)

                if fix:
                    with transaction.atomic():
                        tt.sold = actual_sold
                        tt.held = actual_held
                        tt.save(update_fields=['sold', 'held', 'updated_at'])
                    self.stdout.write(self.style.WARNING(f"Auto-corrected counters for TicketType '{tt.name}'"))
            else:
                self.stdout.write(f"OK: TicketType '{tt.name}' ({tt.id}) sold={tt.sold}, held={tt.held}")

        if drift_found == 0:
            self.stdout.write(self.style.SUCCESS("Reconciliation completed cleanly. Zero drift detected!"))
        else:
            self.stdout.write(self.style.WARNING(f"Reconciliation finished with {drift_found} drift issues detected."))

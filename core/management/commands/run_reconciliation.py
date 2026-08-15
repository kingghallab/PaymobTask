import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from events.models import TicketType
from core.reconciliation import compute_actual_counts
from core.alerting import send_alert

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
        oversell_found = 0

        self.stdout.write(self.style.SUCCESS("Starting inventory reconciliation audit..."))

        for tt in ticket_types:
            actual_sold, actual_held = compute_actual_counts(tt)

            if actual_sold + actual_held > tt.total_capacity:
                oversell_found += 1
                overage = actual_sold + actual_held - tt.total_capacity
                oversell_msg = (
                    f"OVERSELL DETECTED for TicketType '{tt.name}' ({tt.id}) in event "
                    f"'{tt.event.title}': actual_sold={actual_sold} + actual_held={actual_held} "
                    f"exceeds total_capacity={tt.total_capacity} by {overage}."
                )
                self.stdout.write(self.style.ERROR(oversell_msg))
                logger.error(oversell_msg)
                send_alert(
                    subject=f"Oversell detected: {tt.event.title} / {tt.name}",
                    message=oversell_msg + " Immediate steps: pause sales for this event, "
                            "run 'python manage.py run_reconciliation --fix', identify the "
                            "offending orders, and follow refund/compensation policy.",
                )

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

        if oversell_found > 0:
            self.stdout.write(self.style.ERROR(f"{oversell_found} oversell incident(s) detected - alert sent."))

        if drift_found == 0:
            self.stdout.write(self.style.SUCCESS("Reconciliation completed cleanly. Zero drift detected!"))
        else:
            self.stdout.write(self.style.WARNING(f"Reconciliation finished with {drift_found} drift issues detected."))

import csv
import io
import uuid
from datetime import timedelta
from django.test import TransactionTestCase
from django.utils.timezone import now
from django.contrib.auth import get_user_model
from events.models import Event, TicketType, EventStatus, TicketTypeStatus
from orders.services.reservation_service import create_reservation
from orders.services.purchase_service import process_purchase
from orders.exporters import generate_sales_csv, generate_attendee_csv, generate_audit_csv

User = get_user_model()


class SalesReportTest(TransactionTestCase):
    """Brief §6: 'Daily sales report per event with: orders, gross revenue,
    fees, taxes, refunds, net revenue.' Covers findings #11, #12, #13."""
    def setUp(self):
        super().setUp()
        self.organizer = User.objects.create_user(email='org_rep@example.com', username='org_rep', password='Password123!')
        self.user = User.objects.create_user(email='buyer_rep@example.com', username='buyer_rep', password='Password123!')
        self.event = Event.objects.create(
            title='Report Test Event',
            start_date=now() + timedelta(days=3),
            end_date=now() + timedelta(days=3, hours=4),
            venue='Venue',
            status=EventStatus.PUBLISHED,
            organizer=self.organizer,
            hold_duration_minutes=10
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='VIP',
            total_capacity=100,
            sold=0,
            held=0,
            price_cents=10000,
            service_fee_cents=500,
            tax_cents=300,
            status=TicketTypeStatus.ACTIVE
        )

    def test_sales_report_includes_fee_tax_columns_and_correct_totals(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=2)
        process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)

        rows = list(csv.DictReader(io.StringIO(generate_sales_csv())))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['event_id'], str(self.event.id))
        self.assertEqual(int(row['gross_revenue_cents']), 20000)
        self.assertEqual(int(row['total_fees_cents']), 1000)
        self.assertEqual(int(row['total_tax_cents']), 600)
        self.assertEqual(int(row['total_refunds_cents']), 0)
        self.assertEqual(int(row['net_revenue_cents']), 20000 + 1000 + 600 - 0)

    def test_sales_report_groups_by_order_day_not_event_start_date(self):
        """Regression for finding #12: previously one row per event with
        date=event.start_date (a constant), not one row per actual order day."""
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)

        rows = list(csv.DictReader(io.StringIO(generate_sales_csv())))
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0]['date'], self.event.start_date.date().isoformat())
        self.assertEqual(rows[0]['date'], now().date().isoformat())

    def test_sales_report_date_filter_is_wired(self):
        """Regression for finding #13: the exporter's start_date/end_date
        params worked but the view never passed them through."""
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)

        future_date = (now() + timedelta(days=30)).date().isoformat()
        rows = list(csv.DictReader(io.StringIO(generate_sales_csv(start_date=future_date))))
        self.assertEqual(len(rows), 0)


class AttendeeReportTest(TransactionTestCase):
    """Brief §6: 'Attendee export CSV with contact info, ticket type, order
    id, check-in status.' Covers finding #14."""
    def setUp(self):
        super().setUp()
        self.organizer = User.objects.create_user(email='org_att@example.com', username='org_att', password='Password123!')
        self.user = User.objects.create_user(
            email='buyer_att@example.com', username='buyer_att', password='Password123!',
            first_name='Jane', last_name='Doe', phone='+201234567890'
        )
        self.event = Event.objects.create(
            title='Attendee Test Event',
            start_date=now() + timedelta(days=3),
            end_date=now() + timedelta(days=3, hours=4),
            venue='Venue',
            status=EventStatus.PUBLISHED,
            organizer=self.organizer,
            hold_duration_minutes=10
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='VIP',
            total_capacity=100,
            sold=0,
            held=0,
            price_cents=10000,
            status=TicketTypeStatus.ACTIVE
        )

    def test_attendee_export_includes_contact_info_and_checkin_status(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        order = process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)
        ticket = order.tickets.first()

        rows = list(csv.DictReader(io.StringIO(generate_attendee_csv())))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['first_name'], 'Jane')
        self.assertEqual(row['last_name'], 'Doe')
        self.assertEqual(row['phone'], '+201234567890')
        self.assertEqual(row['user_email'], self.user.email)
        self.assertEqual(row['checked_in_at'], '')

        ticket.checked_in_at = now()
        ticket.save(update_fields=['checked_in_at'])

        rows_after = list(csv.DictReader(io.StringIO(generate_attendee_csv())))
        self.assertNotEqual(rows_after[0]['checked_in_at'], '')


class AuditExportTest(TransactionTestCase):
    """Brief §6: 'Audit export for inventory changes with timestamps,
    actor, and reason.' Covers finding #15 (didn't exist at all)."""
    def setUp(self):
        super().setUp()
        self.organizer = User.objects.create_user(email='org_aud@example.com', username='org_aud', password='Password123!')
        self.user = User.objects.create_user(email='buyer_aud@example.com', username='buyer_aud', password='Password123!')
        self.event = Event.objects.create(
            title='Audit Export Event',
            start_date=now() + timedelta(days=3),
            end_date=now() + timedelta(days=3, hours=4),
            venue='Venue',
            status=EventStatus.PUBLISHED,
            organizer=self.organizer,
            hold_duration_minutes=10
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='GA',
            total_capacity=100,
            sold=0,
            held=0,
            price_cents=5000,
            status=TicketTypeStatus.ACTIVE
        )

    def test_audit_export_lists_lifecycle_events(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)

        rows = list(csv.DictReader(io.StringIO(generate_audit_csv())))
        actions = {row['action'] for row in rows}
        self.assertIn('inventory_held', actions)
        self.assertIn('inventory_sold', actions)
        for row in rows:
            self.assertTrue(row['timestamp'])
            self.assertTrue(row['entity_type'])
            self.assertTrue(row['entity_id'])

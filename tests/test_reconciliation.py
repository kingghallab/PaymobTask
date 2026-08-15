import io
import uuid
from datetime import timedelta
from django.test import TransactionTestCase
from django.utils.timezone import now
from django.core import mail
from django.core.management import call_command
from django.contrib.auth import get_user_model
from events.models import Event, TicketType, EventStatus, TicketTypeStatus
from orders.models import Reservation, ReservationStatus
from orders.services.reservation_service import create_reservation
from orders.services.purchase_service import process_purchase
from orders.services.refund_service import issue_refund

User = get_user_model()


class ReconciliationTest(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.organizer = User.objects.create_user(email='org@example.com', username='org', password='Password123!')
        self.user = User.objects.create_user(email='buyer@example.com', username='buyer', password='Password123!')
        self.event = Event.objects.create(
            title='Exhibition',
            start_date=now() + timedelta(days=10),
            end_date=now() + timedelta(days=10, hours=5),
            venue='Center',
            status=EventStatus.PUBLISHED,
            organizer=self.organizer,
            hold_duration_minutes=10
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='Pass',
            total_capacity=100,
            sold=0,
            held=0,
            price_cents=3000,
            status=TicketTypeStatus.ACTIVE
        )

    def test_reconciliation_zero_drift(self):
        # 1. Create reservation (held=2)
        res1 = create_reservation(self.user, self.ticket_type.id, quantity=2)
        
        # 2. Purchase reservation (held=0, sold=2)
        order1 = process_purchase(res1.id, f"key_{uuid.uuid4().hex}", self.user.email)

        # 3. Create second reservation (held=1)
        res2 = create_reservation(self.user, self.ticket_type.id, quantity=1)

        # Run reconciliation command and capture output
        out = io.StringIO()
        call_command('run_reconciliation', stdout=out)
        output_text = out.getvalue()

        self.assertIn("Zero drift detected", output_text)

        # 4. Issue full refund for order1 (sold=0, held=1)
        issue_refund(order1.id, user=self.user, reason="Customer refund", actor_email=self.user.email)

        out_after_refund = io.StringIO()
        call_command('run_reconciliation', stdout=out_after_refund)
        self.assertIn("Zero drift detected", out_after_refund.getvalue())

    def test_oversell_detection_triggers_alert(self):
        """
        Brief §2: "any oversell incident triggers immediate alerting". Fills
        capacity via a real purchase, then creates one extra ACTIVE
        Reservation directly via the ORM - bypassing create_reservation()'s
        capacity check - to simulate the genuine oversell condition
        chk_no_oversell prevents through the normal code path.
        """
        limited = TicketType.objects.create(
            event=self.event,
            name='Limited',
            total_capacity=2,
            sold=0,
            held=0,
            price_cents=1000,
            status=TicketTypeStatus.ACTIVE
        )
        res = create_reservation(self.user, limited.id, quantity=2)
        process_purchase(res.id, f"key_{uuid.uuid4().hex}", self.user.email)

        Reservation.objects.create(
            user=self.user,
            ticket_type=limited,
            quantity=1,
            status=ReservationStatus.ACTIVE,
            expires_at=now() + timedelta(minutes=10)
        )

        out = io.StringIO()
        call_command('run_reconciliation', stdout=out)

        self.assertIn("OVERSELL DETECTED", out.getvalue())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Oversell detected", mail.outbox[0].subject)

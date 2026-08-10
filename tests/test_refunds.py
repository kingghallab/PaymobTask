import uuid
from datetime import timedelta
from django.test import TransactionTestCase
from django.utils.timezone import now
from django.contrib.auth import get_user_model
from events.models import Event, TicketType, EventStatus, TicketTypeStatus
from orders.models import OrderStatus, TicketStatus
from orders.services.reservation_service import create_reservation
from orders.services.purchase_service import process_purchase
from orders.services.refund_service import issue_refund
from orders.exceptions import InvalidRefundError
from core.models import AuditLog

User = get_user_model()


class RefundFlowTest(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        super().setUp()
        self.organizer = User.objects.create_user(email='org@example.com', username='org', password='Password123!')
        self.user = User.objects.create_user(email='buyer@example.com', username='buyer', password='Password123!')
        self.event = Event.objects.create(
            title='Tech Conf',
            start_date=now() + timedelta(days=5),
            end_date=now() + timedelta(days=5, hours=8),
            venue='Hall A',
            status=EventStatus.PUBLISHED,
            organizer=self.organizer,
            hold_duration_minutes=10
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='Standard',
            total_capacity=50,
            sold=0,
            held=0,
            price_cents=10000,
            status=TicketTypeStatus.ACTIVE
        )

    def test_full_refund_restores_inventory(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=3)
        order = process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)

        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.sold, 3)

        refund = issue_refund(order.id, reason="Event rescheduled", actor_email=self.user.email)

        order.refresh_from_db()
        self.ticket_type.refresh_from_db()

        self.assertEqual(refund.amount_cents, 30000)
        self.assertEqual(order.status, OrderStatus.REFUNDED)
        self.assertEqual(self.ticket_type.sold, 0)
        self.assertTrue(AuditLog.objects.filter(entity_type='order', action='refund_issued').exists())

    def test_partial_refund_updates_status(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=2)
        order = process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)

        tickets = list(order.tickets.all())
        target_ticket_id = tickets[0].id

        refund = issue_refund(order.id, ticket_ids=[target_ticket_id], reason="1 attendee cancelled", actor_email=self.user.email)

        order.refresh_from_db()
        self.ticket_type.refresh_from_db()
        tickets[0].refresh_from_db()
        tickets[1].refresh_from_db()

        self.assertEqual(refund.amount_cents, 10000)
        self.assertEqual(order.status, OrderStatus.PARTIALLY_REFUNDED)
        self.assertEqual(self.ticket_type.sold, 1)
        self.assertEqual(tickets[0].status, TicketStatus.REFUNDED)
        self.assertEqual(tickets[1].status, TicketStatus.ACTIVE)

    def test_double_refund_prevention(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        order = process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)

        issue_refund(order.id, reason="First refund", actor_email=self.user.email)

        with self.assertRaises(InvalidRefundError):
            issue_refund(order.id, reason="Second refund attempt", actor_email=self.user.email)

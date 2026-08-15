import uuid
from datetime import timedelta
from django.test import TransactionTestCase
from django.utils.timezone import now
from django.contrib.auth import get_user_model
from events.models import Event, TicketType, EventStatus, TicketTypeStatus
from orders.models import Order, OrderStatus, TicketStatus
from orders.services.reservation_service import create_reservation
from orders.services.purchase_service import process_purchase
from orders.services.refund_service import issue_refund
from orders.exceptions import InvalidRefundError
from core.models import AuditLog

User = get_user_model()


class RefundFlowTest(TransactionTestCase):
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

        refund = issue_refund(order.id, user=self.user, reason="Event rescheduled", actor_email=self.user.email)

        order.refresh_from_db()
        self.ticket_type.refresh_from_db()

        self.assertEqual(refund.amount_cents, 30000)
        self.assertEqual(order.status, OrderStatus.REFUNDED)
        self.assertEqual(self.ticket_type.sold, 0)
        self.assertTrue(AuditLog.objects.filter(entity_type='refund', action='refund_issued').exists())

    def test_partial_refund_updates_status(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=2)
        order = process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)

        tickets = list(order.tickets.all())
        target_ticket_id = tickets[0].id

        refund = issue_refund(order.id, user=self.user, ticket_ids=[target_ticket_id], reason="1 attendee cancelled", actor_email=self.user.email)

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

        issue_refund(order.id, user=self.user, reason="First refund", actor_email=self.user.email)

        with self.assertRaises(InvalidRefundError):
            issue_refund(order.id, user=self.user, reason="Second refund attempt", actor_email=self.user.email)

    def test_non_owner_refund_denied(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        order = process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)

        stranger = User.objects.create_user(email='stranger@example.com', username='stranger', password='Password123!')

        with self.assertRaises(Order.DoesNotExist):
            issue_refund(order.id, user=stranger, reason="Not my order", actor_email=stranger.email)

    def test_staff_can_refund_any_order(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        order = process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)

        staff_user = User.objects.create_user(
            email='staff@example.com', username='staff', password='Password123!', is_staff=True
        )

        refund = issue_refund(order.id, user=staff_user, reason="Staff-issued refund", actor_email=staff_user.email)
        self.assertEqual(refund.amount_cents, 10000)

    def test_partial_refund_includes_proportional_fee_and_tax(self):
        self.ticket_type.service_fee_cents = 100
        self.ticket_type.tax_cents = 50
        self.ticket_type.save(update_fields=['service_fee_cents', 'tax_cents'])

        reservation = create_reservation(self.user, self.ticket_type.id, quantity=2)
        order = process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)
        self.assertEqual(order.total_fees_cents, 200)
        self.assertEqual(order.total_tax_cents, 100)

        target_ticket_id = order.tickets.first().id
        refund = issue_refund(
            order.id, user=self.user, ticket_ids=[target_ticket_id],
            reason="1 attendee cancelled", actor_email=self.user.email
        )

        # price 10000 + proportional fee (200/2=100) + proportional tax (100/2=50)
        self.assertEqual(refund.amount_cents, 10150)

    def test_refund_amount_reflected_in_sales_report(self):
        """
        Brief §4 Functional AC: "Refunds update inventory and finance
        exports correctly." The sales report must read the actual
        Refund.amount_cents (including its fee/tax share) rather than
        recompute a price-only figure from ticket counts.
        """
        import csv
        import io
        from orders.exporters import generate_sales_csv

        self.ticket_type.service_fee_cents = 100
        self.ticket_type.tax_cents = 50
        self.ticket_type.save(update_fields=['service_fee_cents', 'tax_cents'])

        reservation = create_reservation(self.user, self.ticket_type.id, quantity=2)
        order = process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)
        target_ticket_id = order.tickets.first().id
        refund = issue_refund(
            order.id, user=self.user, ticket_ids=[target_ticket_id],
            reason="1 attendee cancelled", actor_email=self.user.email
        )

        rows = list(csv.DictReader(io.StringIO(generate_sales_csv())))
        matching = [r for r in rows if r['event_id'] == str(self.event.id)]
        self.assertEqual(len(matching), 1)
        self.assertEqual(int(matching[0]['total_refunds_cents']), refund.amount_cents)


class AuditTrailCoverageTest(TransactionTestCase):
    """
    Brief §4 Operational AC: "Audit trail exists for every inventory change
    and order lifecycle event." Enumerates each lifecycle event and asserts
    it writes an AuditLog row under the entity_type the runbook doc assumes
    lookups will use (finding #9).
    """
    def setUp(self):
        super().setUp()
        self.organizer = User.objects.create_user(email='org_audit@example.com', username='org_audit', password='Password123!')
        self.user = User.objects.create_user(email='buyer_audit@example.com', username='buyer_audit', password='Password123!')
        self.event = Event.objects.create(
            title='Audit Trail Event',
            start_date=now() + timedelta(days=5),
            end_date=now() + timedelta(days=5, hours=3),
            venue='Hall B',
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
            price_cents=5000,
            status=TicketTypeStatus.ACTIVE
        )

    def test_hold_created_is_audited(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        self.assertTrue(AuditLog.objects.filter(
            entity_type='ticket_type', entity_id=self.ticket_type.id, action='inventory_held'
        ).exists())

    def test_sale_is_audited(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)
        self.assertTrue(AuditLog.objects.filter(
            entity_type='ticket_type', entity_id=self.ticket_type.id, action='inventory_sold'
        ).exists())

    def test_cancellation_is_audited(self):
        from orders.services.reservation_service import cancel_reservation
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        cancel_reservation(reservation.id, self.user)
        self.assertTrue(AuditLog.objects.filter(
            entity_type='reservation', entity_id=reservation.id, action='reservation_cancelled'
        ).exists())

    def test_expiry_is_audited(self):
        from orders.tasks import sweep_expired_reservations
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        reservation.expires_at = now() - timedelta(minutes=1)
        reservation.save(update_fields=['expires_at'])

        sweep_expired_reservations()

        self.assertTrue(AuditLog.objects.filter(
            entity_type='reservation', entity_id=reservation.id, action='reservation_expired'
        ).exists())

    def test_refund_is_audited(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        order = process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)
        refund = issue_refund(order.id, user=self.user, reason="test", actor_email=self.user.email)
        self.assertTrue(AuditLog.objects.filter(
            entity_type='refund', entity_id=refund.id, action='refund_issued'
        ).exists())

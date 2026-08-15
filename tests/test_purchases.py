import concurrent.futures
import uuid
from datetime import timedelta
from unittest import mock
from django.test import TransactionTestCase
from django.utils.timezone import now
from django.db import connection
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from core.models import AuditLog, FailedTask
from events.models import Event, TicketType, EventStatus, TicketTypeStatus
from orders.models import Reservation, Order, Ticket, OrderStatus, TicketStatus
from orders.services.reservation_service import create_reservation
from orders.services.purchase_service import process_purchase
from orders.exceptions import ReservationExpiredError, PaymentFailedError
from orders.tasks import process_purchase_task
from payments.providers import FakePaymentProvider

User = get_user_model()


class PurchaseFlowTest(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.organizer = User.objects.create_user(email='org@example.com', username='org', password='Password123!')
        self.user = User.objects.create_user(email='buyer@example.com', username='buyer', password='Password123!')
        self.event = Event.objects.create(
            title='Festival',
            start_date=now() + timedelta(days=2),
            end_date=now() + timedelta(days=2, hours=6),
            venue='Park',
            status=EventStatus.PUBLISHED,
            organizer=self.organizer,
            hold_duration_minutes=10
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='General',
            total_capacity=100,
            sold=0,
            held=0,
            price_cents=2000,
            status=TicketTypeStatus.ACTIVE
        )

    def test_process_purchase_success(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=2)
        idem_key = f"key_{uuid.uuid4().hex}"

        order = process_purchase(
            reservation_id=reservation.id,
            idempotency_key=idem_key,
            actor_email=self.user.email
        )

        self.ticket_type.refresh_from_db()
        reservation.refresh_from_db()

        self.assertEqual(order.status, OrderStatus.CONFIRMED)
        self.assertEqual(order.quantity, 2)
        self.assertEqual(order.total_cents, 4000)
        self.assertEqual(self.ticket_type.held, 0)
        self.assertEqual(self.ticket_type.sold, 2)
        self.assertEqual(reservation.status, 'confirmed')
        self.assertEqual(Ticket.objects.filter(order=order, status=TicketStatus.ACTIVE).count(), 2)

    def test_process_purchase_expired_reservation_fails(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        
        # Force reservation to be expired
        reservation.expires_at = now() - timedelta(minutes=1)
        reservation.save(update_fields=['expires_at'])

        idem_key = f"key_{uuid.uuid4().hex}"

        with self.assertRaises(ReservationExpiredError):
            process_purchase(
                reservation_id=reservation.id,
                idempotency_key=idem_key,
                actor_email=self.user.email
            )

        # Confirm no order was created
        self.assertFalse(Order.objects.filter(idempotency_key=idem_key).exists())

    def test_reservation_response_shape(self):
        """Brief §4 Functional AC: reservations return reservation_id and expires_at."""
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        self.assertIsNotNone(reservation.id)
        self.assertIsNotNone(reservation.expires_at)

    def test_fee_and_tax_are_captured_on_order(self):
        self.ticket_type.service_fee_cents = 200
        self.ticket_type.tax_cents = 150
        self.ticket_type.save(update_fields=['service_fee_cents', 'tax_cents'])

        reservation = create_reservation(self.user, self.ticket_type.id, quantity=3)
        order = process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)

        self.assertEqual(order.total_cents, 6000)
        self.assertEqual(order.total_fees_cents, 600)
        self.assertEqual(order.total_tax_cents, 450)

    def test_decline_path_marks_order_failed_and_preserves_hold(self):
        """
        Brief §3 Payment failure journey: payment declines during confirm,
        reservation remains until expiry/cancel, order marked FAILED, hold
        left intact. FakePaymentProvider.force_success=True means this
        branch was previously never actually driven by a test - forced here
        deterministically via mocking instead of relying on the provider's
        random 10% failure rate.
        """
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        idem_key = f"key_{uuid.uuid4().hex}"

        declining_provider = FakePaymentProvider()
        declining_provider.force_success = False

        with mock.patch('orders.services.purchase_service.get_payment_provider', return_value=declining_provider), \
             mock.patch('payments.providers.random.random', return_value=0.95):
            with self.assertRaises(PaymentFailedError):
                process_purchase(reservation.id, idem_key, self.user.email)

        order = Order.objects.get(idempotency_key=idem_key)
        reservation.refresh_from_db()
        self.ticket_type.refresh_from_db()

        self.assertEqual(order.status, OrderStatus.FAILED)
        self.assertEqual(reservation.status, 'active')
        self.assertEqual(self.ticket_type.held, 1)
        self.assertEqual(self.ticket_type.sold, 0)

    def test_decline_path_via_task_does_not_retry_or_reach_dlq(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        idem_key = f"key_{uuid.uuid4().hex}"

        declining_provider = FakePaymentProvider()
        declining_provider.force_success = False

        with mock.patch('orders.services.purchase_service.get_payment_provider', return_value=declining_provider), \
             mock.patch('payments.providers.random.random', return_value=0.95):
            result = process_purchase_task.apply(
                kwargs={'reservation_id': str(reservation.id), 'idempotency_key': idem_key, 'actor_email': self.user.email}
            )

        self.assertTrue(result.successful())
        self.assertIsNone(result.get())
        self.assertEqual(FailedTask.objects.count(), 0)
        order = Order.objects.get(idempotency_key=idem_key)
        self.assertEqual(order.status, OrderStatus.FAILED)


class SalesPausedTest(TransactionTestCase):
    """
    Regression tests for the pause-sales kill switch (brief §7 Oversell
    Detected's "pause sales" immediate step). Pausing blocks BOTH new
    reservations and pending purchase confirmations.
    """
    def setUp(self):
        super().setUp()
        self.organizer = User.objects.create_user(email='org_pause@example.com', username='org_pause', password='Password123!')
        self.user = User.objects.create_user(email='buyer_pause@example.com', username='buyer_pause', password='Password123!')
        self.event = Event.objects.create(
            title='Pausable Event',
            start_date=now() + timedelta(days=2),
            end_date=now() + timedelta(days=2, hours=3),
            venue='Hall',
            status=EventStatus.PUBLISHED,
            organizer=self.organizer,
            hold_duration_minutes=10
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='GA',
            total_capacity=10,
            sold=0,
            held=0,
            price_cents=1500,
            status=TicketTypeStatus.ACTIVE
        )

    def test_reservation_blocked_when_sales_paused(self):
        self.event.sales_paused = True
        self.event.save(update_fields=['sales_paused'])

        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.post(
            '/api/reservations/',
            {'ticket_type_id': str(self.ticket_type.id), 'quantity': 1},
            format='json'
        )

        self.assertEqual(response.status_code, 409)
        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.held, 0)

    def test_reservation_allowed_after_resume(self):
        self.event.sales_paused = True
        self.event.save(update_fields=['sales_paused'])
        self.event.sales_paused = False
        self.event.save(update_fields=['sales_paused'])

        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.post(
            '/api/reservations/',
            {'ticket_type_id': str(self.ticket_type.id), 'quantity': 1},
            format='json'
        )
        self.assertEqual(response.status_code, 201)

    def test_pending_purchase_no_ops_when_sales_paused(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)

        self.event.sales_paused = True
        self.event.save(update_fields=['sales_paused'])

        idem_key = f"key_{uuid.uuid4().hex}"
        result = process_purchase_task.apply(
            kwargs={'reservation_id': str(reservation.id), 'idempotency_key': idem_key, 'actor_email': self.user.email}
        )

        self.assertTrue(result.successful())
        self.assertIsNone(result.get())
        self.assertFalse(Order.objects.filter(idempotency_key=idem_key).exists())
        self.assertEqual(FailedTask.objects.count(), 0)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, 'active')

    def test_admin_actions_toggle_sales_paused(self):
        from django.contrib.admin.sites import AdminSite
        from events.admin import EventAdmin

        admin_instance = EventAdmin(Event, AdminSite())
        qs = Event.objects.filter(id=self.event.id)

        admin_instance.pause_sales(None, qs)
        self.event.refresh_from_db()
        self.assertTrue(self.event.sales_paused)

        admin_instance.resume_sales(None, qs)
        self.event.refresh_from_db()
        self.assertFalse(self.event.sales_paused)


class PurchaseIdempotencyRaceTest(TransactionTestCase):
    """
    Regression test for finding #3: two near-simultaneous purchase requests
    carrying the SAME Idempotency-Key against the SAME reservation used to
    race - the second call would see the reservation already CONFIRMED (by
    the first call, once its lock released) and raise
    ReservationNotActiveError instead of returning the winner's Order. Now
    the second call finds the already-created Order and returns it
    untouched instead of raising.
    """
    def setUp(self):
        super().setUp()
        self.organizer = User.objects.create_user(email='org_race@example.com', username='org_race', password='Password123!')
        self.user = User.objects.create_user(email='buyer_race@example.com', username='buyer_race', password='Password123!')
        self.event = Event.objects.create(
            title='Duplicate Key Fest',
            start_date=now() + timedelta(days=2),
            end_date=now() + timedelta(days=2, hours=3),
            venue='Stadium',
            status=EventStatus.PUBLISHED,
            organizer=self.organizer,
            hold_duration_minutes=10
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='GA',
            total_capacity=10,
            sold=0,
            held=0,
            price_cents=1500,
            status=TicketTypeStatus.ACTIVE
        )

    def test_concurrent_duplicate_idempotency_key_yields_one_order(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        idem_key = f"dup_key_{uuid.uuid4().hex}"

        results = []
        exceptions = []

        def attempt():
            connection.close()
            try:
                return process_purchase(reservation.id, idem_key, self.user.email)
            except Exception as e:
                exceptions.append(e)
                return None
            finally:
                connection.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(attempt) for _ in range(5)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(exceptions), 0, f"Unexpected exceptions: {exceptions}")
        order_ids = {r.id for r in results if r is not None}
        self.assertEqual(len(order_ids), 1, f"Expected exactly one Order, got {order_ids}")
        self.assertEqual(Order.objects.filter(idempotency_key=idem_key).count(), 1)
        self.assertEqual(
            AuditLog.objects.filter(action='idempotency_collision').count(), 4,
            "Expected the 4 losing requests to be logged as collisions"
        )


class PurchaseTaskDLQClassificationTest(TransactionTestCase):
    """
    Regression test for the false-positive-DLQ half of finding #3: domain
    outcomes (an inactive/expired reservation, a declined payment) are
    expected results, not infrastructure failures, so they must not retry
    or land in the FailedTask DLQ - only genuine transient errors should.
    """
    def setUp(self):
        super().setUp()
        self.organizer = User.objects.create_user(email='org_dlq@example.com', username='org_dlq', password='Password123!')
        self.user = User.objects.create_user(email='buyer_dlq@example.com', username='buyer_dlq', password='Password123!')
        self.event = Event.objects.create(
            title='DLQ Test Event',
            start_date=now() + timedelta(days=2),
            end_date=now() + timedelta(days=2, hours=3),
            venue='Hall',
            status=EventStatus.PUBLISHED,
            organizer=self.organizer,
            hold_duration_minutes=10
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='GA',
            total_capacity=10,
            sold=0,
            held=0,
            price_cents=1500,
            status=TicketTypeStatus.ACTIVE
        )

    def test_expired_reservation_does_not_retry_or_reach_dlq(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        reservation.expires_at = now() - timedelta(minutes=1)
        reservation.save(update_fields=['expires_at'])

        result = process_purchase_task.apply(
            kwargs={
                'reservation_id': str(reservation.id),
                'idempotency_key': f"key_{uuid.uuid4().hex}",
                'actor_email': self.user.email,
            }
        )

        self.assertTrue(result.successful(), "Domain outcome should not raise/retry inside the task")
        self.assertIsNone(result.get())
        self.assertEqual(FailedTask.objects.count(), 0)

    def test_duplicate_idempotency_key_via_task_does_not_reach_dlq(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        idem_key = f"key_{uuid.uuid4().hex}"

        first = process_purchase_task.apply(
            kwargs={'reservation_id': str(reservation.id), 'idempotency_key': idem_key, 'actor_email': self.user.email}
        )
        second = process_purchase_task.apply(
            kwargs={'reservation_id': str(reservation.id), 'idempotency_key': idem_key, 'actor_email': self.user.email}
        )

        self.assertTrue(first.successful())
        self.assertTrue(second.successful())
        self.assertEqual(first.get(), second.get(), "Both calls should resolve to the same Order id")
        self.assertEqual(FailedTask.objects.count(), 0)


class FailedTaskSignalTest(TransactionTestCase):
    """
    Unit test for the DLQ write path itself (core/signals.py): confirms a
    genuine task failure signal persists a FailedTask row, independent of
    Celery's retry-timing machinery.
    """
    def test_task_failure_signal_writes_failed_task(self):
        from celery.signals import task_failure
        task_failure.send(
            sender=None,
            task_id='test-task-id-123',
            exception=RuntimeError("Simulated permanent infrastructure failure"),
            args=[],
            kwargs={'reservation_id': 'irrelevant'},
            traceback=None,
            einfo=None,
        )
        self.assertTrue(
            FailedTask.objects.filter(task_id='test-task-id-123', exception_message__icontains='Simulated permanent').exists()
        )

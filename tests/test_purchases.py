import uuid
from datetime import timedelta
from django.test import TransactionTestCase
from django.utils.timezone import now
from django.contrib.auth import get_user_model
from events.models import Event, TicketType, EventStatus, TicketTypeStatus
from orders.models import Reservation, Order, Ticket, OrderStatus, TicketStatus
from orders.services.reservation_service import create_reservation
from orders.services.purchase_service import process_purchase
from orders.exceptions import ReservationExpiredError

User = get_user_model()


class PurchaseFlowTest(TransactionTestCase):
    serialized_rollback = True

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

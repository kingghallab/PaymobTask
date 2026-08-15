import concurrent.futures
from datetime import timedelta
from django.test import TransactionTestCase
from django.utils.timezone import now
from django.contrib.auth import get_user_model
from django.db import connection
from events.models import Event, TicketType, EventStatus, TicketTypeStatus
from orders.models import Reservation, ReservationStatus, Ticket, TicketStatus
from orders.services.reservation_service import create_reservation
from orders.services.purchase_service import process_purchase
from orders.exceptions import InsufficientCapacityError

User = get_user_model()


class ConcurrencyReservationTest(TransactionTestCase):
    """
    Crown Jewel Test: Verifies that 100 concurrent threads attempting to reserve 1 ticket
    against a TicketType with capacity = 50 results in EXACTLY 50 successes and 50 failures,
    with zero oversell.
    """
    def setUp(self):
        super().setUp()
        self.organizer = User.objects.create_user(
            email='organizer@example.com',
            username='organizer',
            password='Password123!'
        )
        self.event = Event.objects.create(
            title='Concert',
            start_date=now() + timedelta(days=1),
            end_date=now() + timedelta(days=1, hours=4),
            venue='Arena',
            status=EventStatus.PUBLISHED,
            organizer=self.organizer,
            hold_duration_minutes=10
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='VIP',
            total_capacity=50,
            sold=0,
            held=0,
            price_cents=5000,
            status=TicketTypeStatus.ACTIVE
        )

        self.users = User.objects.bulk_create([
            User(
                email=f'user{i}@example.com',
                username=f'user{i}',
                password='pbkdf2_sha256$dummyhash'
            )
            for i in range(100)
        ])

    def test_concurrent_reservations_zero_oversell(self):
        successes = 0
        failures = 0
        exceptions = []

        def attempt_reservation(user):
            connection.close()
            try:
                res = create_reservation(
                    user=user,
                    ticket_type_id=self.ticket_type.id,
                    quantity=1
                )
                return True
            except InsufficientCapacityError:
                return False
            except Exception as e:
                exceptions.append(e)
                return False
            finally:
                connection.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(attempt_reservation, user) for user in self.users]
            for future in concurrent.futures.as_completed(futures):
                if future.result():
                    successes += 1
                else:
                    failures += 1

        self.ticket_type.refresh_from_db()

        # Assertions
        self.assertEqual(len(exceptions), 0, f"Unexpected exceptions encountered: {exceptions}")
        self.assertEqual(successes, 50, f"Expected 50 successes, got {successes}")
        self.assertEqual(failures, 50, f"Expected 50 failures, got {failures}")
        self.assertEqual(self.ticket_type.held, 50, f"Expected held counter to be 50, got {self.ticket_type.held}")
        self.assertEqual(self.ticket_type.computed_available, 0, f"Expected computed available to be 0, got {self.ticket_type.computed_available}")
        
        active_reservations_count = Reservation.objects.filter(
            ticket_type=self.ticket_type,
            status=ReservationStatus.ACTIVE
        ).count()
        self.assertEqual(active_reservations_count, 50)


class ConcurrencyPurchaseTest(TransactionTestCase):
    """
    Regression test for finding #1: process_purchase() previously updated
    TicketType.held/sold via a plain Python read-modify-write, with only the
    Reservation row locked - concurrent purchases against DIFFERENT
    reservations of the SAME ticket type could lose an update. Unlike the
    reservation-side crown jewel test above (which only needs "no oversell"),
    this asserts the final sold/held counters are EXACT, since a lost update
    wouldn't necessarily cause oversell but would silently corrupt the
    counters reconciliation depends on.
    """
    def setUp(self):
        super().setUp()
        self.organizer = User.objects.create_user(
            email='organizer_purchase@example.com', username='organizer_purchase', password='Password123!'
        )
        self.event = Event.objects.create(
            title='Purchase Concurrency Conference',
            start_date=now() + timedelta(days=1),
            end_date=now() + timedelta(days=1, hours=4),
            venue='Hall',
            status=EventStatus.PUBLISHED,
            organizer=self.organizer,
            hold_duration_minutes=10
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='General',
            total_capacity=50,
            sold=0,
            held=0,
            price_cents=1000,
            status=TicketTypeStatus.ACTIVE
        )

        self.num_purchases = 30
        self.reservations = []
        for i in range(self.num_purchases):
            buyer = User.objects.create_user(
                email=f'purchaser{i}@example.com', username=f'purchaser{i}', password='Password123!'
            )
            reservation = create_reservation(user=buyer, ticket_type_id=self.ticket_type.id, quantity=1)
            self.reservations.append(reservation)

    def test_concurrent_purchases_no_lost_update(self):
        results = []
        exceptions = []

        def attempt_purchase(reservation):
            connection.close()
            try:
                return process_purchase(
                    reservation_id=reservation.id,
                    idempotency_key=f"key_{reservation.id}",
                    actor_email=reservation.user.email
                )
            except Exception as e:
                exceptions.append(e)
                return None
            finally:
                connection.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.num_purchases) as executor:
            futures = [executor.submit(attempt_purchase, r) for r in self.reservations]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

        self.ticket_type.refresh_from_db()

        self.assertEqual(len(exceptions), 0, f"Unexpected exceptions encountered: {exceptions}")
        self.assertEqual(
            len([r for r in results if r is not None]), self.num_purchases,
            "Not all concurrent purchases succeeded"
        )
        self.assertLessEqual(
            self.ticket_type.sold + self.ticket_type.held, self.ticket_type.total_capacity,
            "Oversell detected"
        )
        self.assertEqual(self.ticket_type.held, 0, f"Expected held=0 after all purchases, got {self.ticket_type.held}")
        self.assertEqual(
            self.ticket_type.sold, self.num_purchases,
            f"Lost update detected: expected sold={self.num_purchases}, got {self.ticket_type.sold}"
        )
        active_tickets = Ticket.objects.filter(
            order__ticket_type=self.ticket_type, status=TicketStatus.ACTIVE
        ).count()
        self.assertEqual(active_tickets, self.num_purchases)

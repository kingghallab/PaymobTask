import concurrent.futures
from datetime import timedelta
from django.test import TransactionTestCase
from django.utils.timezone import now
from django.contrib.auth import get_user_model
from django.db import connection
from events.models import Event, TicketType, EventStatus, TicketTypeStatus
from orders.models import Reservation, ReservationStatus
from orders.services.reservation_service import create_reservation
from orders.exceptions import InsufficientCapacityError

User = get_user_model()


class ConcurrencyReservationTest(TransactionTestCase):
    """
    Crown Jewel Test: Verifies that 100 concurrent threads attempting to reserve 1 ticket
    against a TicketType with capacity = 50 results in EXACTLY 50 successes and 50 failures,
    with zero oversell.
    """
    serialized_rollback = True

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

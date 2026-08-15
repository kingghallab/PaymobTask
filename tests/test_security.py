import uuid
from datetime import timedelta
from django.test import TransactionTestCase
from django.utils.timezone import now
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from events.models import Event, TicketType, EventStatus, TicketTypeStatus
from orders.models import Order, Ticket
from orders.services.reservation_service import create_reservation
from orders.services.purchase_service import process_purchase
from core.models import AuditLog

User = get_user_model()


class RateLimitTest(TransactionTestCase):
    """Brief §4 Security & Compliance AC: 'Rate limits applied to
    reservation and purchase endpoints.' (settings.py: 'reserve': '10/min')"""
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.organizer = User.objects.create_user(email='org_sec@example.com', username='org_sec', password='Password123!')
        self.user = User.objects.create_user(email='buyer_sec@example.com', username='buyer_sec', password='Password123!')
        self.event = Event.objects.create(
            title='Rate Limit Event',
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
            total_capacity=1000,
            sold=0,
            held=0,
            price_cents=1000,
            status=TicketTypeStatus.ACTIVE
        )
        self.client.force_authenticate(user=self.user)

    def test_reservation_endpoint_enforces_rate_limit(self):
        statuses = []
        for _ in range(12):
            response = self.client.post('/api/reservations/', {
                'ticket_type_id': str(self.ticket_type.id), 'quantity': 1
            }, format='json')
            statuses.append(response.status_code)
        self.assertIn(status.HTTP_429_TOO_MANY_REQUESTS, statuses)


class IdempotencyLoggingTest(TransactionTestCase):
    """Brief §4 Security & Compliance AC: 'Idempotency keys enforced and
    logged.' Enforcement is the unique constraint (finding #3's fix);
    logging is the idempotency_collision AuditLog entry."""
    def setUp(self):
        super().setUp()
        self.organizer = User.objects.create_user(email='org_idem@example.com', username='org_idem', password='Password123!')
        self.user = User.objects.create_user(email='buyer_idem@example.com', username='buyer_idem', password='Password123!')
        self.event = Event.objects.create(
            title='Idempotency Log Event',
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
            price_cents=1000,
            status=TicketTypeStatus.ACTIVE
        )

    def test_duplicate_idempotency_key_is_logged(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        idem_key = f"key_{uuid.uuid4().hex}"
        process_purchase(reservation.id, idem_key, self.user.email)
        process_purchase(reservation.id, idem_key, self.user.email)

        log = AuditLog.objects.filter(action='idempotency_collision').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changes.get('idempotency_key'), idem_key)


class NoSensitivePaymentDataTest(TransactionTestCase):
    """Brief §4 Security & Compliance AC: 'Sensitive payment data is not
    stored; only tokens or references are recorded.' True by construction
    with FakePaymentProvider - asserted explicitly rather than left implicit."""
    def test_no_raw_card_fields_on_order_or_ticket_models(self):
        order_field_names = {f.name for f in Order._meta.get_fields()}
        ticket_field_names = {f.name for f in Ticket._meta.get_fields()}
        forbidden_substrings = ('card_number', 'cvv', 'cvc', 'pan', 'card_pan', 'expiry_date')
        for name in order_field_names | ticket_field_names:
            for forbidden in forbidden_substrings:
                self.assertNotIn(forbidden, name.lower())
        # Order only ever records a provider-issued reference, not raw data
        self.assertIn('payment_id', order_field_names)
        self.assertIn('payment_provider', order_field_names)


class EventOwnershipTest(TransactionTestCase):
    """Regression test for finding #6: EventViewSet had no object-level
    ownership check - any authenticated user could edit/delete/reassign
    another organizer's event."""
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.owner = User.objects.create_user(email='owner_evt@example.com', username='owner_evt', password='Password123!')
        self.stranger = User.objects.create_user(email='stranger_evt@example.com', username='stranger_evt', password='Password123!')
        self.event = Event.objects.create(
            title='Owned Event',
            start_date=now() + timedelta(days=3),
            end_date=now() + timedelta(days=3, hours=4),
            venue='Venue',
            status=EventStatus.PUBLISHED,
            organizer=self.owner,
            hold_duration_minutes=10
        )

    def test_non_owner_cannot_update_event(self):
        self.client.force_authenticate(user=self.stranger)
        response = self.client.patch(f'/api/events/{self.event.id}/', {'title': 'Hijacked'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.event.refresh_from_db()
        self.assertEqual(self.event.title, 'Owned Event')

    def test_non_owner_cannot_delete_event(self):
        self.client.force_authenticate(user=self.stranger)
        response = self.client.delete(f'/api/events/{self.event.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Event.objects.filter(id=self.event.id).exists())

    def test_organizer_field_is_not_writable(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(
            f'/api/events/{self.event.id}/', {'organizer': str(self.stranger.id)}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.event.refresh_from_db()
        self.assertEqual(self.event.organizer_id, self.owner.id)

    def test_owner_can_update_own_event(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(f'/api/events/{self.event.id}/', {'title': 'Updated Title'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class PasswordValidationTest(TransactionTestCase):
    """Regression test for finding #10: registration only enforced an
    8-char minimum, bypassing the 4 validators configured in
    AUTH_PASSWORD_VALIDATORS."""
    def test_common_weak_password_is_rejected(self):
        client = APIClient()
        response = client.post('/api/users/register/', {
            'email': 'weakpass@example.com',
            'username': 'weakpassuser',
            'first_name': 'Weak',
            'last_name': 'Pass',
            'password': 'password1',
            'confirm_password': 'password1',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(email='weakpass@example.com').exists())

    def test_strong_password_is_accepted(self):
        client = APIClient()
        response = client.post('/api/users/register/', {
            'email': 'strongpass@example.com',
            'username': 'strongpassuser',
            'first_name': 'Strong',
            'last_name': 'Pass',
            'password': 'Zx9!qLp42Wm',
            'confirm_password': 'Zx9!qLp42Wm',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

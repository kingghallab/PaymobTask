import uuid
from datetime import timedelta
from django.test import TransactionTestCase
from django.utils.timezone import now
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from events.models import Event, TicketType, EventStatus, TicketTypeStatus
from orders.services.reservation_service import create_reservation
from orders.services.purchase_service import process_purchase
from orders.services.refund_service import issue_refund

User = get_user_model()


class MetricsViewTest(TransactionTestCase):
    """Brief §5: Business Metrics & KPIs. Confirms the /api/metrics/
    endpoint returns all 5 categories and that live-computed values move
    correctly across a seeded reservation -> purchase -> refund cycle."""
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email='admin_metrics@example.com', username='admin_metrics', password='Password123!', is_staff=True
        )
        self.user = User.objects.create_user(email='buyer_metrics@example.com', username='buyer_metrics', password='Password123!')
        self.event = Event.objects.create(
            title='Metrics Event',
            start_date=now() + timedelta(days=3),
            end_date=now() + timedelta(days=3, hours=4),
            venue='Venue',
            status=EventStatus.PUBLISHED,
            organizer=self.admin,
            hold_duration_minutes=10
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='GA',
            total_capacity=50,
            sold=0,
            held=0,
            price_cents=5000,
            status=TicketTypeStatus.ACTIVE
        )
        self.client.force_authenticate(user=self.admin)

    def test_metrics_response_has_all_five_categories(self):
        response = self.client.get('/api/metrics/')
        self.assertEqual(response.status_code, 200)
        for category in ('sales', 'inventory', 'reliability', 'operational', 'customer_experience'):
            self.assertIn(category, response.data)

    def test_metrics_move_across_reservation_purchase_refund_cycle(self):
        baseline = self.client.get('/api/metrics/').data
        self.assertEqual(baseline['inventory']['active_reservations']['value'], 0)

        reservation = create_reservation(self.user, self.ticket_type.id, quantity=2)
        after_reserve = self.client.get('/api/metrics/').data
        self.assertEqual(after_reserve['inventory']['active_reservations']['value'], 1)

        order = process_purchase(reservation.id, f"key_{uuid.uuid4().hex}", self.user.email)
        after_purchase = self.client.get('/api/metrics/').data
        self.assertEqual(after_purchase['inventory']['active_reservations']['value'], 0)
        self.assertEqual(
            after_purchase['sales']['revenue_per_event_cents']['value'][str(self.event.id)],
            10000
        )

        issue_refund(order.id, user=self.user, reason="test", actor_email=self.user.email)
        after_refund = self.client.get('/api/metrics/').data
        self.assertEqual(after_refund['reconciliation_drift_count'], 0)

    def test_idempotency_collision_metric_increments(self):
        reservation = create_reservation(self.user, self.ticket_type.id, quantity=1)
        idem_key = f"key_{uuid.uuid4().hex}"
        process_purchase(reservation.id, idem_key, self.user.email)
        process_purchase(reservation.id, idem_key, self.user.email)  # duplicate

        metrics = self.client.get('/api/metrics/').data
        self.assertGreaterEqual(metrics['reliability']['idempotency_collisions_per_hour']['value'], 1)

    def test_non_admin_forbidden(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/metrics/')
        self.assertEqual(response.status_code, 403)

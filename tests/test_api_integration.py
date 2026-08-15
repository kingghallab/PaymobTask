import uuid
from datetime import timedelta
from django.test import TransactionTestCase
from django.utils.timezone import now
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from events.models import Event, TicketType, EventStatus, TicketTypeStatus
from orders.models import OrderStatus, TicketStatus

User = get_user_model()


class APIIntegrationTest(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.organizer = User.objects.create_user(email='org@example.com', username='org', password='Password123!')
        self.event = Event.objects.create(
            title='Startup Gala 2026',
            start_date=now() + timedelta(days=3),
            end_date=now() + timedelta(days=3, hours=5),
            venue='Grand Ballroom',
            status=EventStatus.PUBLISHED,
            organizer=self.organizer,
            hold_duration_minutes=10
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='VIP Ticket',
            total_capacity=20,
            sold=0,
            held=0,
            price_cents=12000,
            status=TicketTypeStatus.ACTIVE
        )

    def test_full_user_checkout_and_refund_flow(self):
        # 1. User Registration
        reg_data = {
            'email': 'alice@example.com',
            'username': 'alice',
            'first_name': 'Alice',
            'last_name': 'Smith',
            'password': 'StrongPassword123!',
            'confirm_password': 'StrongPassword123!'
        }
        reg_response = self.client.post('/api/users/register/', reg_data, format='json')
        self.assertEqual(reg_response.status_code, status.HTTP_201_CREATED)

        # 2. Login to obtain JWT token
        login_data = {'email': 'alice@example.com', 'password': 'StrongPassword123!'}
        login_response = self.client.post('/api/users/login/', login_data, format='json')
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        access_token = login_response.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')

        # 3. Get event catalog
        event_response = self.client.get('/api/events/')
        self.assertEqual(event_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(event_response.data), 1)

        # 4. Create Reservation (Hold 2 tickets)
        res_data = {'ticket_type_id': str(self.ticket_type.id), 'quantity': 2}
        res_response = self.client.post('/api/reservations/', res_data, format='json')
        self.assertEqual(res_response.status_code, status.HTTP_201_CREATED)
        reservation_id = res_response.data['id']

        # Verify held counter updated
        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.held, 2)

        # 5. Submit Purchase with Idempotency-Key
        idem_key = f"key_{uuid.uuid4().hex}"
        purchase_data = {'reservation_id': reservation_id}
        purchase_response = self.client.post(
            '/api/purchases/',
            purchase_data,
            format='json',
            HTTP_IDEMPOTENCY_KEY=idem_key
        )
        self.assertEqual(purchase_response.status_code, status.HTTP_202_ACCEPTED)

        # Execute purchase directly in test context
        from orders.services.purchase_service import process_purchase
        order = process_purchase(reservation_id, idem_key, 'alice@example.com')

        # 6. Verify order lookup
        order_response = self.client.get(f'/api/orders/{order.id}/')
        self.assertEqual(order_response.status_code, status.HTTP_200_OK)
        self.assertEqual(order_response.data['status'], OrderStatus.CONFIRMED)
        self.assertEqual(len(order_response.data['tickets']), 2)

        # 7. Request Refund
        refund_data = {'order_id': str(order.id), 'reason': 'Change of plans'}
        refund_response = self.client.post('/api/refunds/', refund_data, format='json')
        self.assertEqual(refund_response.status_code, status.HTTP_201_CREATED)

        # Verify inventory restored
        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.sold, 0)
        self.assertEqual(self.ticket_type.held, 0)

    def test_cancel_reservation_endpoint_releases_hold_and_serializes(self):
        login_data = {'email': 'alice@example.com', 'password': 'StrongPassword123!'}
        reg_data = {
            'email': 'alice2@example.com',
            'username': 'alice2',
            'first_name': 'Alice',
            'last_name': 'Smith',
            'password': 'StrongPassword123!',
            'confirm_password': 'StrongPassword123!'
        }
        self.client.post('/api/users/register/', reg_data, format='json')
        login_response = self.client.post('/api/users/login/', {'email': 'alice2@example.com', 'password': 'StrongPassword123!'}, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login_response.data["access"]}')

        res_response = self.client.post('/api/reservations/', {'ticket_type_id': str(self.ticket_type.id), 'quantity': 3}, format='json')
        self.assertEqual(res_response.status_code, status.HTTP_201_CREATED)
        reservation_id = res_response.data['id']

        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.held, 3)

        del_response = self.client.delete(f'/api/reservations/{reservation_id}/')
        self.assertEqual(del_response.status_code, status.HTTP_200_OK)
        self.assertEqual(del_response.data['status'], 'cancelled')
        self.assertEqual(del_response.data['ticket_type_detail']['held'], 0)
        self.assertEqual(del_response.data['ticket_type_detail']['computed_available'], 20)

        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.held, 0)

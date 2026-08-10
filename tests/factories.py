from datetime import timedelta
import factory
from django.utils.timezone import now
from django.contrib.auth import get_user_model
from events.models import Event, TicketType, EventStatus, TicketTypeStatus
from orders.models import Reservation, Order, Ticket, Refund, ReservationStatus, OrderStatus, TicketStatus, RefundStatus
from core.models import AuditLog, FailedTask

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    username = factory.Sequence(lambda n: f"user{n}")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    password = factory.PostGenerationMethodCall("set_password", "Password123!")


class EventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Event

    title = factory.Sequence(lambda n: f"Event {n}")
    description = "Test Event Description"
    start_date = factory.LazyFunction(lambda: now() + timedelta(days=7))
    end_date = factory.LazyFunction(lambda: now() + timedelta(days=7, hours=4))
    venue = "Main Auditorium"
    status = EventStatus.PUBLISHED
    organizer = factory.SubFactory(UserFactory)
    hold_duration_minutes = 10


class TicketTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TicketType

    event = factory.SubFactory(EventFactory)
    name = "Standard Ticket"
    total_capacity = 100
    sold = 0
    held = 0
    price_cents = 5000
    status = TicketTypeStatus.ACTIVE


class ReservationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Reservation

    user = factory.SubFactory(UserFactory)
    ticket_type = factory.SubFactory(TicketTypeFactory)
    quantity = 1
    status = ReservationStatus.ACTIVE
    expires_at = factory.LazyFunction(lambda: now() + timedelta(minutes=10))


class OrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Order

    user = factory.SubFactory(UserFactory)
    event = factory.LazyAttribute(lambda o: o.ticket_type.event)
    reservation = factory.SubFactory(ReservationFactory)
    ticket_type = factory.SubFactory(TicketTypeFactory)
    idempotency_key = factory.Sequence(lambda n: f"idem_key_{n}")
    quantity = 1
    unit_price_cents = 5000
    total_cents = 5000
    status = OrderStatus.CONFIRMED
    payment_id = factory.Sequence(lambda n: f"pay_{n}")
    payment_provider = "fake"
    confirmed_at = factory.LazyFunction(now)


class TicketFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Ticket

    order = factory.SubFactory(OrderFactory)
    status = TicketStatus.ACTIVE


class RefundFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Refund

    order = factory.SubFactory(OrderFactory)
    amount_cents = 5000
    reason = "Customer cancellation"
    status = RefundStatus.PROCESSED
    initiated_by = "admin@example.com"
    payment_refund_id = factory.Sequence(lambda n: f"ref_{n}")
    processed_at = factory.LazyFunction(now)


class AuditLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AuditLog

    entity_type = "ticket_type"
    entity_id = factory.Faker("uuid4")
    action = "inventory_held"
    actor = "system"
    changes = factory.Dict({"held_delta": 1})
    reason = "Test audit entry"


class FailedTaskFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FailedTask

    task_id = factory.Sequence(lambda n: f"task_{n}")
    task_name = "orders.tasks.process_purchase_task"
    args = factory.List([])
    kwargs = factory.Dict({})
    exception_message = "Simulated connection error"
    retry_count = 3

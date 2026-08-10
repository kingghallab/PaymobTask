from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils.timezone import now
from django.contrib.auth import get_user_model
from events.models import Event, TicketType, EventStatus, TicketTypeStatus

User = get_user_model()


class Command(BaseCommand):
    help = "Seeds initial test data: admin, organizers, events, and ticket types."

    def handle(self, *args, **options):
        self.stdout.write("Seeding database...")

        # Create admin superuser
        admin, created = User.objects.get_or_create(
            email='admin@paymob.com',
            defaults={
                'username': 'admin',
                'first_name': 'Paymob',
                'last_name': 'Admin',
                'is_staff': True,
                'is_superuser': True
            }
        )
        if created:
            admin.set_password('AdminPassword123!')
            admin.save()
            self.stdout.write(self.style.SUCCESS("Created admin user (admin@paymob.com / AdminPassword123!)"))

        # Create test organizer
        organizer, created = User.objects.get_or_create(
            email='organizer@paymob.com',
            defaults={
                'username': 'organizer',
                'first_name': 'Event',
                'last_name': 'Organizer',
                'is_staff': True
            }
        )
        if created:
            organizer.set_password('OrganizerPassword123!')
            organizer.save()
            self.stdout.write(self.style.SUCCESS("Created organizer user (organizer@paymob.com / OrganizerPassword123!)"))

        # Create test event
        event, created = Event.objects.get_or_create(
            title='Cairo Tech Summit 2026',
            defaults={
                'description': 'The premier technology conference in North Africa.',
                'start_date': now() + timedelta(days=14),
                'end_date': now() + timedelta(days=14, hours=8),
                'venue': 'Cairo International Convention Center',
                'status': EventStatus.PUBLISHED,
                'organizer': organizer,
                'hold_duration_minutes': 10
            }
        )

        if created:
            TicketType.objects.create(
                event=event,
                name='VIP Access',
                total_capacity=50,
                sold=0,
                held=0,
                price_cents=15000,
                status=TicketTypeStatus.ACTIVE
            )
            TicketType.objects.create(
                event=event,
                name='General Admission',
                total_capacity=500,
                sold=0,
                held=0,
                price_cents=5000,
                status=TicketTypeStatus.ACTIVE
            )
            self.stdout.write(self.style.SUCCESS(f"Created event '{event.title}' with VIP and General ticket types."))

        self.stdout.write(self.style.SUCCESS("Data seeding complete!"))

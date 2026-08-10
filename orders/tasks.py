import logging
from celery import shared_task
from django.db import transaction
from django.db.models import F
from django.utils.timezone import now
from core.models import AuditLog
from orders.models import Reservation, ReservationStatus

logger = logging.getLogger(__name__)


@shared_task
def sweep_expired_reservations():
    """
    Periodic Celery Beat task (runs every 60s).
    Finds active reservations that past their expiry date and releases held inventory.
    Uses select_for_update(skip_locked=True) to avoid blocking active user checkouts.
    """
    expired_count = 0

    with transaction.atomic():
        stale_reservations = (
            Reservation.objects
            .filter(status=ReservationStatus.ACTIVE, expires_at__lt=now())
            .select_related('ticket_type')
            .select_for_update(skip_locked=True)
        )

        for reservation in stale_reservations:
            ticket_type = reservation.ticket_type
            ticket_type.held = F('held') - reservation.quantity
            ticket_type.save(update_fields=['held', 'updated_at'])

            reservation.status = ReservationStatus.EXPIRED
            reservation.save(update_fields=['status'])

            AuditLog.record(
                entity_type='reservation',
                entity_id=reservation.id,
                action='reservation_expired',
                actor='system_sweep',
                changes={
                    'status_old': ReservationStatus.ACTIVE,
                    'status_new': ReservationStatus.EXPIRED,
                    'quantity_released': reservation.quantity
                },
                reason="Automatic 60s Celery Beat expiry sweep"
            )
            expired_count += 1

    if expired_count > 0:
        logger.info(f"Swept and expired {expired_count} stale reservations.")

    return expired_count

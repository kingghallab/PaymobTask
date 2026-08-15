import logging
from celery import shared_task
from django.db import transaction
from django.db.models import F
from django.utils.timezone import now
from core.models import AuditLog
from orders.models import Reservation, ReservationStatus
from orders.services.purchase_service import process_purchase
from orders.exceptions import ReservationNotActiveError, ReservationExpiredError, PaymentFailedError, SalesPausedError

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


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def process_purchase_task(self, reservation_id: str, idempotency_key: str, actor_email: str):
    """
    Background Celery worker task for executing asynchronous ticket purchases.
    Retries up to 3 times with 5s delay on transient failures.

    Domain outcomes (reservation already gone, expired, or a declined
    payment) are expected results, not infrastructure failures - they mark
    the purchase as not completed and return without retrying or landing in
    the FailedTask DLQ, per the brief's "DLQ captures permanently failed
    attempts" AC. Only genuine transient errors (DB deadlock, timeout, etc.)
    retry and eventually reach the DLQ.
    """
    try:
        order = process_purchase(
            reservation_id=reservation_id,
            idempotency_key=idempotency_key,
            actor_email=actor_email
        )
        logger.info(f"Successfully processed purchase task for Order {order.id}")
        return str(order.id)
    except (ReservationNotActiveError, ReservationExpiredError, PaymentFailedError, SalesPausedError) as exc:
        logger.info(f"Purchase for reservation {reservation_id} did not complete: {exc}")
        return None
    except Exception as exc:
        logger.warning(f"Error processing purchase task for reservation {reservation_id}: {exc}")
        # Re-raise to trigger retry until max_retries, then signal fires FailedTask DLQ
        raise self.retry(exc=exc)

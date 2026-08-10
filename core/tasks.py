import logging
from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task
def run_reconciliation_task():
    """
    Nightly Celery Beat task scheduled at 2:00 AM.
    Audits inventory counters across all events and logs any drift.
    """
    logger.info("Executing nightly inventory reconciliation task...")
    try:
        call_command('run_reconciliation')
        logger.info("Nightly reconciliation task finished successfully.")
    except Exception as e:
        logger.error(f"Error during nightly reconciliation task: {e}")

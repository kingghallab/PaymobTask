import logging
from celery.signals import task_failure
from core.models import FailedTask

logger = logging.getLogger(__name__)


@task_failure.connect
def handle_task_failure(sender=None, task_id=None, exception=None, args=None, kwargs=None, traceback=None, einfo=None, **kw):
    """
    Captures task failures after retries are exhausted and persists them to the FailedTask DLQ table.
    """
    try:
        task_name = getattr(sender, 'name', str(sender))
        retry_count = getattr(sender.request, 'retries', 0) if hasattr(sender, 'request') else 0

        FailedTask.objects.create(
            task_id=task_id or 'unknown',
            task_name=task_name,
            args=list(args) if args else [],
            kwargs=dict(kwargs) if kwargs else {},
            exception_message=str(exception),
            retry_count=retry_count
        )
        logger.error(f"Captured task failure for task {task_name} [{task_id}] to DLQ table.")
    except Exception as e:
        logger.error(f"Failed to record task failure signal to DLQ table: {e}")

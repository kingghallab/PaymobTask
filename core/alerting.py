import logging
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_alert(subject: str, message: str, severity: str = 'CRITICAL'):
    """
    Sends an operational alert via Django's configured email backend
    (console in dev - see settings.ALERT_RECIPIENT_EMAILS/DEFAULT_FROM_EMAIL).

    Scoped to the brief's one concrete alerting requirement (§2: "any
    oversell incident triggers immediate alerting") rather than a general
    multi-metric alert framework - see run_reconciliation's oversell check
    for the sole call site.
    """
    full_subject = f"[{severity}] {subject}"
    logger.error(f"ALERT: {full_subject} - {message}")
    send_mail(
        subject=full_subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=settings.ALERT_RECIPIENT_EMAILS,
        fail_silently=False,
    )

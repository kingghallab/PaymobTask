from datetime import timedelta
from django.http import HttpResponse
from django.utils.timezone import now
from django.db.models import Sum, Avg
from rest_framework import views, permissions, status
from rest_framework.response import Response
from orders.exporters import (
    generate_sales_csv, generate_attendee_csv,
    generate_reconciliation_csv, generate_audit_csv
)
from orders.models import Order, OrderStatus, Reservation, ReservationStatus
from events.models import TicketType
from core.models import FailedTask, AuditLog
from core.reconciliation import compute_actual_counts


class SalesReportView(views.APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        csv_data = generate_sales_csv(start_date=start_date, end_date=end_date)
        response = HttpResponse(csv_data, content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="daily_sales_report.csv"'
        return response


class AttendeeReportView(views.APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        event_id = request.query_params.get('event_id')
        csv_data = generate_attendee_csv(event_id=event_id)
        response = HttpResponse(csv_data, content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="attendees_export.csv"'
        return response


class ReconciliationReportView(views.APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        event_id = request.query_params.get('event_id')
        csv_data = generate_reconciliation_csv(event_id=event_id)
        response = HttpResponse(csv_data, content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="reconciliation_report.csv"'
        return response


class AuditExportView(views.APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        csv_data = generate_audit_csv(start_date=start_date, end_date=end_date)
        response = HttpResponse(csv_data, content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="audit_export.csv"'
        return response


class MetricsView(views.APIView):
    """
    Implements the brief's §5 Business Metrics & KPIs table (16 metrics
    across 5 categories). Entries with a null "value" and a "note" are
    documented-only for this project - no persistent store for a rolling
    measurement without new infrastructure; the note names the intended
    production measurement path (Prometheus + Grafana).
    """
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        one_hour_ago = now() - timedelta(hours=1)
        confirmed_like = [OrderStatus.CONFIRMED, OrderStatus.PARTIALLY_REFUNDED]

        # --- Sales ---
        orders_last_hour = Order.objects.filter(created_at__gte=one_hour_ago).count()
        revenue_per_event = {
            str(row['event_id']): row['total']
            for row in Order.objects.filter(status__in=confirmed_like)
                .values('event_id').annotate(total=Sum('total_cents'))
        }
        average_order_value_cents = Order.objects.filter(status__in=confirmed_like) \
            .aggregate(avg=Avg('total_cents'))['avg'] or 0

        # --- Inventory ---
        remaining_per_ticket_type = {
            str(tt.id): tt.total_capacity - tt.sold - tt.held
            for tt in TicketType.objects.all()
        }
        active_reservations = Reservation.objects.filter(
            status=ReservationStatus.ACTIVE, expires_at__gt=now()
        ).count()
        expired_reservations_last_hour = AuditLog.objects.filter(
            action='reservation_expired', created_at__gte=one_hour_ago
        ).count()

        # --- Reliability ---
        idempotency_collisions_last_hour = AuditLog.objects.filter(
            action='idempotency_collision', created_at__gte=one_hour_ago
        ).count()
        failed_tasks_last_hour = FailedTask.objects.filter(created_at__gte=one_hour_ago).count()
        task_failure_rate = round(failed_tasks_last_hour / (orders_last_hour or 1), 4)
        failed_tasks_unresolved = FailedTask.objects.filter(resolved_at__isnull=True).count()
        oversell_incidents = sum(
            1 for tt in TicketType.objects.all() if tt.sold + tt.held > tt.total_capacity
        )

        # --- Operational ---
        queue_length = self._queue_length()

        # --- Customer Experience ---
        confirmed_count = Order.objects.filter(status=OrderStatus.CONFIRMED, created_at__gte=one_hour_ago).count()
        failed_count = Order.objects.filter(status=OrderStatus.FAILED, created_at__gte=one_hour_ago).count()
        checkout_success_rate = None
        if confirmed_count + failed_count > 0:
            checkout_success_rate = round(confirmed_count / (confirmed_count + failed_count), 4)

        avg_time_to_confirm_seconds = None
        confirmed_orders = Order.objects.filter(
            status=OrderStatus.CONFIRMED, confirmed_at__isnull=False
        ).only('created_at', 'confirmed_at')
        if confirmed_orders.exists():
            deltas = [(o.confirmed_at - o.created_at).total_seconds() for o in confirmed_orders]
            avg_time_to_confirm_seconds = round(sum(deltas) / len(deltas), 2)

        return Response({
            'sales': {
                'orders_per_hour': {'value': orders_last_hour, 'alert_threshold': None},
                'revenue_per_event_cents': {'value': revenue_per_event, 'alert_threshold': None},
                'average_order_value_cents': {'value': round(average_order_value_cents, 2), 'alert_threshold': None},
            },
            'inventory': {
                'remaining_per_ticket_type': {'value': remaining_per_ticket_type, 'alert_threshold': '< 10% of capacity'},
                'active_reservations': {'value': active_reservations, 'alert_threshold': None},
                'expired_reservations_per_hour': {'value': expired_reservations_last_hour, 'alert_threshold': None},
            },
            'reliability': {
                'idempotency_collisions_per_hour': {'value': idempotency_collisions_last_hour, 'alert_threshold': '> 0'},
                'task_failure_rate': {'value': task_failure_rate, 'alert_threshold': '> 0.05'},
                'dead_letter_queue_size': {'value': failed_tasks_unresolved, 'alert_threshold': '> 0'},
                'oversell_incidents': {'value': oversell_incidents, 'alert_threshold': 'CRITICAL: any > 0'},
            },
            'operational': {
                'queue_length': {'value': queue_length, 'alert_threshold': '> 1000'},
                'average_task_processing_time_seconds': {
                    'value': None, 'alert_threshold': None,
                    'note': ('Documented only for this project - measured via structured logging '
                             '(task_prerun/task_postrun signal timing). Production path is '
                             'Prometheus + Grafana with a rolling histogram.')
                },
                'reservation_expiry_lag_seconds': {
                    'value': None, 'alert_threshold': '> 120 (2x the 60s sweep interval)',
                    'note': ('Bounded by the Celery Beat sweep interval (runs every 60s). Precise '
                             'per-reservation lag would need a processed_at timestamp on the sweep '
                             'event - not added since the bound is already known from the schedule.')
                },
            },
            'customer_experience': {
                'checkout_success_rate': {'value': checkout_success_rate, 'alert_threshold': '< 0.98'},
                'average_time_to_confirm_seconds': {'value': avg_time_to_confirm_seconds, 'alert_threshold': None},
                'refund_turnaround_time_seconds': {
                    'value': None, 'alert_threshold': None,
                    'note': ("issue_refund() is fully synchronous today (lock, provider call, and the "
                             "Refund row all happen in one request), so turnaround is sub-second by "
                             "construction and not a meaningful signal yet - would need refund requests "
                             "to become queued/async in production for this to have real variance.")
                },
            },
            'reconciliation_drift_count': self._reconciliation_drift_count(),
            'timestamp': now().isoformat(),
        }, status=status.HTTP_200_OK)

    def _queue_length(self):
        try:
            from django_redis import get_redis_connection
            return get_redis_connection('default').llen('celery')
        except Exception:
            return None

    def _reconciliation_drift_count(self):
        drift_count = 0
        for tt in TicketType.objects.all():
            actual_sold, actual_held = compute_actual_counts(tt)
            if actual_sold != tt.sold or actual_held != tt.held:
                drift_count += 1
        return drift_count

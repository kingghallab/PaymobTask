from datetime import timedelta
from django.http import HttpResponse
from django.utils.timezone import now
from django.db.models import Sum
from rest_framework import views, permissions, status
from rest_framework.response import Response
from orders.exporters import generate_sales_csv, generate_attendee_csv, generate_reconciliation_csv
from orders.models import Order, OrderStatus, Ticket, TicketStatus, Reservation, ReservationStatus
from events.models import TicketType
from core.models import FailedTask


class SalesReportView(views.APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        csv_data = generate_sales_csv()
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


class MetricsView(views.APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        one_hour_ago = now() - timedelta(hours=1)
        orders_last_hour = Order.objects.filter(created_at__gte=one_hour_ago).count()

        gross_revenue_cents = Order.objects.filter(
            status__in=[OrderStatus.CONFIRMED, OrderStatus.PARTIALLY_REFUNDED]
        ).aggregate(total=Sum('total_cents'))['total'] or 0

        failed_tasks_unresolved = FailedTask.objects.filter(resolved_at__isnull=True).count()

        # Count reconciliation drift
        drift_count = 0
        for tt in TicketType.objects.all():
            actual_sold = Ticket.objects.filter(order__ticket_type=tt, status=TicketStatus.ACTIVE).count()
            actual_held = Reservation.objects.filter(ticket_type=tt, status=ReservationStatus.ACTIVE).count()
            if actual_sold != tt.sold or actual_held != tt.held:
                drift_count += 1

        return Response({
            'orders_last_hour': orders_last_hour,
            'gross_revenue_cents': gross_revenue_cents,
            'failed_tasks_unresolved': failed_tasks_unresolved,
            'reconciliation_drift_count': drift_count,
            'timestamp': now().isoformat()
        }, status=status.HTTP_200_OK)

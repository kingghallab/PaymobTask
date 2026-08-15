from django.urls import path
from core.views import (
    SalesReportView, AttendeeReportView, ReconciliationReportView,
    AuditExportView, MetricsView
)

urlpatterns = [
    path('reports/sales/', SalesReportView.as_view(), name='report-sales'),
    path('reports/attendees/', AttendeeReportView.as_view(), name='report-attendees'),
    path('reports/reconciliation/', ReconciliationReportView.as_view(), name='report-reconciliation'),
    path('reports/audit/', AuditExportView.as_view(), name='report-audit'),
    path('metrics/', MetricsView.as_view(), name='system-metrics'),
]

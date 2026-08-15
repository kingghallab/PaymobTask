from django.contrib import admin
from django.utils.timezone import now
from core.models import AuditLog, FailedTask, FailedTaskResolution


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('entity_type', 'entity_id', 'action', 'actor', 'created_at')
    list_filter = ('entity_type', 'action')
    search_fields = ('entity_id', 'actor')


@admin.action(description="Mark selected tasks as manually resolved")
def mark_resolved(modeladmin, request, queryset):
    queryset.filter(resolved_at__isnull=True).update(
        resolution=FailedTaskResolution.MANUAL,
        resolved_by=request.user.email,
        resolved_at=now(),
    )


@admin.register(FailedTask)
class FailedTaskAdmin(admin.ModelAdmin):
    list_display = ('task_name', 'task_id', 'retry_count', 'resolution', 'resolved_at', 'created_at')
    list_filter = ('task_name', 'resolution')
    search_fields = ('task_id', 'task_name', 'exception_message')
    actions = [mark_resolved]

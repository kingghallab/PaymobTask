from django.contrib import admin
from django.utils.timezone import now
from orders.models import Order, Reservation, Ticket, Refund


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'ticket_type', 'quantity', 'status', 'expires_at', 'created_at')
    list_filter = ('status',)
    search_fields = ('user__email', 'ticket_type__name')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'event', 'quantity', 'total_cents', 'status', 'created_at')
    list_filter = ('status', 'event')
    search_fields = ('user__email', 'idempotency_key', 'payment_id')


@admin.action(description="Mark selected tickets as checked in")
def mark_checked_in(modeladmin, request, queryset):
    queryset.update(checked_in_at=now())


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'status', 'checked_in_at', 'created_at')
    list_filter = ('status',)
    actions = [mark_checked_in]


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'amount_cents', 'status', 'initiated_by', 'processed_at')
    list_filter = ('status',)
    search_fields = ('order__id', 'initiated_by')

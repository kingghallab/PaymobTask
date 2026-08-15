from django.contrib import admin
from events.models import Event, TicketType


class TicketTypeInline(admin.TabularInline):
    model = TicketType
    extra = 1
    readonly_fields = ('sold', 'held', 'computed_available')
    fields = ('name', 'total_capacity', 'sold', 'held', 'computed_available', 'price_cents', 'status')


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'organizer', 'venue', 'status', 'sales_paused', 'start_date', 'end_date')
    list_filter = ('status', 'sales_paused', 'start_date')
    search_fields = ('title', 'venue', 'organizer__email')
    inlines = [TicketTypeInline]
    actions = ['pause_sales', 'resume_sales']

    @admin.action(description="Pause sales (block new reservations and pending purchases)")
    def pause_sales(self, request, queryset):
        queryset.update(sales_paused=True)

    @admin.action(description="Resume sales")
    def resume_sales(self, request, queryset):
        queryset.update(sales_paused=False)


@admin.register(TicketType)
class TicketTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'event', 'price_cents', 'total_capacity', 'sold', 'held', 'status')
    list_filter = ('status', 'event')
    search_fields = ('name', 'event__title')
    readonly_fields = ('sold', 'held', 'computed_available')

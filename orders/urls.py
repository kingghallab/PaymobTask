from django.urls import path
from orders.views import ReservationView, ReservationDetailView

urlpatterns = [
    path('reservations/', ReservationView.as_view(), name='reservation-list'),
    path('reservations/<uuid:pk>/', ReservationDetailView.as_view(), name='reservation-detail'),
]

from django.urls import path
from orders.views import (
    ReservationView, ReservationDetailView,
    PurchaseView, OrderDetailView
)

urlpatterns = [
    path('reservations/', ReservationView.as_view(), name='reservation-list'),
    path('reservations/<uuid:pk>/', ReservationDetailView.as_view(), name='reservation-detail'),
    path('purchases/', PurchaseView.as_view(), name='purchase-create'),
    path('orders/<uuid:pk>/', OrderDetailView.as_view(), name='order-detail'),
]

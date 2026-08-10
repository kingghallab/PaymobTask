from rest_framework import status, views, permissions
from rest_framework.response import Response
from orders.serializers import ReservationSerializer, ReservationCreateSerializer
from orders.services.reservation_service import create_reservation, cancel_reservation
from orders.exceptions import InsufficientCapacityError, ReservationAccessDeniedError


class ReservationView(views.APIView):
    throttle_scope = 'reserve'
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ReservationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            reservation = create_reservation(
                user=request.user,
                ticket_type_id=serializer.validated_data['ticket_type_id'],
                quantity=serializer.validated_data['quantity']
            )
            return Response(
                ReservationSerializer(reservation).data,
                status=status.HTTP_201_CREATED
            )
        except InsufficientCapacityError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ReservationDetailView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        try:
            reservation = cancel_reservation(reservation_id=pk, user=request.user)
            return Response(
                ReservationSerializer(reservation).data,
                status=status.HTTP_200_OK
            )
        except ReservationAccessDeniedError as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)

from rest_framework import status, views, permissions
from rest_framework.response import Response
from orders.models import Order
from orders.serializers import (
    ReservationSerializer, ReservationCreateSerializer,
    PurchaseRequestSerializer, OrderSerializer,
    RefundRequestSerializer, RefundSerializer
)
from orders.services.reservation_service import create_reservation, cancel_reservation
from orders.services.purchase_service import process_purchase
from orders.services.refund_service import issue_refund
from orders.exceptions import (
    InsufficientCapacityError, ReservationAccessDeniedError,
    InvalidRefundError, PaymentRefundFailedError, SalesPausedError
)
from orders.tasks import process_purchase_task


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
        except SalesPausedError as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)


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


class PurchaseView(views.APIView):
    throttle_scope = 'purchase'
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        idem_key = request.headers.get('Idempotency-Key')
        if not idem_key:
            return Response(
                {'error': 'Idempotency-Key header is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        existing_order = Order.objects.filter(idempotency_key=idem_key).first()
        if existing_order:
            return Response(OrderSerializer(existing_order).data, status=status.HTTP_200_OK)

        serializer = PurchaseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reservation_id = serializer.validated_data['reservation_id']

        process_purchase_task.delay(
            reservation_id=str(reservation_id),
            idempotency_key=idem_key,
            actor_email=request.user.email
        )

        return Response(
            {
                'status': 'processing',
                'idempotency_key': idem_key,
                'message': 'Purchase request enqueued for asynchronous processing.'
            },
            status=status.HTTP_202_ACCEPTED
        )


class OrderDetailView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        order = Order.objects.prefetch_related('tickets', 'ticket_type', 'event').filter(id=pk, user=request.user).first()
        if not order:
            return Response({'error': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)


class RefundView(views.APIView):
    throttle_scope = 'refund'
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = RefundRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            refund = issue_refund(
                order_id=serializer.validated_data['order_id'],
                user=request.user,
                ticket_ids=serializer.validated_data.get('ticket_ids'),
                reason=serializer.validated_data.get('reason', ''),
                actor_email=request.user.email
            )
            return Response(RefundSerializer(refund).data, status=status.HTTP_201_CREATED)
        except (InvalidRefundError, PaymentRefundFailedError) as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found.'}, status=status.HTTP_403_FORBIDDEN)

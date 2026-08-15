class InsufficientCapacityError(Exception):
    """Raised when requesting more tickets than available capacity."""
    pass


class ReservationNotActiveError(Exception):
    """Raised when trying to purchase an inactive or cancelled reservation."""
    pass


class ReservationExpiredError(Exception):
    """Raised when trying to purchase an expired reservation."""
    pass


class ReservationAccessDeniedError(Exception):
    """Raised when a user tries to access/cancel a reservation owned by another user."""
    pass


class PaymentFailedError(Exception):
    """Raised when payment gateway declines or fails to capture funds."""
    pass


class SalesPausedError(Exception):
    """Raised when sales are paused for the event (ops kill switch)."""
    pass


class InvalidRefundError(Exception):
    """Raised when refund request is invalid."""
    pass


class PaymentRefundFailedError(Exception):
    """Raised when refund gateway call fails."""
    pass

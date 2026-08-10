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

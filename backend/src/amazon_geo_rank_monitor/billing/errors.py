class BillingError(Exception):
    """Base error for prepaid credit operations."""


class InsufficientCreditsError(BillingError):
    def __init__(self, *, available: int, required: int) -> None:
        self.available = available
        self.required = required
        super().__init__(
            f"insufficient credits: available={available}, required={required}"
        )

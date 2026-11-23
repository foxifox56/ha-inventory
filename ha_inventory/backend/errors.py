"""Domain and API errors shared between layers."""


class InventoryError(Exception):
    """An expected inventory operation error with an HTTP status."""

    def __init__(
        self, message: str, status_code: int = 400, field: str | None = None,
        *, code: str | None = None, details: dict | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field = field
        self.code = code
        self.details = details or {}

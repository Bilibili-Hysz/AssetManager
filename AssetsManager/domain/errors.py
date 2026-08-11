"""Domain errors — explicit error types for business logic failures.

Domain errors replace generic Exception raises with type-safe error
hierarchy that can be caught and handled appropriately by each layer.
"""
from __future__ import annotations


class DomainError(Exception):
    """Base class for all domain errors."""


class PathEscapeError(DomainError):
    """A path resolved outside the allowed root directory."""

    def __init__(self, path: str = "", root: str = ""):
        self.path = path
        self.root = root
        super().__init__(f"Path '{path}' escapes root '{root}'")


class MissingPathError(DomainError):
    """A required path does not exist."""

    def __init__(self, path: str = ""):
        self.path = path
        super().__init__(f"Path not found: {path}")


class DuplicateError(DomainError):
    """An operation would create a duplicate entry."""

    def __init__(self, entity: str = "", key: str = ""):
        self.entity = entity
        self.key = key
        super().__init__(f"Duplicate {entity}: {key}")


class NotFoundError(DomainError):
    """A requested entity was not found."""

    def __init__(self, entity: str = "", key: str = ""):
        self.entity = entity
        self.key = key
        super().__init__(f"{entity} not found: {key}")


class ValidationError(DomainError):
    """Input validation failed."""

    def __init__(self, field: str = "", message: str = ""):
        self.field = field
        self.message = message
        super().__init__(f"Validation error on '{field}': {message}")


class OperationNotPermitted(DomainError):
    """An operation is not permitted."""

    def __init__(self, message: str = ""):
        super().__init__(message or "Operation not permitted")


class StoreNotAcceptingOrdersError(OperationNotPermitted):
    """Raised when an order creation races with a seller store pause."""

    def __init__(self):
        super().__init__("This store is not accepting new orders")


class VersionConflictError(OperationNotPermitted):
    code = "cart_version_conflict"
    def __init__(self):
        super().__init__("Cart version conflict")


class WishlistLimitError(OperationNotPermitted):
    code = "wishlist_limit"

    def __init__(self, limit: int = 500):
        self.limit = int(limit)
        super().__init__(f"Wishlist cannot contain more than {self.limit} items")


class PriceChangedError(OperationNotPermitted):
    code = "price_changed"
    def __init__(self, item_id: object):
        self.item_id = item_id
        super().__init__(f"Price changed for shop item {item_id}")

class DeliveryPreparationError(DomainError):
    """The server could not prepare a digital delivery response."""

    code = "delivery_prepare_failed"

    def __init__(self):
        super().__init__("Failed to create delivery")

class IdempotencyKeyReusedError(OperationNotPermitted):
    """The same lifecycle key was replayed with different request inputs."""

    code = "idempotency_key_reused"

    def __init__(self):
        super().__init__("Idempotency key was already used with different checkout inputs")

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
        super().__init__(f"Validation error on '{field}': {message}")


class OperationNotPermitted(DomainError):
    """An operation is not permitted."""

    def __init__(self, message: str = ""):
        super().__init__(message or "Operation not permitted")

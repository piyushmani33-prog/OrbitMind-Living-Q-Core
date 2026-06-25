"""Domain error types with safe, client-facing messages (SR-17).

``OrbitMindError`` subclasses carry a stable ``code`` and a *safe* message that may
be shown to clients. Internal detail is logged, never returned.
"""

from __future__ import annotations


class OrbitMindError(Exception):
    """Base class for application errors with a safe client message."""

    code: str = "orbitmind_error"
    http_status: int = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationError(OrbitMindError):
    """Request failed domain validation."""

    code = "validation_error"
    http_status = 422


class IdempotencyConflictError(OrbitMindError):
    """An owner-scoped idempotency key was reused for different input."""

    code = "idempotency_conflict"
    http_status = 409


class NotFoundError(OrbitMindError):
    """A requested resource does not exist."""

    code = "not_found"
    http_status = 404


class PropagationError(OrbitMindError):
    """Orbital propagation failed for one or more samples."""

    code = "propagation_error"
    http_status = 422


class StorageError(OrbitMindError):
    """Persistence operation failed."""

    code = "storage_error"
    http_status = 500


class SecurityError(OrbitMindError):
    """A safety/security guard rejected an operation (e.g., path traversal)."""

    code = "security_error"
    http_status = 400


class EvidenceNotAuthenticatedError(OrbitMindError):
    """Persisted evidence exists but is not authenticated (no signer / unaccepted / failed
    receipt). It is diagnostic only and must not be served as ordinary evidence (fifth review,
    Medium #2)."""

    code = "evidence_not_authenticated"
    http_status = 409

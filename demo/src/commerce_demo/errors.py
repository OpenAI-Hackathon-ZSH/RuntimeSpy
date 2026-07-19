"""Domain errors converted to consistent API responses."""

from __future__ import annotations

from typing import Any


class DomainError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "domain_error",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class NotFoundError(DomainError):
    def __init__(self, resource: str, identifier: str):
        super().__init__(
            f"{resource} {identifier!r} was not found",
            code="not_found",
            status_code=404,
            details={"resource": resource, "identifier": identifier},
        )


class ConflictError(DomainError):
    def __init__(self, message: str, *, code: str = "conflict"):
        super().__init__(message, code=code, status_code=409)


class PermissionDeniedError(DomainError):
    def __init__(self, message: str = "permission denied"):
        super().__init__(message, code="permission_denied", status_code=403)


class ValidationError(DomainError):
    def __init__(self, message: str, *, field: str | None = None):
        details = {"field": field} if field else {}
        super().__init__(
            message,
            code="validation_error",
            status_code=422,
            details=details,
        )


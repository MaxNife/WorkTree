"""Application errors. Route handlers translate these into a stable JSON error shape."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected, client-visible failures."""

    status_code = 400
    code = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class DuplicateRun(Conflict):
    code = "duplicate_run"


class UnprocessableEntity(AppError):
    status_code = 422
    code = "unprocessable"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class ConfigurationError(AppError):
    status_code = 500
    code = "configuration_error"


class ActivityNotFound(NotFound):
    code = "activity_not_found"

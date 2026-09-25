"""Domain errors. Services raise these; one handler maps them to HTTP responses."""
from __future__ import annotations


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFound(AppError):
    status, code = 404, "not_found"


class Unauthorized(AppError):
    status, code = 401, "unauthorized"


class Forbidden(AppError):
    status, code = 403, "forbidden"


class Conflict(AppError):
    status, code = 409, "conflict"


class Invalid(AppError):
    status, code = 422, "invalid"


class RateLimited(AppError):
    status, code = 429, "rate_limited"


class Unavailable(AppError):
    status, code = 503, "unavailable"

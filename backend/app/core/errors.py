"""Application error types, shared envelope, and FastAPI exception handlers.

Every error response goes through `_envelope` so clients can rely on a
single shape:

    {
      "error":   {"code": "...", "message": "...", "details": null | {...}},
      "request_id": "..." | null
    }
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger("errors")


class AppError(Exception):
    """Base class for domain errors that should surface to clients."""

    code: str = "app_error"
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        # Optional response headers (e.g. Retry-After on 429).
        self.headers = headers


class BadRequestError(AppError):
    code = "bad_request"
    status_code = status.HTTP_400_BAD_REQUEST


class NotFoundError(AppError):
    code = "not_found"
    status_code = status.HTTP_404_NOT_FOUND


class ConflictError(AppError):
    code = "conflict"
    status_code = status.HTTP_409_CONFLICT


class UnauthorizedError(AppError):
    code = "unauthorized"
    status_code = status.HTTP_401_UNAUTHORIZED


class ForbiddenError(AppError):
    code = "forbidden"
    status_code = status.HTTP_403_FORBIDDEN


class RateLimitedError(AppError):
    code = "rate_limited"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            "Rate limit exceeded. Please slow down and retry shortly.",
            details={"retry_after": retry_after},
            headers={"Retry-After": str(max(0, int(retry_after)))},
        )


class WeakPasswordError(BadRequestError):
    """A password that fails the policy. ``details.issues`` lists the reasons."""

    code = "weak_password"

    def __init__(self, issues: list[str]) -> None:
        super().__init__(
            "Password does not meet the security policy.",
            details={"issues": issues},
        )


class AccountLockedError(AppError):
    """Account temporarily locked after repeated failed logins."""

    code = "account_locked"
    status_code = status.HTTP_423_LOCKED

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            "Account temporarily locked due to repeated failed sign-in attempts. "
            "Try again later or contact an administrator.",
            details={"retry_after": retry_after},
            headers={"Retry-After": str(max(0, int(retry_after)))},
        )


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _envelope(
    *,
    code: str,
    message: str,
    request_id: str | None,
    details: Any | None = None,
) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "details": details},
        "request_id": request_id,
    }


async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            request_id=_request_id(request),
        ),
        headers=getattr(exc, "headers", None),
    )


async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    message = detail if isinstance(detail, str) else "HTTP error."
    details = None if isinstance(detail, str) else detail
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(
            code=f"http_{exc.status_code}",
            message=message,
            details=details,
            request_id=_request_id(request),
        ),
    )


async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_envelope(
            code="validation_error",
            message="Request validation failed.",
            details={"errors": exc.errors()},
            request_id=_request_id(request),
        ),
    )


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled.exception",
        path=request.url.path,
        method=request.method,
        request_id=_request_id(request),
        error=str(exc),
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_envelope(
            code="internal_error",
            message="Internal server error.",
            request_id=_request_id(request),
        ),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _handle_unexpected)

from __future__ import annotations

import hmac
import logging
import os
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Awaitable, Callable
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api.services.api_keys import authenticate_api_key


logger = logging.getLogger(__name__)


def _truthy(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        if limit <= 0:
            return True, 0
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._requests[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(events[0] + window_seconds - now))
                return False, retry_after
            events.append(now)
            return True, 0

    def clear(self) -> None:
        with self._lock:
            self._requests.clear()


rate_limiter = SlidingWindowLimiter()


def _error_payload(request: Request, code: str, message: str, status_code: int) -> dict:
    request_id = getattr(request.state, "request_id", "unknown")
    return {
        "error": {"code": code, "message": message, "request_id": request_id},
        "detail": message,
        "status_code": status_code,
    }


def _status_code_for_error(status_code: int) -> str:
    return {
        400: "INVALID_REQUEST",
        401: "UNAUTHORIZED",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "INVALID_REQUEST",
        429: "RATE_LIMIT_EXCEEDED",
        500: "INTERNAL_SERVER_ERROR",
        502: "UPSTREAM_ERROR",
        503: "SERVICE_UNAVAILABLE",
        504: "UPSTREAM_TIMEOUT",
    }.get(status_code, "API_ERROR")


async def api_http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    code = _status_code_for_error(exc.status_code)
    message = str(detail)
    if isinstance(detail, dict):
        code = str(detail.get("code") or code)
        message = str(detail.get("message") or "Request failed")
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(request, code, message, exc.status_code),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=_error_payload(request, "INVALID_REQUEST", "Request parameters are invalid.", 400),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled API error request_id=%s", getattr(request.state, "request_id", "unknown"))
    return JSONResponse(
        status_code=500,
        content=_error_payload(request, "INTERNAL_SERVER_ERROR", "The server could not complete the request.", 500),
    )


async def api_middleware(request: Request, call_next: Callable[[Request], Awaitable]) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID", "").strip() or str(uuid4())
    request.state.request_id = request_id
    path_is_api = request.url.path.startswith("/api/v1")
    if path_is_api:
        is_key_management = request.url.path == "/api/v1/api-keys" or request.url.path.startswith("/api/v1/api-keys/")
        configured_key = os.getenv("RAILETA_PUBLIC_API_KEY", "").strip()
        if _truthy("RAILETA_REQUIRE_API_KEY", False) and not is_key_management:
            supplied_key = request.headers.get("X-API-Key", "")
            valid_static_key = bool(configured_key and supplied_key and hmac.compare_digest(supplied_key, configured_key))
            valid_stored_key = False
            if supplied_key and not valid_static_key:
                valid_stored_key = authenticate_api_key(supplied_key)
            if not valid_static_key and not valid_stored_key:
                return JSONResponse(
                    status_code=401,
                    content=_error_payload(request, "INVALID_API_KEY", "A valid X-API-Key header is required.", 401),
                )

        try:
            limit = max(0, int(os.getenv("RAILETA_RATE_LIMIT_PER_MINUTE", "60")))
        except ValueError:
            limit = 60
        client_host = request.client.host if request.client else "unknown"
        limiter_key = request.headers.get("X-API-Key", "") or client_host
        allowed, retry_after = rate_limiter.allow(limiter_key, limit)
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content=_error_payload(request, "RATE_LIMIT_EXCEEDED", "API rate limit exceeded.", 429),
            )
            response.headers["Retry-After"] = str(retry_after)
            response.headers["X-Request-ID"] = request_id
            return response

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

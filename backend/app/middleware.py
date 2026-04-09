"""
KozAlma AI — Middleware.

Provides:
  - Request ID injection (X-Request-ID header)
  - Structured JSON logging
  - Request/response logging with timing
  - Rate limiting per endpoint group
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar
from typing import Callable, Dict, Optional, Tuple

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# ── Context var for request_id — available anywhere in the request ──
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


# ═══════════════════════════════════════════════════════════════════════
# Request ID Middleware
# ═══════════════════════════════════════════════════════════════════════

class RequestIdMiddleware(BaseHTTPMiddleware):
    """Inject a unique request ID into every request and response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request_id_var.set(rid)
        request.state.request_id = rid

        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


# ═══════════════════════════════════════════════════════════════════════
# Request Logging Middleware
# ═══════════════════════════════════════════════════════════════════════

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, status, and duration."""

    SKIP_PATHS = {"/health", "/readiness", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if path in self.SKIP_PATHS:
            return await call_next(request)

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000

        rid = getattr(request.state, "request_id", "")
        logger.info(
            "HTTP %s %s → %d (%.1fms) [rid=%s]",
            request.method,
            path,
            response.status_code,
            duration_ms,
            rid,
        )
        return response


# ═══════════════════════════════════════════════════════════════════════
# JSON Log Formatter
# ═══════════════════════════════════════════════════════════════════════

class JsonLogFormatter(logging.Formatter):
    """Structured JSON log formatter for production log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(""),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════
# In-Memory Rate Limiter
# ═══════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Simple in-memory sliding-window rate limiter.

    Suitable for single-instance deployments.
    For multi-instance, use Redis-backed rate limiting.

    Usage:
        limiter = RateLimiter()
        if not limiter.allow("scan", client_ip, max_requests=30, window_seconds=60):
            raise HTTPException(429, "Too Many Requests")
    """

    def __init__(self) -> None:
        # key → list of timestamps
        self._requests: Dict[str, list[float]] = defaultdict(list)
        self._last_cleanup = time.monotonic()

    def allow(
        self,
        group: str,
        client_id: str,
        max_requests: int,
        window_seconds: int,
    ) -> bool:
        """Check if the request is within rate limits.

        Args:
            group: Rate limit group (e.g. "scan", "tts", "otp")
            client_id: Client identifier (IP address typically)
            max_requests: Max requests per window
            window_seconds: Window size in seconds

        Returns:
            True if allowed, False if rate limited.
        """
        now = time.monotonic()
        key = f"{group}:{client_id}"

        # Periodic cleanup (every 60s)
        if now - self._last_cleanup > 60:
            self._cleanup(now)

        # Remove expired timestamps
        cutoff = now - window_seconds
        timestamps = self._requests[key]
        self._requests[key] = [t for t in timestamps if t > cutoff]

        if len(self._requests[key]) >= max_requests:
            return False

        self._requests[key].append(now)
        return True

    def _cleanup(self, now: float) -> None:
        """Remove stale entries to prevent memory growth."""
        self._last_cleanup = now
        stale_keys = [
            k for k, v in self._requests.items()
            if not v or (now - max(v)) > 300  # 5 min stale
        ]
        for k in stale_keys:
            del self._requests[k]


# Global rate limiter instance
rate_limiter = RateLimiter()


def parse_rate_limit(spec: str) -> Tuple[int, int]:
    """Parse rate limit spec like '30/minute' → (30, 60).

    Supported units: second, minute, hour.
    """
    try:
        parts = spec.strip().split("/")
        count = int(parts[0])
        unit = parts[1].lower().strip()
        seconds_map = {"second": 1, "minute": 60, "hour": 3600}
        window = seconds_map.get(unit, 60)
        return count, window
    except (IndexError, ValueError):
        return 30, 60  # safe default


def get_client_ip(request: Request) -> str:
    """Extract client IP, preferring X-Forwarded-For behind proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def check_rate_limit(
    request: Request,
    group: str,
    spec: str,
    enabled: bool = True,
) -> Optional[JSONResponse]:
    """Check rate limit and return 429 response if exceeded, None if OK."""
    if not enabled:
        return None
    max_req, window = parse_rate_limit(spec)
    client_ip = get_client_ip(request)
    if not rate_limiter.allow(group, client_ip, max_req, window):
        logger.warning(
            "Rate limit exceeded: group=%s client=%s limit=%s",
            group, client_ip, spec,
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Too many requests. Please try again later."},
        )
    return None

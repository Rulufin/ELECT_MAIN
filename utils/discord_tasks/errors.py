# utils/discord/errors.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Tuple

import discord

logger = logging.getLogger(__name__)


# =========================
# Rate limit normalized types
# =========================

@dataclass(frozen=True)
class RateLimitInfo:
    """Normalized rate-limit info to be used across layers (queue, notifier, etc.)."""
    retry_after: float          # seconds
    is_global: bool
    route: str                  # e.g. "PATCH /channels/{channel_id}"
    bucket_key: Optional[str] = None


class DiscordRateLimited(Exception):
    """A normalized exception representing Discord API rate limiting."""
    def __init__(self, info: RateLimitInfo, original: Exception | None = None):
        super().__init__(f"Rate limited: {info.route} retry_after={info.retry_after}")
        self.info = info
        self.original = original

class DiscordQueueAborted(Exception):
    """Queue intentionally aborted (e.g. too long rate limit)."""
    def __init__(self, message: str, *, retry_after: float, route: str | None = None):
        super().__init__(message)
        self.retry_after = float(retry_after)
        self.route = route

def to_rate_limit_info(
    exc: Exception,
    *,
    route: str,
    bucket_key: str | None = None,
) -> RateLimitInfo | None:
    """
    Convert discord.py exceptions into RateLimitInfo (best-effort).
    Note:
      - route should be supplied by the caller (bucket / request wrapper), not inferred.
    """
    if not is_rate_limited(exc):
        return None
    retry_after, is_global = extract_retry_after(exc)
    return RateLimitInfo(
        retry_after=float(retry_after),
        is_global=bool(is_global),
        route=route,
        bucket_key=bucket_key,
    )


def raise_rate_limited(
    exc: Exception,
    *,
    route: str,
    bucket_key: str | None = None,
) -> None:
    """
    If `exc` is rate limited, raise DiscordRateLimited(info, exc).
    Otherwise do nothing.

    Usage:
        try:
            ...
        except Exception as e:
            raise_rate_limited(e, route="PATCH /channels/{id}", bucket_key=...)
            raise
    """
    info = to_rate_limit_info(exc, route=route, bucket_key=bucket_key)
    if info is not None:
        raise DiscordRateLimited(info, exc)


# =========================
# Existing helpers (discord.py compatibility)
# =========================

def is_rate_limited(exc: Exception) -> bool:
    # discord.py may raise discord.RateLimited, or discord.HTTPException with status 429
    if isinstance(exc, getattr(discord, "RateLimited", ())):
        return True
    if isinstance(exc, discord.HTTPException):
        return getattr(exc, "status", None) == 429
    return False


def extract_retry_after(exc: Exception) -> Tuple[float, bool]:
    """
    Returns: (retry_after_seconds, is_global)
    Best-effort across discord.py versions.
    """
    # discord.RateLimited
    RateLimited = getattr(discord, "RateLimited", None)
    if RateLimited and isinstance(exc, RateLimited):
        retry_after = float(getattr(exc, "retry_after", 1.0))
        is_global = bool(getattr(exc, "global", False))
        return retry_after, is_global

    # discord.HTTPException with 429
    if isinstance(exc, discord.HTTPException) and getattr(exc, "status", None) == 429:
        # Newer discord.py often sets .retry_after
        ra = getattr(exc, "retry_after", None)
        if ra is not None:
            return float(ra), bool(getattr(exc, "global", False))

        # Fallback: inspect response headers if available
        resp = getattr(exc, "response", None)
        if resp is not None:
            try:
                headers = getattr(resp, "headers", {}) or {}
                # Discord commonly uses Retry-After or X-RateLimit-Reset-After
                if "Retry-After" in headers:
                    return float(headers["Retry-After"]), False
                if "X-RateLimit-Reset-After" in headers:
                    return float(headers["X-RateLimit-Reset-After"]), False
            except Exception:
                pass

        # Fallback: default small wait
        return 1.0, False

    return 0.0, False


def is_transient_http_error(exc: Exception) -> bool:
    """
    Retryable transient errors (best-effort):
    - HTTP 5xx
    - Gateway issues
    - timeouts
    """
    if isinstance(exc, (discord.GatewayNotFound, discord.ConnectionClosed)):
        return True

    if isinstance(exc, discord.HTTPException):
        st = getattr(exc, "status", 0) or 0
        return 500 <= int(st) <= 599

    # if user wraps aiohttp elsewhere and bubbles it up, you can extend here
    return False


def is_forbidden(exc: Exception) -> bool:
    return isinstance(exc, discord.Forbidden)


def is_not_found(exc: Exception) -> bool:
    return isinstance(exc, discord.NotFound)


def format_http_exception(exc: Exception) -> str:
    if isinstance(exc, discord.HTTPException):
        return f"HTTPException(status={exc.status}, text={getattr(exc, 'text', '')})"
    return f"{type(exc).__name__}: {exc}"

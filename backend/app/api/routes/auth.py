"""
KozAlma AI — Auth API Routes.

Passwordless OTP authentication:
  POST /auth/request-code  — send 6-digit OTP
  POST /auth/verify-code   — verify OTP, issue JWT tokens
  POST /auth/refresh       — refresh tokens
  GET  /auth/me            — current user profile
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth.jwt_utils import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    verify_token,
)
from app.config import get_settings
from app.db.session import get_session_factory
from app.middleware import check_rate_limit
from app.models.user import get_or_create_user
from app.services import notify_service
from app.services import otp_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ────────────────────────────────────────────────────────────────────
# Request / Response schemas
# ────────────────────────────────────────────────────────────────────

class RequestCodeBody(BaseModel):
    channel: str = Field(..., pattern="^(email|phone|whatsapp)$")
    identifier: str = Field(..., min_length=3, max_length=320)


class RequestCodeResponse(BaseModel):
    ok: bool = True
    cooldown_seconds: int = 60


class VerifyCodeBody(BaseModel):
    channel: str = Field(..., pattern="^(email|phone|whatsapp)$")
    identifier: str = Field(..., min_length=3, max_length=320)
    code: str = Field(..., min_length=6, max_length=6)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshBody(BaseModel):
    refresh_token: str


class UserProfile(BaseModel):
    id: str
    channel: str
    identifier: str
    role: str


# ────────────────────────────────────────────────────────────────────
# Helper: get Redis or 503
# ────────────────────────────────────────────────────────────────────

def _get_redis(request: Request):
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service unavailable (Redis not connected)",
        )
    return redis


# ────────────────────────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────────────────────────

@router.post("/request-code", response_model=RequestCodeResponse)
async def request_code(body: RequestCodeBody, request: Request):
    """Send a 6-digit OTP to the user's email or phone.

    Always returns ok=true to prevent user enumeration.
    """
    # ── Rate limiting ──
    settings = get_settings()
    rl_response = check_rate_limit(
        request, "otp", settings.rate_limit_otp, settings.rate_limit_enabled,
    )
    if rl_response:
        return rl_response

    redis = _get_redis(request)
    identifier = body.identifier.strip()

    # Check cooldown
    on_cd, remaining = await otp_service.is_on_cooldown(redis, body.channel, identifier)
    if on_cd:
        return RequestCodeResponse(ok=True, cooldown_seconds=remaining)

    # Check lock
    if await otp_service.is_locked(redis, body.channel, identifier):
        # Still return ok=true (no enumeration), but with max cooldown
        return RequestCodeResponse(ok=True, cooldown_seconds=settings.otp_lock_seconds)

    # Generate OTP
    code = await otp_service.generate_otp(redis, body.channel, identifier)
    if code is None:
        return RequestCodeResponse(ok=True, cooldown_seconds=settings.otp_cooldown_seconds)

    # Send via configured channel
    await notify_service.send_otp(body.channel, identifier, code)

    return RequestCodeResponse(ok=True, cooldown_seconds=settings.otp_cooldown_seconds)


@router.post("/verify-code", response_model=TokenResponse)
async def verify_code(body: VerifyCodeBody, request: Request):
    """Verify OTP and issue JWT tokens.

    Auto-creates user on first successful verification (login == signup).
    """
    # ── Rate limiting ──
    settings = get_settings()
    rl_response = check_rate_limit(
        request, "auth", settings.rate_limit_auth, settings.rate_limit_enabled,
    )
    if rl_response:
        return rl_response

    redis = _get_redis(request)
    identifier = body.identifier.strip()

    # Verify OTP
    ok = await otp_service.verify_otp(redis, body.channel, identifier, body.code)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired code",
        )

    # Parse admin identifiers from env
    admin_ids = [
        s.strip()
        for s in (settings.admin_identifiers or "").split(",")
        if s.strip()
    ]

    # Find or create user
    session_factory = get_session_factory()
    async with session_factory() as session:
        user = await get_or_create_user(
            session,
            channel=body.channel,
            identifier=identifier,
            admin_identifiers=admin_ids,
        )
        user_id = user.id
        user_role = user.role

    # Issue tokens
    access = create_access_token(user_id, user_role)
    refresh = create_refresh_token(user_id)

    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(body: RefreshBody):
    """Exchange a valid refresh token for new access + refresh tokens."""
    payload = verify_token(body.refresh_token, expected_type="refresh")
    user_id = payload["sub"]

    # Look up current role from DB
    session_factory = get_session_factory()
    async with session_factory() as session:
        from sqlalchemy import select
        from app.models.user import User
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        role = user.role

    access = create_access_token(user_id, role)
    refresh = create_refresh_token(user_id)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.get("/me", response_model=UserProfile)
async def me(current_user=Depends(get_current_user)):
    """Return minimal profile of the authenticated user."""
    user_id = current_user["sub"]

    session_factory = get_session_factory()
    async with session_factory() as session:
        from sqlalchemy import select
        from app.models.user import User
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return UserProfile(
            id=user.id,
            channel=user.channel,
            identifier=user.identifier,
            role=user.role,
        )

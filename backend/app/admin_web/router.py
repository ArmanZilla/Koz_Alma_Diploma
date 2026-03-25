"""
KozAlma AI — Admin Web Panel.

Cookie-session-based admin for viewing/downloading unknown image batches.
Login + Password authentication.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer

from app.admin_web.auth import verify_credentials
from app.auth.jwt_utils import require_admin
from app.config import get_settings

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

router = APIRouter(prefix="/admin", tags=["admin"])

SESSION_COOKIE = "koz_admin_session"
MAX_AGE = 3600 * 8  # 8 hours


def _get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().admin_session_secret)


def _is_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    try:
        _get_serializer().loads(token, max_age=MAX_AGE)
        return True
    except Exception:
        return False


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """Render login form."""
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
    """Validate login + password and set session cookie."""
    if not verify_credentials(username, password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Неверный логин или пароль"},
            status_code=401,
        )

    token = _get_serializer().dumps({"admin": True, "user": username})
    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(SESSION_COOKIE, token, max_age=MAX_AGE, httponly=True)
    return response


@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Admin dashboard — list unknown image batches."""
    if not _is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=303)

    mgr = request.app.state.unknown_manager
    groups: List[Dict[str, Any]] = []
    error_msg = ""

    if mgr is None:
        error_msg = "S3 storage not configured"
    else:
        try:
            groups = mgr.list_groups()
        except Exception as exc:
            logger.error("Admin dashboard — failed to list groups: %s", exc)
            error_msg = "Ошибка подключения к хранилищу"

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "groups": groups, "error_msg": error_msg},
    )


# ────────────────────────────────────────────────────────────────────────
# Batch detail page
# ────────────────────────────────────────────────────────────────────────

@router.get("/batch/{batch_id}", response_class=HTMLResponse)
async def batch_detail(batch_id: str, request: Request) -> HTMLResponse:
    """Show detailed view of a single batch — thumbnails, status, meta."""
    if not _is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=303)

    mgr = request.app.state.unknown_manager
    if mgr is None:
        return templates.TemplateResponse(
            "batch_detail.html",
            {
                "request": request,
                "batch": None,
                "images": [],
                "error_msg": "S3 storage not configured",
            },
        )

    error_msg = ""
    batch: Dict[str, Any] = {}
    images: List[Dict[str, Any]] = []

    try:
        # Get batch metadata
        state = mgr._read_batch_state(batch_id) or {}
        batch = {
            "batch_id": batch_id,
            "status": state.get("status", "unknown"),
            "count": state.get("count", 0),
            "created_at": state.get("created_at", ""),
            "labeled_at": state.get("labeled_at", ""),
            "model_version": state.get("model_version", ""),
            "label_count": state.get("label_count", 0),
        }

        # Get image list
        images = mgr.list_images(batch_id)

    except Exception as exc:
        logger.error("batch_detail failed for '%s': %s", batch_id, exc)
        error_msg = "Ошибка загрузки данных батча"

    return templates.TemplateResponse(
        "batch_detail.html",
        {
            "request": request,
            "batch": batch,
            "images": images,
            "error_msg": error_msg,
        },
    )


# ────────────────────────────────────────────────────────────────────────
# Downloads
# ────────────────────────────────────────────────────────────────────────

@router.get("/download/{group_id:path}")
async def download_group(group_id: str, request: Request) -> Response:
    """Download a batch as ZIP (images/ + meta/ + labels/ + pred/)."""
    if not _is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=303)

    mgr = request.app.state.unknown_manager
    if mgr is None:
        return Response(content=b"S3 not configured", status_code=500)

    try:
        zip_bytes = mgr.download_group_zip(group_id)
    except Exception as exc:
        logger.error("Admin download failed for '%s': %s", group_id, exc)
        return Response(content=b"Storage error", status_code=500)

    if zip_bytes is None:
        return Response(content=b"Not found", status_code=404)

    filename = f"{group_id.replace('/', '_')}.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/download-all")
async def download_all(request: Request) -> Response:
    """Download ALL unknown images + metadata as a single ZIP."""
    if not _is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=303)

    mgr = request.app.state.unknown_manager
    if mgr is None:
        return Response(content=b"S3 not configured", status_code=500)

    try:
        zip_bytes = mgr.download_all_zip()
    except Exception as exc:
        logger.error("Admin download-all failed: %s", exc)
        return Response(content=b"Storage error", status_code=500)

    if zip_bytes is None:
        return Response(content=b"No unknown images found", status_code=404)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"unknown_all_{today}.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/image/{key:path}")
async def image_proxy(key: str, request: Request) -> Response:
    """Proxy an image from S3 for admin preview (bucket is private)."""
    if not _is_authenticated(request):
        return Response(content=b"Unauthorized", status_code=401)

    mgr = request.app.state.unknown_manager
    if mgr is None:
        return Response(content=b"S3 not configured", status_code=500)

    data = mgr.get_image_bytes(key)
    if data is None:
        return Response(content=b"Not found", status_code=404)

    # Determine media type from extension
    media_type = "image/jpeg"
    if key.endswith(".png"):
        media_type = "image/png"
    elif key.endswith(".json"):
        media_type = "application/json"

    return Response(content=data, media_type=media_type)


@router.get("/logout")
async def logout(request: Request) -> Response:
    """Clear session and redirect to login."""
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


# ────────────────────────────────────────────────────────────────────────
# Admin API (JWT-protected, for future mobile/programmatic use)
# ────────────────────────────────────────────────────────────────────────

@router.get("/api/groups")
async def api_groups(
    request: Request,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> JSONResponse:
    """List groups via JWT Bearer (admin role required)."""
    mgr = request.app.state.unknown_manager
    if mgr is None:
        return JSONResponse({"groups": [], "error": "Storage not configured"})
    try:
        groups = mgr.list_groups()
    except Exception as exc:
        logger.error("Admin API groups failed: %s", exc)
        return JSONResponse({"groups": [], "error": "Storage error"})
    return JSONResponse({"groups": groups, "error": None})

"""
KozAlma AI — /unknown Endpoints.

List unknown image groups, view images, download as ZIP.
Upload endpoints require JWT authentication.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response

from app.api.schemas import UnknownGroupItem, UnknownImageItem
from app.auth.jwt_utils import get_current_user, get_optional_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/unknown", tags=["unknown"])


@router.get("/groups", response_model=List[UnknownGroupItem])
async def list_groups(request: Request) -> List[UnknownGroupItem]:
    """List all unknown image groups (public for admin dashboard)."""
    mgr = request.app.state.unknown_manager
    if mgr is None:
        return []
    try:
        groups = mgr.list_groups()
    except Exception as exc:
        logger.error("list_groups failed: %s", exc)
        return []
    return [
        UnknownGroupItem(
            group_id=g["group_id"],
            date=g["date"],
            image_count=g["image_count"],
        )
        for g in groups
    ]


@router.get("/groups/{group_id:path}/images", response_model=List[UnknownImageItem])
async def list_images(group_id: str, request: Request) -> List[UnknownImageItem]:
    """List images in a specific group."""
    mgr = request.app.state.unknown_manager
    if mgr is None:
        return []
    try:
        images = mgr.list_images(group_id)
    except Exception as exc:
        logger.error("list_images failed for '%s': %s", group_id, exc)
        return []
    return [UnknownImageItem(**img) for img in images]


@router.get("/groups/{group_id:path}/download")
async def download_group(group_id: str, request: Request) -> Response:
    """Download all images in a group as a ZIP file."""
    mgr = request.app.state.unknown_manager
    if mgr is None:
        return Response(content=b"", status_code=404)

    try:
        zip_bytes = mgr.download_group_zip(group_id)
    except Exception as exc:
        logger.error("download_group failed for '%s': %s", group_id, exc)
        return Response(content=b"Storage error", status_code=500)

    if zip_bytes is None:
        return Response(content=b"Group not found or empty", status_code=404)

    filename = f"{group_id.replace('/', '_')}.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/upload")
async def upload_unknown(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    user: Dict[str, Any] = Depends(get_current_user),
) -> dict:
    """Upload an unknown image.  Requires JWT authentication.

    Stores user_id from token in the image metadata.
    """
    mgr = request.app.state.unknown_manager
    if mgr is None:
        return {"error": "Storage not configured", "key": None}

    image_bytes = await file.read()
    metadata = {
        "user_id": user.get("sub", "unknown"),
        "uploaded_via": "api",
    }

    try:
        key = mgr.store_image(image_bytes, metadata=metadata, session_id=session_id, background_tasks=background_tasks)
    except Exception as exc:
        logger.error("upload_unknown failed: %s", exc)
        return {"error": "Upload failed", "key": None}

    return {"key": key, "error": None}

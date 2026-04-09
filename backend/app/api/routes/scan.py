"""
KozAlma AI — /scan Endpoint.

Accepts an image, runs YOLO+MiDaS pipeline, generates TTS audio,
and optionally stores unknown images in S3.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from PIL import Image

from app.api.schemas import DetectionItem, ScanResponse
from app.config import get_settings
from app.middleware import check_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scan"])


@router.post("/scan", response_model=ScanResponse)
async def scan_image(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Image to scan"),
    lang: str = Form("ru", description="Language: ru or kz"),
    tts_speed: float = Form(1.0, description="TTS speed multiplier"),
    send_unknown: bool = Form(False, description="Store unknown images to S3"),
    session_id: Optional[str] = Form(None, description="Session ID for grouping unknowns"),
) -> ScanResponse:
    """
    Main scan endpoint:
    1. Decode image
    2. Run YOLOv8 + MiDaS pipeline (with bilingual text builder)
    3. Generate TTS audio from localized text
    4. Optionally store unknowns in S3
    """
    # ── Rate limiting ──
    settings = get_settings()
    rl_response = check_rate_limit(
        request, "scan", settings.rate_limit_scan, settings.rate_limit_enabled,
    )
    if rl_response:
        return rl_response

    logger.info(
        "Scan request: lang=%s, tts_speed=%.1f, send_unknown=%s",
        lang, tts_speed, send_unknown,
    )

    # Access shared resources from app state
    pipeline = request.app.state.pipeline
    tts_engine = request.app.state.tts_engine
    unknown_mgr = request.app.state.unknown_manager

    if pipeline is None:
        return ScanResponse(
            lang=lang, detections=[], text="ML pipeline not available",
            audio_base64=None, is_unknown=False,
        )

    # 1. Decode image
    image_bytes = await file.read()
    image = Image.open(BytesIO(image_bytes)).convert("RGB")

    # 2. Run pipeline
    result = pipeline.run(image, lang=lang)

    # 3. Build detection items from pipeline dicts
    detection_items = [
        DetectionItem(
            class_id=d["class_id"],
            class_name=d["class_name"],
            class_name_localized=d["class_name_localized"],
            confidence=round(d["confidence"], 3),
            bbox=d["bbox"],
            position=d["position"],
            distance_m=d["distance_m"],
        )
        for d in result.detection_dicts
    ]

    # 4. TTS — speak the localized text
    audio_b64 = tts_engine.synthesize(result.text, lang=lang, speed=tts_speed)

    # 5. Store unknown if needed
    if result.has_unknown and send_unknown and unknown_mgr is not None:
        try:
            meta = {
                "lang": lang,
                "detections": len(result.detections),
                "has_unknown": True,
            }
            unknown_mgr.store_image(
                image_bytes,
                metadata=meta,
                session_id=session_id,
                background_tasks=background_tasks,
            )
        except Exception as exc:
            logger.error("Failed to store unknown image: %s", exc)

    return ScanResponse(
        lang=lang,
        detections=detection_items,
        text=result.text,
        audio_base64=audio_b64,
        is_unknown=result.has_unknown,
    )

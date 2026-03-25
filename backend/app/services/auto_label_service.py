"""
KozAlma AI — Auto-Label Service.

Downloads images from a completed batch, runs YOLO inference,
and saves YOLO .txt labels + prediction JSON files back to S3.

This service is called asynchronously via BackgroundTasks so
the upload request is never blocked.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.storage.s3_client import S3Client

if TYPE_CHECKING:
    from app.ml.detector import YOLODetector

logger = logging.getLogger(__name__)

_PREFIX = "unknown/"

# Fallback version string when the detector doesn't expose one
_DEFAULT_MODEL_VERSION = "yolov8-custom"


class AutoLabelService:
    """Run YOLO auto-labeling on a full batch of unknown images."""

    def __init__(
        self,
        s3: S3Client,
        detector: YOLODetector,
        min_conf: float = 0.15,
    ) -> None:
        self.s3 = s3
        self.detector = detector
        self.min_conf = min_conf
        logger.info(
            "AutoLabelService initialized (min_conf=%.2f)", self.min_conf
        )

    # ═══════════════════════════════════════════════════════════════════
    #  PUBLIC: label_batch
    # ═══════════════════════════════════════════════════════════════════

    def label_batch(self, batch_id: str) -> int:
        """Auto-label every image in a batch.

        For each image:
          1. Download from S3
          2. Run YOLO detector
          3. Filter detections below min_conf
          4. Save labels/<id>.txt   (YOLO normalized format)
          5. Save pred/<id>.json    (rich prediction data)

        After all images are processed, updates _batch_meta.json
        with status="labeled".

        Returns the number of images successfully labeled.
        """
        from PIL import Image as PILImage

        logger.info("Auto-labeling batch %s (min_conf=%.2f)", batch_id, self.min_conf)

        images_prefix = f"{_PREFIX}{batch_id}/images/"
        objs = self.s3.list_objects(prefix=images_prefix)
        jpg_objs = [o for o in objs if o.get("Key", "").endswith(".jpg")]

        if not jpg_objs:
            logger.warning("No images found in %s — skipping", batch_id)
            return 0

        labeled = 0
        for obj in jpg_objs:
            key = obj["Key"]
            try:
                labeled += self._label_single_image(batch_id, key, PILImage)
            except Exception as exc:
                logger.error("Auto-label failed for %s: %s", key, exc)
                continue

        # Update _batch_meta.json → status = "labeled"
        self._update_batch_meta(batch_id, labeled)

        logger.info(
            "Batch %s auto-labeled: %d/%d images", batch_id, labeled, len(jpg_objs)
        )
        return labeled

    # ═══════════════════════════════════════════════════════════════════
    #  PRIVATE: label a single image
    # ═══════════════════════════════════════════════════════════════════

    def _label_single_image(
        self,
        batch_id: str,
        image_key: str,
        pil_module: Any,
    ) -> int:
        """Download one image, run detector, save label + pred.

        Returns 1 on success, 0 if the image is inaccessible.
        """
        img_data = self.s3.get_object(image_key)
        if img_data is None:
            logger.warning("Skipping inaccessible image: %s", image_key)
            return 0

        image = pil_module.open(BytesIO(img_data)).convert("RGB")
        detections = self.detector.detect(image)
        img_w, img_h = image.size

        # Filter by minimum confidence
        filtered = [d for d in detections if d.confidence >= self.min_conf]

        # Extract file stem: unknown/batch_001/images/abc123.jpg → abc123
        file_stem = image_key.split("/")[-1].replace(".jpg", "")

        # ── Save YOLO label (.txt) ──────────────────────────────────
        yolo_lines: List[str] = []
        for det in filtered:
            x1, y1, x2, y2 = det.bbox
            # Pixel coords → YOLO normalized [cx, cy, w, h]
            cx = ((x1 + x2) / 2) / img_w
            cy = ((y1 + y2) / 2) / img_h
            w = (x2 - x1) / img_w
            h = (y2 - y1) / img_h
            yolo_lines.append(
                f"{det.class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"
            )

        label_key = f"{_PREFIX}{batch_id}/labels/{file_stem}.txt"
        label_content = "\n".join(yolo_lines) if yolo_lines else ""
        self.s3.upload_bytes(
            label_key, label_content.encode("utf-8"), content_type="text/plain"
        )

        # ── Save prediction JSON ────────────────────────────────────
        pred_data: List[Dict[str, Any]] = []
        for det in filtered:
            pred_data.append({
                "class_id": det.class_id,
                "class_name": det.class_name,
                "confidence": round(det.confidence, 4),
                "bbox": {
                    "x1": round(det.bbox[0], 2),
                    "y1": round(det.bbox[1], 2),
                    "x2": round(det.bbox[2], 2),
                    "y2": round(det.bbox[3], 2),
                },
            })

        pred_key = f"{_PREFIX}{batch_id}/pred/{file_stem}.json"
        self.s3.upload_json(
            pred_key, json.dumps(pred_data, ensure_ascii=False, indent=2)
        )

        return 1

    # ═══════════════════════════════════════════════════════════════════
    #  PRIVATE: update _batch_meta.json
    # ═══════════════════════════════════════════════════════════════════

    def _update_batch_meta(self, batch_id: str, label_count: int) -> None:
        """Set batch status to 'labeled' and record model version."""
        meta_key = f"{_PREFIX}{batch_id}/_batch_meta.json"
        data = self.s3.get_object(meta_key)

        meta: Dict[str, Any] = {}
        if data:
            try:
                meta = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        # Determine model version from detector
        model_version = getattr(self.detector, "_weights_path", _DEFAULT_MODEL_VERSION)
        model_version = str(model_version)

        meta["status"] = "labeled"
        meta["labeled_at"] = datetime.now(timezone.utc).isoformat()
        meta["model_version"] = model_version
        meta["label_count"] = label_count

        self.s3.upload_json(meta_key, json.dumps(meta, ensure_ascii=False, indent=2))
        logger.info("Updated _batch_meta.json for %s → status=labeled", batch_id)

    # ═══════════════════════════════════════════════════════════════════
    #  PUBLIC: get model version string
    # ═══════════════════════════════════════════════════════════════════

    @property
    def model_version(self) -> str:
        """Return a human-readable model version string."""
        return str(getattr(self.detector, "_weights_path", _DEFAULT_MODEL_VERSION))

"""
KozAlma AI — Unknown Image Manager (Batch System).

Stores low-confidence / undetected images in numbered batches:
  unknown/batch_001/images/
  unknown/batch_001/meta/
  unknown/batch_001/labels/
  unknown/batch_001/pred/
  unknown/batch_001/_batch_meta.json

Batch lifecycle:
  1. Images arrive → stored in the ACTIVE batch (latest open batch)
  2. When batch reaches MAX_BATCH_SIZE (25) images:
     a. Mark batch as "pending"
     b. Trigger auto_label_batch() via BackgroundTasks (non-blocking)
     c. AutoLabelService runs YOLO → generates labels/ + pred/
     d. _batch_meta.json updated to status="labeled"
     e. Next image goes to a NEW batch

Concurrency safety:
  Batch state is stored in S3 as unknown/batch_XXX/_batch_meta.json.
  A global marker file `unknown/_active_batch.json` is the authoritative
  source for the currently active batch.
  This is sufficient for single-instance deployments (our case).

All S3 calls are wrapped so the admin dashboard never crashes, even if
the bucket is empty or S3 is misconfigured.
"""

from __future__ import annotations

import json
import logging
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.storage.s3_client import S3Client

if TYPE_CHECKING:
    from app.services.auto_label_service import AutoLabelService

logger = logging.getLogger(__name__)

_PREFIX = "unknown/"
MAX_BATCH_SIZE = 25
_ACTIVE_BATCH_KEY = f"{_PREFIX}_active_batch.json"


class UnknownManager:
    """Manage unknown/low-confidence images in S3 using a batch system."""

    def __init__(self, s3: S3Client) -> None:
        self.s3 = s3
        self._auto_label_service: Optional[AutoLabelService] = None

    def set_auto_label_service(self, service: AutoLabelService) -> None:
        """Inject the auto-label service (called during app startup)."""
        self._auto_label_service = service
        logger.info("AutoLabelService injected into UnknownManager")

    # ════════════════════════════════════════════════════════════════════
    #  BATCH STATE  (_batch_meta.json)
    # ════════════════════════════════════════════════════════════════════

    def _read_active_batch_meta(self) -> Optional[Dict[str, Any]]:
        """Read the global active-batch marker from S3."""
        data = self.s3.get_object(_ACTIVE_BATCH_KEY)
        if data is None:
            return None
        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Corrupt _active_batch.json — will create new batch")
            return None

    def _write_active_batch_meta(self, meta: Dict[str, Any]) -> bool:
        """Write the global active-batch marker to S3."""
        return self.s3.upload_json(
            _ACTIVE_BATCH_KEY,
            json.dumps(meta, ensure_ascii=False),
        )

    def _read_batch_state(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Read _batch_meta.json for a specific batch."""
        key = f"{_PREFIX}{batch_id}/_batch_meta.json"
        data = self.s3.get_object(key)
        if data is None:
            return None
        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _write_batch_state(self, batch_id: str, state: Dict[str, Any]) -> bool:
        """Write _batch_meta.json for a specific batch."""
        key = f"{_PREFIX}{batch_id}/_batch_meta.json"
        return self.s3.upload_json(key, json.dumps(state, ensure_ascii=False, indent=2))

    def _next_batch_number(self) -> int:
        """Determine the next batch number by scanning existing batch_ prefixes."""
        prefixes = self.s3.list_prefixes(prefix=_PREFIX)
        max_num = 0
        for p in prefixes:
            # p looks like "unknown/batch_003/"
            name = p.rstrip("/").split("/")[-1]
            if name.startswith("batch_"):
                try:
                    num = int(name.replace("batch_", ""))
                    max_num = max(max_num, num)
                except ValueError:
                    pass
        return max_num + 1

    def _create_batch(self, batch_num: int) -> str:
        """Create a new empty batch and write its _batch_meta.json + active marker."""
        batch_id = f"batch_{batch_num:03d}"
        now = datetime.now(timezone.utc).isoformat()

        # Determine model_version from auto-label service if available
        model_version = ""
        if self._auto_label_service:
            model_version = self._auto_label_service.model_version

        state: Dict[str, Any] = {
            "batch_id": batch_id,
            "count": 0,
            "status": "open",
            "model_version": model_version,
            "created_at": now,
            "labeled_at": None,
        }
        self._write_batch_state(batch_id, state)

        active_meta = {"batch_id": batch_id, "batch_num": batch_num}
        self._write_active_batch_meta(active_meta)

        logger.info("Created new batch: %s", batch_id)
        return batch_id

    # ════════════════════════════════════════════════════════════════════
    #  PUBLIC: get_active_batch
    # ════════════════════════════════════════════════════════════════════

    def get_active_batch(self) -> str:
        """Return the ID of the current active (open) batch.

        If no active batch exists, creates batch_001.
        If the active batch is already full/closed, creates the next one.
        """
        meta = self._read_active_batch_meta()

        if meta is None:
            # No active batch marker → first time setup
            return self._create_batch(1)

        batch_id = meta.get("batch_id", "")
        state = self._read_batch_state(batch_id)

        if state is None or state.get("status") != "open":
            # Marker points to a closed/missing batch → create next
            next_num = self._next_batch_number()
            return self._create_batch(next_num)

        if state.get("count", 0) >= MAX_BATCH_SIZE:
            # Batch is full but wasn't closed yet (edge case)
            next_num = meta.get("batch_num", 0) + 1
            return self._create_batch(next_num)

        return batch_id

    # ════════════════════════════════════════════════════════════════════
    #  PUBLIC: store_image (BATCH VERSION)
    # ════════════════════════════════════════════════════════════════════

    def store_image(
        self,
        image_bytes: bytes,
        metadata: Dict[str, Any],
        session_id: Optional[str] = None,
        background_tasks: Any = None,
    ) -> Optional[str]:
        """Store an unknown image in the active batch.

        Layout:
          images/<uuid>.jpg
          meta/<uuid>_meta.json

        When the batch reaches MAX_BATCH_SIZE:
          1. Batch marked "pending"
          2. Auto-label triggered via BackgroundTasks (non-blocking)
          3. Next call will create a new batch

        Returns the S3 key of the stored image, or None on failure.
        """
        try:
            import uuid

            batch_id = self.get_active_batch()
            now = datetime.now(timezone.utc)
            img_id = uuid.uuid4().hex[:12]

            # Save image to images/ subfolder
            img_key = f"{_PREFIX}{batch_id}/images/{img_id}.jpg"

            # Save meta to meta/ subfolder (NOT images/)
            meta_key = f"{_PREFIX}{batch_id}/meta/{img_id}_meta.json"

            metadata.update({
                "timestamp": now.isoformat(),
                "image_key": img_key,
                "batch_id": batch_id,
                "session_id": session_id,
            })

            ok_img = self.s3.upload_bytes(img_key, image_bytes, content_type="image/jpeg")
            ok_meta = self.s3.upload_json(meta_key, json.dumps(metadata, ensure_ascii=False))

            if not ok_img or not ok_meta:
                logger.error("store_image: partial upload failure (img=%s, meta=%s)", ok_img, ok_meta)
                return None

            # Update batch image count in _batch_meta.json
            state = self._read_batch_state(batch_id) or {}
            count = state.get("count", 0) + 1
            state["count"] = count
            self._write_batch_state(batch_id, state)

            logger.info("Stored image %s in %s (%d/%d)", img_key, batch_id, count, MAX_BATCH_SIZE)

            # Auto-close if full
            if count >= MAX_BATCH_SIZE:
                logger.info("Batch %s reached %d images — closing", batch_id, MAX_BATCH_SIZE)
                self.close_batch(batch_id, background_tasks=background_tasks)

            return img_key
        except Exception as exc:
            logger.error("store_image unexpected error: %s", exc)
            return None

    # ════════════════════════════════════════════════════════════════════
    #  PUBLIC: close_batch
    # ════════════════════════════════════════════════════════════════════

    def close_batch(
        self,
        batch_id: str,
        background_tasks: Any = None,
    ) -> bool:
        """Close a batch and trigger auto-labeling.

        1. Set status to "pending" in _batch_meta.json
        2. Trigger auto_label_batch via BackgroundTasks (non-blocking)
        3. Create next batch for future uploads

        The AutoLabelService will:
          - Run YOLO on each image → labels/ + pred/
          - Update _batch_meta.json to status="labeled"
        """
        try:
            logger.info("Closing batch %s — marking as pending", batch_id)

            # Step 1: Mark as pending
            state = self._read_batch_state(batch_id) or {}
            state["status"] = "pending"
            self._write_batch_state(batch_id, state)

            # Step 2: Trigger auto-label in background
            if self._auto_label_service is not None:
                if background_tasks is not None:
                    # Use FastAPI BackgroundTasks — does NOT block the request
                    background_tasks.add_task(
                        self._run_auto_label_background, batch_id
                    )
                    logger.info("Auto-label for %s queued as background task", batch_id)
                else:
                    # No BackgroundTasks available — run synchronously
                    logger.info("No BackgroundTasks — running auto-label synchronously for %s", batch_id)
                    self._run_auto_label_background(batch_id)
            else:
                logger.warning("No AutoLabelService — skipping auto-label for %s", batch_id)

            # Step 3: Advance active batch marker
            next_num = self._next_batch_number()
            self._create_batch(next_num)

            logger.info("Batch %s closed, next batch created", batch_id)
            return True

        except Exception as exc:
            logger.error("close_batch failed for %s: %s", batch_id, exc)
            return False

    def _run_auto_label_background(self, batch_id: str) -> None:
        """Background task: run auto-labeling and generate ZIP.

        Errors are logged but never raised — the upload request
        must not fail because of labeling issues.
        """
        try:
            if self._auto_label_service is None:
                return

            label_count = self._auto_label_service.label_batch(batch_id)
            logger.info("Auto-labeled %d images in %s", label_count, batch_id)

            # Generate and upload batch ZIP after labeling
            zip_bytes = self._generate_batch_zip(batch_id)
            if zip_bytes:
                zip_key = f"{_PREFIX}{batch_id}.zip"
                ok = self.s3.upload_bytes(zip_key, zip_bytes, content_type="application/zip")
                if ok:
                    logger.info("Uploaded %s (%d bytes)", zip_key, len(zip_bytes))
                else:
                    logger.error("Failed to upload batch ZIP for %s", batch_id)

        except Exception as exc:
            logger.error("Background auto-label failed for %s: %s", batch_id, exc)

    # ════════════════════════════════════════════════════════════════════
    #  PRIVATE: Batch ZIP generation
    # ════════════════════════════════════════════════════════════════════

    def _generate_batch_zip(self, batch_id: str) -> Optional[bytes]:
        """Create a ZIP archive containing images/, meta/, labels/, pred/.

        Structure inside ZIP:
            batch_XXX/images/abc123.jpg
            batch_XXX/meta/abc123_meta.json
            batch_XXX/labels/abc123.txt
            batch_XXX/pred/abc123.json
        """
        try:
            batch_prefix = f"{_PREFIX}{batch_id}/"
            objs = self.s3.list_objects(prefix=batch_prefix)

            # Include images/, meta/, labels/, pred/ (not _batch_meta.json or _active_batch)
            relevant = [
                o for o in objs
                if any(
                    o.get("Key", "").startswith(f"{batch_prefix}{sub}/")
                    for sub in ("images", "meta", "labels", "pred")
                )
            ]

            if not relevant:
                return None

            buf = BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for obj in relevant:
                    key = obj["Key"]
                    data = self.s3.get_object(key)
                    if data:
                        # Path inside ZIP: batch_XXX/images/file.jpg
                        arc_name = key.replace(_PREFIX, "")
                        zf.writestr(arc_name, data)

            buf.seek(0)
            return buf.read()
        except Exception as exc:
            logger.error("_generate_batch_zip failed for %s: %s", batch_id, exc)
            return None

    # ════════════════════════════════════════════════════════════════════
    #  LIST BATCHES  (admin dashboard — MUST NEVER CRASH)
    # ════════════════════════════════════════════════════════════════════

    def list_groups(self) -> List[Dict[str, Any]]:
        """List all batches with their state.

        Returns an empty list if the bucket is empty or S3 is unreachable,
        so the admin panel always renders.
        """
        try:
            prefixes = self.s3.list_prefixes(prefix=_PREFIX)
            if not prefixes:
                return []

            groups: List[Dict[str, Any]] = []
            for batch_prefix in prefixes:
                batch_name = batch_prefix.rstrip("/").split("/")[-1]
                if not batch_name.startswith("batch_"):
                    continue

                # Read _batch_meta.json
                state = self._read_batch_state(batch_name) or {}
                status = state.get("status", "unknown")
                count = state.get("count", 0)

                # Find first JPG for preview
                images_prefix = f"{batch_prefix}images/"
                objs = self.s3.list_objects(prefix=images_prefix)
                jpg_keys = [o["Key"] for o in objs if o.get("Key", "").endswith(".jpg")]

                groups.append({
                    "group_id": batch_name,
                    "prefix": batch_prefix,
                    "image_count": count if count else len(jpg_keys),
                    "date": state.get("created_at", "")[:10],
                    "created_at": state.get("created_at", ""),
                    "labeled_at": state.get("labeled_at", ""),
                    "model_version": state.get("model_version", ""),
                    "preview_key": jpg_keys[0] if jpg_keys else None,
                    "status": status,
                    "label_count": state.get("label_count", 0),
                })

            # Sort: open batches first, then by batch number
            groups.sort(key=lambda g: (g["status"] != "open", g["group_id"]))
            return groups

        except Exception as exc:
            logger.error("list_groups failed: %s", exc)
            return []

    # ════════════════════════════════════════════════════════════════════
    #  LIST IMAGES IN A BATCH
    # ════════════════════════════════════════════════════════════════════

    def list_images(self, group_id: str) -> List[Dict[str, Any]]:
        """List images in a specific batch.  Returns [] on error."""
        try:
            prefix = f"{_PREFIX}{group_id}/images/"
            objs = self.s3.list_objects(prefix=prefix)
            images: List[Dict[str, Any]] = []
            for obj in objs:
                key = obj.get("Key", "")
                if key.endswith(".jpg"):
                    images.append({
                        "key": key,
                        "name": key.split("/")[-1],
                        "size": obj.get("Size", 0),
                    })
            return images
        except Exception as exc:
            logger.error("list_images failed for batch '%s': %s", group_id, exc)
            return []

    # ════════════════════════════════════════════════════════════════════
    #  DOWNLOAD BATCH ZIP
    # ════════════════════════════════════════════════════════════════════

    def download_group_zip(self, group_id: str) -> Optional[bytes]:
        """Download a batch as ZIP.

        First tries the pre-built ZIP (labeled batches have this),
        then falls back to generating one on-the-fly.
        """
        try:
            # Try pre-built ZIP first (labeled batches have this)
            zip_key = f"{_PREFIX}{group_id}.zip"
            data = self.s3.get_object(zip_key)
            if data:
                return data

            # Fall back to on-the-fly generation
            return self._generate_batch_zip(group_id)
        except Exception as exc:
            logger.error("download_group_zip failed for '%s': %s", group_id, exc)
            return None

    # ════════════════════════════════════════════════════════════════════
    #  DOWNLOAD ALL BATCHES AS ONE ZIP
    # ════════════════════════════════════════════════════════════════════

    def download_all_zip(self) -> Optional[bytes]:
        """Download every batch's images+meta+labels+pred as a single ZIP.

        Preserves S3 path structure inside the archive.
        Returns None if bucket is empty or on error.
        """
        try:
            objs = self.s3.list_objects(prefix=_PREFIX)
            if not objs:
                return None

            buf = BytesIO()
            skipped = 0
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for obj in objs:
                    key = obj.get("Key", "")
                    if not key:
                        continue
                    # Skip marker files and batch meta files
                    if key.endswith("_active_batch.json") or key.endswith("_batch_meta.json"):
                        continue
                    data = self.s3.get_object(key)
                    if data:
                        zf.writestr(key, data)
                    else:
                        skipped += 1
                        logger.warning("download_all_zip: skipped inaccessible '%s'", key)

            if skipped:
                logger.warning("download_all_zip: %d object(s) skipped", skipped)

            buf.seek(0)
            return buf.read()
        except Exception as exc:
            logger.error("download_all_zip failed: %s", exc)
            return None

    # ════════════════════════════════════════════════════════════════════
    #  GET SINGLE IMAGE (admin preview proxy)
    # ════════════════════════════════════════════════════════════════════

    def get_image_bytes(self, key: str) -> Optional[bytes]:
        """Fetch a single object from S3 by key.  Returns None if not found."""
        try:
            return self.s3.get_object(key)
        except Exception as exc:
            logger.error("get_image_bytes failed for '%s': %s", key, exc)
            return None

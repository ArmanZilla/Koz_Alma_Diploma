"""
KozAlma AI — Scan Pipeline.

Orchestrates: YOLOv8 detect → MiDaS depth → text_builder → TTS.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from PIL import Image

from app.ml.detector import Detection, YOLODetector
from app.ml.depth import DepthEstimator
from app.logic.text_builder import build_detection_text, localize_class_name

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Aggregated scan result."""

    detections: List[Detection]
    detection_dicts: List[Dict[str, Any]] = field(default_factory=list)
    text: str = ""
    has_unknown: bool = False


class ScanPipeline:
    """Full inference pipeline for a single image scan."""

    def __init__(
        self,
        detector: YOLODetector,
        depth_estimator: DepthEstimator,
        unknown_threshold: float = 0.30,
    ) -> None:
        self.detector = detector
        self.depth = depth_estimator
        self.unknown_threshold = unknown_threshold

    def run(self, image: Image.Image, lang: str = "ru") -> ScanResult:
        """Execute full pipeline and return ScanResult."""
        logger.info("Pipeline run: lang=%s", lang)

        # 1. Detect objects
        detections = self.detector.detect(image)

        # 2. Check for unknowns
        has_unknown = len(detections) == 0 or any(
            d.confidence < self.unknown_threshold for d in detections
        )

        if not detections:
            from app.logic.text_builder import _get_phrases
            text = _get_phrases(lang)["no_objects"]
            return ScanResult(detections=[], text=text, has_unknown=True)

        # 3. Depth estimation
        logger.info(
            "Depth estimator available: %s", self.depth.is_available,
        )
        depth_map = self.depth.estimate_depth_map(image)
        logger.info(
            "Depth map: %s",
            "None" if depth_map is None else f"shape={depth_map.shape}",
        )

        # 4. Build per-detection dicts with distances
        det_dicts: list[Dict[str, Any]] = []
        for det in detections:
            dist: Optional[float] = None
            if depth_map is not None:
                dist = self.depth.estimate_distance(depth_map, det.bbox)
                if dist < 0:
                    dist = None

            det_dicts.append({
                "class_id": det.class_id,
                "class_name": det.class_name,
                "class_name_localized": localize_class_name(det.class_name, lang),
                "confidence": det.confidence,
                "bbox": det.bbox,
                "position": det.position,
                "distance_m": dist,
            })

        # 5. Build localized text via text_builder
        text = build_detection_text(det_dicts, lang=lang)

        logger.info(
            "Pipeline result: %d detections, unknown=%s, lang=%s",
            len(detections), has_unknown, lang,
        )
        return ScanResult(
            detections=detections,
            detection_dicts=det_dicts,
            text=text,
            has_unknown=has_unknown,
        )

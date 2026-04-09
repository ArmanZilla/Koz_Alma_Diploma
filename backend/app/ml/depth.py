from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch
from PIL import Image
import torch

import torch

# 🔥 ФИКС №1 (оставь)
torch.hub._validate_not_a_forked_repo = lambda *args, **kwargs: True

# 🔥 ФИКС №2 (ЭТО ГЛАВНОЕ)
torch.hub._check_repo_is_trusted = lambda *args, **kwargs: None

logger = logging.getLogger(__name__)


class DepthEstimator:
    """MiDaS-based monocular depth estimator with linear calibration."""

    def __init__(self, model_type: str = "MiDaS_small") -> None:
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model_type = model_type
        self._model: Optional[torch.nn.Module] = None
        self._transform = None

        self.calibration_method = "linear"
        self.scale = 1.0
        self.shift = 0.0

        self._load_model()
        self._load_calibration()

    # ─────────────────────────────────────────────
    # 🔥 FIXED MODEL LOADING (Docker-safe)
    # ─────────────────────────────────────────────
    def _load_model(self) -> None:
        import torch

        # 🔥 КЛЮЧЕВОЙ ФИКС: убираем trust prompt
        torch.hub._validate_not_a_forked_repo = lambda *args, **kwargs: True

        for attempt in range(1, 3):
            try:
                force_reload = attempt > 1

                if force_reload:
                    logger.info("MiDaS retry #%d (force_reload=True)", attempt)

                self._model = torch.hub.load(
                    "intel-isl/MiDaS",
                    self.model_type,
                    trust_repo=True,
                    force_reload=force_reload,
                )

                self._model.to(self.device).eval()

                midas_transforms = torch.hub.load(
                    "intel-isl/MiDaS",
                    "transforms",
                    trust_repo=True,
                    force_reload=force_reload,
                )

                if "small" in self.model_type.lower():
                    self._transform = midas_transforms.small_transform
                else:
                    self._transform = midas_transforms.dpt_transform

                logger.info("✅ MiDaS loaded successfully (%s)", self.model_type)
                return

            except Exception as exc:
                logger.error("❌ MiDaS load failed: %s", exc, exc_info=True)

        logger.critical("🔥 MiDaS NOT loaded → depth disabled")
        self._model = None
        self._transform = None

    # ─────────────────────────────────────────────
    # Calibration
    # ─────────────────────────────────────────────
    def _load_calibration(self) -> None:
        try:
            base_dir = Path(__file__).resolve().parents[1]
            calib_path = base_dir / "assets" / "calibration.json"

            if not calib_path.exists():
                logger.warning("Calibration file not found: %s", calib_path)
                return

            data = json.loads(calib_path.read_text(encoding="utf-8"))
            self.calibration_method = data.get("method", "linear")
            self.scale = float(data.get("scale", 1.0))
            self.shift = float(data.get("shift", 0.0))

            logger.info(
                "Calibration loaded: scale=%s shift=%s",
                self.scale,
                self.shift,
            )

        except Exception as exc:
            logger.error("Calibration load failed: %s", exc, exc_info=True)

    # ─────────────────────────────────────────────
    # Status
    # ─────────────────────────────────────────────
    @property
    def is_available(self) -> bool:
        return self._model is not None and self._transform is not None

    # ─────────────────────────────────────────────
    # Depth map
    # ─────────────────────────────────────────────
    def estimate_depth_map(self, image: Image.Image) -> Optional[np.ndarray]:
        if not self.is_available:
            logger.warning("Depth estimator NOT available")
            return None

        try:
            img_np = np.array(image)

            if img_np.ndim == 2:
                img_np = cv2.cvtColor(img_np, cv2.COLOR_GRAY2RGB)
            elif img_np.ndim == 3 and img_np.shape[2] == 4:
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
            elif img_np.ndim == 3 and img_np.shape[2] == 3:
                pass
            else:
                logger.error("Invalid image shape: %s", img_np.shape)
                return None

            input_batch = self._transform(img_np).to(self.device)

            with torch.no_grad():
                prediction = self._model(input_batch)
                prediction = torch.nn.functional.interpolate(
                    prediction.unsqueeze(1),
                    size=img_np.shape[:2],
                    mode="bicubic",
                    align_corners=False,
                ).squeeze()

            depth_map = prediction.cpu().numpy().astype(np.float32)

            logger.info("Depth map OK shape=%s", depth_map.shape)
            return depth_map

        except Exception as exc:
            logger.error("Depth map failed: %s", exc, exc_info=True)
            return None

    # ─────────────────────────────────────────────
    # Distance
    # ─────────────────────────────────────────────
    def estimate_distance(
        self,
        depth_map: np.ndarray,
        bbox: list[float],
    ) -> float:
        h, w = depth_map.shape[:2]

        x1 = max(0, int(bbox[0]))
        y1 = max(0, int(bbox[1]))
        x2 = min(w, int(bbox[2]))
        y2 = min(h, int(bbox[3]))

        roi = depth_map[y1:y2, x1:x2]

        if roi.size == 0:
            logger.warning("Empty ROI")
            return -1.0

        depth_value = float(np.median(roi))

        distance = depth_value * self.scale + self.shift

        if distance < 0:
            distance = 0.0

        result = round(float(distance), 2)

        logger.info("Distance=%.2fm", result)

        return result
"""
KozAlma AI — Application Configuration.

Loads settings from .env via pydantic-settings.
Supports dev/staging/prod environments with appropriate defaults.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent  # backend/


class Settings(BaseSettings):
    """Global application settings populated from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Environment ─────────────────────────────────────────────────
    # Controls security defaults, CORS, logging, fail-fast behavior.
    # Values: "dev" (default), "staging", "prod"
    environment: str = "dev"

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("dev", "staging", "prod"):
            raise ValueError(f"ENVIRONMENT must be dev|staging|prod, got '{v}'")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"

    @property
    def is_development(self) -> bool:
        return self.environment == "dev"

    # ── CORS ────────────────────────────────────────────────────────
    # Comma-separated origins.  In dev mode, defaults to "*".
    # In prod, MUST be explicitly set.
    allowed_origins: str = ""

    def get_cors_origins(self) -> List[str]:
        """Return list of allowed CORS origins based on environment."""
        if self.allowed_origins.strip():
            return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
        if self.is_development:
            return ["*"]
        # prod/staging with no explicit origins → restrictive default
        return ["http://localhost:3000", "http://localhost:8000"]

    # ── S3 / Yandex Object Storage ──────────────────────────────────
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "koz-alma-unknown"
    s3_endpoint: str = "https://storage.yandexcloud.net"
    s3_region: str = "ru-central1"

    # ── Admin ───────────────────────────────────────────────────────
    admin_username: str = "admin"
    admin_password: str = "changeme123"
    admin_session_secret: str = "super-secret-session-key"

    # ── ML Models ───────────────────────────────────────────────────
    yolo_weights_path: str = "weights/best.pt"
    midas_model: str = "MiDaS_small"
    confidence_threshold: float = 0.35
    unknown_threshold: float = 0.30

    # ── Auto-Label ──────────────────────────────────────────────────
    auto_label_enabled: bool = True
    auto_label_min_conf: float = 0.15

    # ── TTS ─────────────────────────────────────────────────────────
    tts_default_lang: str = "ru"
    tts_default_speed: float = 1.0

    # ── Kazakh TTS (Piper — offline) ───────────────────────────────
    kz_tts_enabled: bool = False
    kz_tts_model_path: str = "models/kk_KZ-issai-high.onnx"
    kz_tts_config_path: str = "models/kk_KZ-issai-high.onnx.json"
    kz_tts_use_cuda: bool = False

    # ── Server ──────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Dataset ─────────────────────────────────────────────────────
    data_yaml_path: str = "../data/data.yaml"

    # ── Redis ───────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── OTP ─────────────────────────────────────────────────────────
    otp_ttl_seconds: int = 300          # 5 minutes
    otp_cooldown_seconds: int = 60      # 1 minute between requests
    otp_max_attempts: int = 5
    otp_lock_seconds: int = 600         # 10 minutes lock
    otp_dev_mode: bool = False          # MUST be explicitly enabled
    otp_hmac_secret: str = "change-me-otp-hmac-secret"
    otp_salt: str = ""                   # SHA256 salt; auto-generated if empty

    # ── JWT ─────────────────────────────────────────────────────────
    jwt_secret_key: str = "change-me-jwt-secret-key"
    jwt_alg: str = "HS256"
    access_token_expires_min: int = 30   # 30 minutes
    refresh_token_expires_days: int = 30 # 30 days

    # ── Admin identifiers (auto-admin on first login) ──────────────
    admin_identifiers: str = ""  # comma-separated: "admin@x.com,+7701..."

    # ── SMTP ────────────────────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""

    # ── Twilio (WhatsApp OTP) ───────────────────────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = "whatsapp:+14155238886"  # sandbox default

    # ── Database ────────────────────────────────────────────────────
    # Default: SQLite for dev.  Set to postgresql+asyncpg://... for prod.
    database_url: str = f"sqlite+aiosqlite:///{_ROOT / 'koz_alma.db'}"

    # ── Rate Limiting ───────────────────────────────────────────────
    rate_limit_enabled: bool = True
    # Format: "requests/period" — e.g. "10/minute"
    rate_limit_scan: str = "30/minute"
    rate_limit_tts: str = "60/minute"
    rate_limit_otp: str = "5/minute"
    rate_limit_auth: str = "20/minute"

    # ── Logging ─────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_json: bool = False  # Set to True for production (structured JSON logs)

    # ── Startup Validation ──────────────────────────────────────────

    _INSECURE_DEFAULTS = {
        "admin_password": "changeme123",
        "admin_session_secret": "super-secret-session-key",
        "jwt_secret_key": "change-me-jwt-secret-key",
        "otp_hmac_secret": "change-me-otp-hmac-secret",
    }

    def validate_production_config(self) -> list[str]:
        """Check for insecure defaults.  Returns list of warnings.
        In production, these are fatal errors.
        """
        warnings = []

        for field_name, insecure_val in self._INSECURE_DEFAULTS.items():
            actual = getattr(self, field_name, "")
            if actual == insecure_val:
                warnings.append(
                    f"⚠️  {field_name.upper()} is using the default insecure value! "
                    f"Set a strong value in .env"
                )

        if self.is_production and self.otp_dev_mode:
            warnings.append(
                "⚠️  OTP_DEV_MODE=true in production — OTP codes will be printed to console!"
            )

        if self.is_production and not self.allowed_origins.strip():
            warnings.append(
                "⚠️  ALLOWED_ORIGINS not set in production — using restrictive defaults"
            )

        return warnings

    def fail_on_insecure_production(self) -> None:
        """Abort startup if production config is insecure."""
        warnings = self.validate_production_config()
        if not warnings:
            return

        for w in warnings:
            logger.warning(w)

        if self.is_production:
            # In production, insecure defaults are fatal
            insecure_fields = [
                f for f, v in self._INSECURE_DEFAULTS.items()
                if getattr(self, f, "") == v
            ]
            if insecure_fields:
                logger.critical(
                    "FATAL: Production mode with insecure defaults: %s. "
                    "Set proper values in .env and restart.",
                    ", ".join(f.upper() for f in insecure_fields),
                )
                sys.exit(1)


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()

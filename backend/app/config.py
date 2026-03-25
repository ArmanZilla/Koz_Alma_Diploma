"""
KozAlma AI — Application Configuration.

Loads settings from .env via pydantic-settings.
"""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


_ROOT = Path(__file__).resolve().parent.parent  # backend/


class Settings(BaseSettings):
    """Global application settings populated from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── S3 / Yandex Object Storage ──────────────────────────────────────
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "koz-alma-unknown"
    s3_endpoint: str = "https://storage.yandexcloud.net"
    s3_region: str = "ru-central1"

    # ── Admin ───────────────────────────────────────────────────────────
    admin_username: str = "admin"
    admin_password: str = "changeme123"
    admin_session_secret: str = "super-secret-session-key"

    # ── ML Models ───────────────────────────────────────────────────────
    yolo_weights_path: str = "weights/best.pt"
    midas_model: str = "MiDaS_small"
    confidence_threshold: float = 0.35
    unknown_threshold: float = 0.30

    # ── Auto-Label ──────────────────────────────────────────────────────
    auto_label_enabled: bool = True
    auto_label_min_conf: float = 0.15

    # ── TTS ─────────────────────────────────────────────────────────────
    tts_default_lang: str = "ru"
    tts_default_speed: float = 1.0

    # ── Server ──────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Dataset ─────────────────────────────────────────────────────────
    data_yaml_path: str = str(_ROOT.parent / "data" / "data.yaml")

    # ── Redis ───────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── OTP ─────────────────────────────────────────────────────────────
    otp_ttl_seconds: int = 300          # 5 minutes
    otp_cooldown_seconds: int = 60      # 1 minute between requests
    otp_max_attempts: int = 5
    otp_lock_seconds: int = 600         # 10 minutes lock
    otp_dev_mode: bool = True           # print OTP to console
    otp_hmac_secret: str = "change-me-otp-hmac-secret"
    otp_salt: str = ""                   # SHA256 salt; auto-generated if empty

    # ── JWT ─────────────────────────────────────────────────────────────
    jwt_secret_key: str = "change-me-jwt-secret-key"
    jwt_alg: str = "HS256"
    access_token_expires_min: int = 30   # 30 minutes
    refresh_token_expires_days: int = 30 # 30 days

    # ── Admin identifiers (auto-admin on first login) ──────────────────
    admin_identifiers: str = ""  # comma-separated: "admin@x.com,+7701..."

    # ── SMTP ────────────────────────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""

    # ── Twilio (WhatsApp OTP) ───────────────────────────────────────────
    # Leave empty to disable WhatsApp channel (app won't crash).
    # For Twilio Sandbox: user must first send "join <sandbox-code>"
    # to the sandbox number before receiving messages.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = "whatsapp:+14155238886"  # sandbox default

    # ── Database ────────────────────────────────────────────────────────
    database_url: str = f"sqlite+aiosqlite:///{_ROOT / 'koz_alma.db'}"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()

"""
KozAlma AI — FastAPI Application Entry Point.

Loads ML models on startup, mounts static files, and includes all routers.
Supports dev/staging/prod environments with appropriate security defaults.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.middleware import (
    JsonLogFormatter,
    RequestIdMiddleware,
    RequestLoggingMiddleware,
)


def _setup_logging() -> None:
    """Configure logging based on settings."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Clear existing handlers to avoid duplicates on reload
    root.handlers.clear()

    import io
    handler = logging.StreamHandler(
        io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    )
    handler.setLevel(level)

    if settings.log_json:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
            )
        )

    root.addHandler(handler)

    # Quiet noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)


_setup_logging()
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Lifespan: startup/shutdown
# ═══════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load ML models and shared services on startup."""
    settings = get_settings()
    logger.info(
        "Starting KozAlma AI backend (env=%s, port=%d)...",
        settings.environment, settings.port,
    )

    # ── Security validation ──
    settings.fail_on_insecure_production()

    # ── Database (SQLite/PostgreSQL) — create tables ──
    try:
        from app.db.session import init_db
        await init_db()
        logger.info("✅ Database initialized")
    except Exception as exc:
        logger.error("Database init failed: %s", exc)
        if settings.is_production:
            logger.critical("FATAL: Database required in production")
            sys.exit(1)

    # ── Redis ──
    redis_client = None
    try:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        await redis_client.ping()
        logger.info("✅ Redis connected (%s)", settings.redis_url)
    except Exception as exc:
        logger.warning("Redis not available: %s — auth endpoints will return 503", exc)
        redis_client = None
        if settings.is_production:
            logger.critical("FATAL: Redis required in production for OTP/auth")
            sys.exit(1)

    # ── ML models ──
    from app.ml.detector import YOLODetector
    from app.ml.depth import DepthEstimator
    from app.ml.pipeline import ScanPipeline

    try:
        detector = YOLODetector(
            weights_path=settings.yolo_weights_path,
            confidence=settings.confidence_threshold,
        )
        depth_estimator = DepthEstimator(model_type=settings.midas_model)
        pipeline = ScanPipeline(
            detector=detector,
            depth_estimator=depth_estimator,
            unknown_threshold=settings.unknown_threshold,
        )
        logger.info("✅ ML pipeline initialized")
    except Exception as exc:
        logger.error("ML model loading failed: %s", exc)
        if settings.is_production:
            logger.critical("FATAL: ML models required in production")
            sys.exit(1)
        # Dev mode: create degraded pipeline
        detector = None
        depth_estimator = None
        pipeline = None

    # ── TTS ──
    from app.tts.engine import TTSEngine

    kz_engine = None
    if settings.kz_tts_enabled:
        try:
            from app.tts.kazakh_tts_engine import KazakhTTSEngine
            kz_engine = KazakhTTSEngine(
                model_path=settings.kz_tts_model_path,
                config_path=settings.kz_tts_config_path,
                use_cuda=settings.kz_tts_use_cuda,
            )
            logger.info("✅ Kazakh TTS (Piper) engine ready")
        except ImportError as exc:
            logger.warning(
                "Kazakh TTS disabled — piper-tts not installed: %s. "
                "Install with: pip install piper-tts", exc,
            )
        except FileNotFoundError as exc:
            logger.warning(
                "Kazakh TTS disabled — model files not found: %s. "
                "Download from: https://huggingface.co/rhasspy/piper-voices", exc,
            )
        except Exception as exc:
            logger.warning(
                "Kazakh TTS disabled — initialization failed: %s. "
                "Falling back to gTTS for all languages.", exc,
            )
    else:
        logger.info("Kazakh TTS (Piper) disabled by config (KZ_TTS_ENABLED=false)")

    tts_engine = TTSEngine(kz_engine=kz_engine)

    # ── S3 / Yandex Object Storage ──
    unknown_manager = None
    if settings.s3_access_key and settings.s3_secret_key:
        try:
            from app.storage.s3_client import S3Client
            from app.storage.unknown_manager import UnknownManager

            s3 = S3Client(
                access_key=settings.s3_access_key,
                secret_key=settings.s3_secret_key,
                bucket=settings.s3_bucket,
                endpoint=settings.s3_endpoint,
                region=settings.s3_region,
            )

            bucket_ok = s3.validate_bucket()
            if bucket_ok:
                unknown_manager = UnknownManager(s3)

                if settings.auto_label_enabled and detector is not None:
                    from app.services.auto_label_service import AutoLabelService
                    auto_label_svc = AutoLabelService(
                        s3=s3,
                        detector=detector,
                        min_conf=settings.auto_label_min_conf,
                    )
                    unknown_manager.set_auto_label_service(auto_label_svc)
                    logger.info("Auto-label pipeline enabled (min_conf=%.2f)", settings.auto_label_min_conf)
                else:
                    logger.info("Auto-label pipeline disabled by config")

                logger.info("✅ S3 unknown manager enabled (bucket=%s)", settings.s3_bucket)
            else:
                logger.warning(
                    "S3 bucket '%s' is not accessible — unknown image storage disabled. "
                    "Check credentials, bucket name, and endpoint.",
                    settings.s3_bucket,
                )
        except Exception as exc:
            logger.error("S3 initialization failed: %s — unknown image storage disabled", exc)
    else:
        logger.warning("S3 credentials not set — unknown image storage disabled")

    # Store in app state for access in routes
    app.state.pipeline = pipeline
    app.state.tts_engine = tts_engine
    app.state.unknown_manager = unknown_manager
    app.state.redis = redis_client
    app.state.settings = settings

    logger.info("✅ KozAlma AI backend ready (env=%s)", settings.environment)
    yield

    # ── Shutdown ──
    logger.info("Shutting down KozAlma AI backend...")
    if redis_client:
        await redis_client.close()


# ═══════════════════════════════════════════════════════════════════════
# App factory
# ═══════════════════════════════════════════════════════════════════════

def create_app() -> FastAPI:
    """Factory function to create the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="KozAlma AI",
        description="Visual assistant API for visually impaired users",
        version="1.0.0",
        lifespan=lifespan,
        # Disable docs in production for security
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    # ── Middleware (order matters: outermost first) ──
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestIdMiddleware)

    # ── CORS ──
    origins = settings.get_cors_origins()
    allow_all = origins == ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=not allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if allow_all:
        logger.warning("CORS: allow_origins=['*'] (dev mode)")
    else:
        logger.info("CORS: allow_origins=%s", origins)

    # ── Mount static files for admin panel ──
    static_dir = Path(__file__).parent / "admin_web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ── Include routers (with /api/v1 prefix for API routes) ──
    from app.api.routes.scan import router as scan_router
    from app.api.routes.unknown import router as unknown_router
    from app.api.routes.auth import router as auth_router
    from app.api.routes.tts import router as tts_router
    from app.admin_web.router import router as admin_router

    app.include_router(scan_router, prefix="/api/v1")
    app.include_router(unknown_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(tts_router, prefix="/api/v1")
    app.include_router(admin_router)

    # ── Backward‑compatible routes (no prefix) — keeps Flutter working ──
    app.include_router(scan_router)
    app.include_router(unknown_router)
    app.include_router(auth_router)
    app.include_router(tts_router)

    # ── Health / Readiness endpoints ──
    @app.get("/health")
    async def health():
        """Liveness probe — returns OK if the process is alive."""
        return {"status": "ok", "service": "koz-alma-ai"}

    @app.get("/readiness")
    async def readiness(request: Request):
        """Readiness probe — checks that critical dependencies are up."""
        checks = {}
        ready = True

        # ML pipeline
        pipeline_ok = getattr(request.app.state, "pipeline", None) is not None
        checks["ml_pipeline"] = "ok" if pipeline_ok else "unavailable"
        if not pipeline_ok:
            ready = False

        # Redis
        redis = getattr(request.app.state, "redis", None)
        if redis is not None:
            try:
                await redis.ping()
                checks["redis"] = "ok"
            except Exception:
                checks["redis"] = "unavailable"
                ready = False
        else:
            checks["redis"] = "not_configured"

        # S3
        s3_ok = getattr(request.app.state, "unknown_manager", None) is not None
        checks["s3_storage"] = "ok" if s3_ok else "not_configured"

        # TTS
        tts = getattr(request.app.state, "tts_engine", None)
        checks["tts"] = "ok" if tts is not None else "unavailable"

        status_code = 200 if ready else 503
        return JSONResponse(
            content={
                "status": "ready" if ready else "degraded",
                "checks": checks,
                "environment": get_settings().environment,
            },
            status_code=status_code,
        )

    return app


from fastapi.responses import JSONResponse  # noqa: E402 — used in readiness

app = create_app()

"""
KozAlma AI — FastAPI Application Entry Point.

Loads ML models on startup, mounts static files, and includes all routers.
CORS is enabled for Flutter Web development.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load ML models and shared services on startup."""
    settings = get_settings()
    logger.info("Starting KozAlma AI backend...")

    # ── Database (SQLite) — create tables ──
    try:
        from app.db.session import init_db
        await init_db()
        logger.info("Database initialized")
    except Exception as exc:
        logger.error("Database init failed: %s", exc)

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

    # ── ML models ──
    from app.ml.detector import YOLODetector
    from app.ml.depth import DepthEstimator
    from app.ml.pipeline import ScanPipeline

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

    # ── TTS ──
    from app.tts.engine import TTSEngine

    tts_engine = TTSEngine()

    # ── S3 / Yandex Object Storage — Unknown Manager ──
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

                # Inject auto-label service if enabled
                if settings.auto_label_enabled:
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

                logger.info("S3 unknown manager enabled (bucket=%s)", settings.s3_bucket)
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

    logger.info("✅ KozAlma AI backend ready")
    yield

    # ── Shutdown ──
    logger.info("Shutting down KozAlma AI backend...")
    if redis_client:
        await redis_client.close()


def create_app() -> FastAPI:
    """Factory function to create the FastAPI application."""
    app = FastAPI(
        title="KozAlma AI",
        description="Visual assistant API for visually impaired users",
        version="1.0.0",
        lifespan=lifespan,
    )

    # ── CORS — must be added BEFORE routers ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.warning("CORS middleware enabled: allow_origins=['*']")

    # ── Mount static files for admin panel ──
    static_dir = Path(__file__).parent / "admin_web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ── Include routers ──
    from app.api.routes.scan import router as scan_router
    from app.api.routes.unknown import router as unknown_router
    from app.api.routes.auth import router as auth_router
    from app.admin_web.router import router as admin_router

    app.include_router(scan_router)
    app.include_router(unknown_router)
    app.include_router(auth_router)
    app.include_router(admin_router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "koz-alma-ai"}

    return app


app = create_app()

"""
KozAlma AI — TTS Speak Route.

Minimal endpoint for UI speech synthesis.
Reuses the existing TTSEngine (Piper for Kazakh, gTTS for Russian).

Used by Flutter (Web + Mobile) for Kazakh UI speech, since browser
speechSynthesis and Android flutter_tts lack quality kk-KZ voices.

Includes in-memory cache for short repeated UI phrases (welcome,
button labels, hints, etc.) to minimize Piper synthesis latency.
Cache key: md5(text + lang + speed).  Max 128 entries, FIFO eviction.
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.config import get_settings
from app.middleware import check_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tts", tags=["tts"])

# ── In-memory audio cache for short UI phrases ────────────────────────
# OrderedDict gives us insertion-order, so we can pop the oldest entry
# when the cache fills up (FIFO eviction).
_CACHE_MAX = 128
_audio_cache: OrderedDict[str, str] = OrderedDict()


def _cache_key(text: str, lang: str, speed: float) -> str:
    """Generate a stable cache key from text + lang + speed."""
    raw = f"{text}|{lang}|{speed:.2f}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class SpeakRequest(BaseModel):
    text: str
    lang: str = "kz"
    speed: float = 1.0


@router.post("/speak")
async def speak(req: SpeakRequest, request: Request):
    """Synthesize text to speech and return base64 audio.

    Short phrases (< 200 chars) are cached in memory so that
    repeated UI speech (buttons, greetings) returns instantly.
    """
    # ── Rate limiting ──
    settings = get_settings()
    rl_response = check_rate_limit(
        request, "tts", settings.rate_limit_tts, settings.rate_limit_enabled,
    )
    if rl_response:
        return rl_response

    key = _cache_key(req.text, req.lang, req.speed)

    # ── Cache hit → instant return ────────────────────────────────
    if key in _audio_cache:
        # Move to end (LRU touch) so recently-used entries survive longer
        _audio_cache.move_to_end(key)
        logger.debug("TTS cache hit: %s (lang=%s)", req.text[:40], req.lang)
        return {"audio_base64": _audio_cache[key]}

    # ── Cache miss → synthesize ───────────────────────────────────
    tts_engine = request.app.state.tts_engine

    audio_b64 = tts_engine.synthesize(
        text=req.text,
        lang=req.lang,
        speed=req.speed,
    )

    if audio_b64 is None:
        return {"audio_base64": None, "error": "synthesis_failed"}

    # ── Store in cache (short UI phrases only) ────────────────────
    if len(req.text) < 200:
        # Evict oldest entries if cache is full
        while len(_audio_cache) >= _CACHE_MAX:
            evicted_key, _ = _audio_cache.popitem(last=False)
            logger.debug("TTS cache evict: %s", evicted_key[:12])
        _audio_cache[key] = audio_b64
        logger.debug(
            "TTS cache store: %s (lang=%s, entries=%d)",
            req.text[:40], req.lang, len(_audio_cache),
        )

    return {"audio_base64": audio_b64}

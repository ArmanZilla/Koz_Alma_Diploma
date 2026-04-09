# KozAlma AI — Architecture

## System Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    Flutter Mobile / Web App                    │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌───────────┐     │
│  │ Welcome  │→ │  Camera   │→ │ Result  │  │ Settings  │     │
│  │ Screen   │  │  Screen   │  │ Screen  │  │  Screen   │     │
│  └─────────┘  └────┬─────┘  └─────────┘  └───────────┘     │
│              POST /scan │                                     │
│              ┌──────┴──────┐                                  │
│              │ API Service │──── Auth API (OTP + JWT)         │
│              └──────┬──────┘                                  │
└─────────────────────┼────────────────────────────────────────┘
                      │ HTTP
┌─────────────────────┼────────────────────────────────────────┐
│              FastAPI Backend                                  │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐     │
│  │                Scan Pipeline                         │     │
│  │  1. YOLOv8 (object detection, 39 classes)           │     │
│  │  2. MiDaS (monocular depth → meters)                │     │
│  │  3. Text Builder (RU/KZ localization)               │     │
│  │  4. TTS Engine:                                      │     │
│  │     - Russian → gTTS (online)                        │     │
│  │     - Kazakh → Piper TTS (offline ONNX)             │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                               │
│  ┌───────────┐  ┌───────────┐  ┌────────────┐               │
│  │ OTP Auth  │  │ S3 Unknown│  │ Admin Panel│               │
│  │ (Redis +  │  │ Manager + │  │ (Jinja2 +  │               │
│  │  JWT)     │  │ AutoLabel │  │  Cookie)   │               │
│  └─────┬─────┘  └─────┬─────┘  └────────────┘               │
│        │               │                                      │
│  ┌─────┴─────┐  ┌─────┴──────────┐                          │
│  │  Redis    │  │  Yandex S3     │                          │
│  │  (OTP +   │  │  (images +     │                          │
│  │  sessions)│  │  labels + meta)│                          │
│  └───────────┘  └────────────────┘                          │
│        │                                                      │
│  ┌─────┴─────────────────────┐                               │
│  │  SQLite (dev) /           │                               │
│  │  PostgreSQL (prod)        │                               │
│  │  — user accounts          │                               │
│  └───────────────────────────┘                               │
└──────────────────────────────────────────────────────────────┘
```

## ML Pipeline

1. **YOLOv8** — Custom 39-class object detection (3,000 images, 60 epochs)
2. **MiDaS Small** — Monocular depth estimation (relative depth map)
3. **Calibration** — Linear model: `distance ≈ depth × scale + shift`
4. **Text Builder** — Position (left/center/right) + distance in RU/KZ
5. **TTS Engine** — Piper (Kazakh, offline WAV) + gTTS (Russian, online MP3)

## Auth Flow

```
Client → POST /auth/request-code {channel, identifier}
  → OTP generated → SHA256(code + salt) stored in Redis (TTL)
  → Code sent via Email (SMTP) / WhatsApp (Twilio) / Console (dev)

Client → POST /auth/verify-code {channel, identifier, code}
  → Verify hash → Create/find user in DB
  → Issue JWT access + refresh tokens

Client → GET /auth/me (Bearer token)
  → Return user profile

Client → POST /auth/refresh {refresh_token}
  → Issue new token pair
```

## Active Learning Loop

```
Camera → Low confidence? → Store to S3 → Auto-label (YOLO) →
  → Admin reviews → Label corrections → Add to training data → Retrain
```

## Data Flow (S3)

- Images grouped by `YYYY-MM-DD/session_id/` in S3
- Each image stored with `_meta.json` (timestamp, detection count)
- Auto-label stores: `labels/*.txt` (YOLO format) + `pred/*.json`
- Admin downloads ZIP → labels in annotation tool → adds to training data

## Rate Limiting

In-memory sliding window rate limiter per endpoint group:
- `/scan` — 30/minute per IP
- `/tts/speak` — 60/minute per IP
- `/auth/request-code` — 5/minute per IP
- `/auth/verify-code` — 20/minute per IP

## Environments

| Setting | Dev | Staging | Prod |
|---------|-----|---------|------|
| CORS | `*` (all) | Configured | Configured |
| OTP Mode | Console | Email/SMS | Email/SMS |
| DB | SQLite | PostgreSQL | PostgreSQL |
| Docs | Enabled | Enabled | Disabled |
| Fail-fast | No | Yes | Yes |
| Logging | Text | JSON | JSON |

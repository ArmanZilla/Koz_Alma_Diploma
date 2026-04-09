# KozAlma AI

**Visual assistant for visually impaired users** — detects objects via camera, estimates distance using depth (MiDaS), generates bilingual RU/KZ speech (Piper TTS + gTTS), and actively learns from unknown images.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Flutter Mobile / Web App                    │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌───────────┐     │
│  │ Welcome  │→ │  Camera   │→ │ Result  │  │ Settings  │     │
│  │ Screen   │  │  Screen   │  │ Screen  │  │  Screen   │     │
│  └─────────┘  └────┬─────┘  └─────────┘  └───────────┘     │
│              POST /scan │                                     │
└──────────────────────┼───────────────────────────────────────┘
                       │
┌──────────────────────┼───────────────────────────────────────┐
│              FastAPI Backend                                  │
│  ┌───────────────────┼───────────────────────────────┐       │
│  │            Scan Pipeline                           │       │
│  │  YOLOv8 ─→ MiDaS Depth ─→ Text Builder ─→ TTS   │       │
│  └───────────────────────────────────────────────────┘       │
│                                                               │
│  ┌───────────┐  ┌───────────┐  ┌────────────┐               │
│  │ OTP Auth  │  │ S3 Unknown│  │ Admin Panel│               │
│  │ (Redis)   │  │ Manager   │  │ (Jinja2)   │               │
│  └───────────┘  └───────────┘  └────────────┘               │
└──────────────────────────────────────────────────────────────┘
```

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11, FastAPI, Uvicorn |
| **ML Detection** | YOLOv8 (Ultralytics), custom 39-class model |
| **Depth Estimation** | MiDaS (Intel ISL) |
| **TTS — Russian** | gTTS (Google Translate TTS) |
| **TTS — Kazakh** | Piper TTS (offline ONNX model) |
| **Auth** | Passwordless OTP (email/WhatsApp/phone) |
| **Session** | Redis + JWT (HS256) |
| **Database** | SQLite (dev) / PostgreSQL (prod) via SQLAlchemy |
| **Object Storage** | Yandex Object Storage (S3-compatible) |
| **Frontend** | Flutter (Android + Web + iOS) |
| **Infrastructure** | Docker, Docker Compose |

## ML Model

- **Architecture:** YOLOv8 (custom-trained)
- **Classes:** 39 (see `data/data.yaml`)
- **Training data:** 3,000 labeled images
- **Training:** 60 epochs, imgsz=640
- **Split:** 80% train / 10% val / 10% test
- **Depth:** MiDaS Small with linear calibration

## Quick Start

### Prerequisites

- Python 3.11+
- Redis (for auth/OTP)
- YOLOv8 weights file (`weights/best.pt`)
- (Optional) Piper TTS model for Kazakh

### Backend — Local Development

```bash
cd backend
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
# source venv/bin/activate

pip install -r requirements.txt -r requirements-dev.txt

# Copy and configure .env
cp ../.env.example .env
# Edit .env: set S3 keys, passwords, secrets

# Start Redis (requires Docker)
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Initialize database (auto-creates on first run)
# Or use Alembic:
# alembic upgrade head

# Run server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
 docker compose up -d --build

API docs: http://localhost:8000/docs
Admin panel: http://localhost:8000/admin/login

### Backend — Docker

```bash
# 1. Configure
cp .env.example backend/.env
# Edit backend/.env with real values
# Set REDIS_URL=redis://redis:6379/0

# 2. Place model weights
# Put your best.pt in backend/weights/
# Put Piper models in backend/models/ (optional)

# 3. Build and run
docker compose up -d --build

# 4. Verify
curl http://localhost:8000/health
curl http://localhost:8000/readiness
```

### Frontend (Flutter)

```bash
cd frontend
flutter pub get

# For emulator (auto-detects backend URL):
flutter run

# For physical device (specify your backend IP):
flutter run --dart-define=API_URL=http://YOUR_SERVER_IP:8000

# Build APK:
flutter build apk --dart-define=API_URL=https://api.kozalma.kz
```

> **Note:** The frontend is a Flutter app (Android/Web/iOS).
> It is NOT a containerized service — build and deploy it separately.

## Environment Variables

See `.env.example` for the complete list with descriptions.

Key variables:

| Variable | Description | Required |
|---|---|---|
| `ENVIRONMENT` | `dev` / `staging` / `prod` | No (default: dev) |
| `ALLOWED_ORIGINS` | CORS origins (comma-separated) | Prod only |
| `S3_ACCESS_KEY` | Yandex Object Storage access key | For S3 features |
| `S3_SECRET_KEY` | Yandex Object Storage secret key | For S3 features |
| `ADMIN_PASSWORD` | Admin panel password | Yes |
| `JWT_SECRET_KEY` | JWT signing secret | Yes (change default!) |
| `OTP_HMAC_SECRET` | OTP hashing secret | Yes (change default!) |
| `REDIS_URL` | Redis connection URL | For auth features |
| `DATABASE_URL` | Database URL (SQLite or PostgreSQL) | No (default: SQLite) |
| `YOLO_WEIGHTS_PATH` | Path to YOLOv8 weights | Yes |
| `KZ_TTS_ENABLED` | Enable Piper Kazakh TTS | No (default: false) |

## API Endpoints

### Core API (`/api/v1/...` or legacy `/...`)

| Method | Path | Description | Auth |
|---|---|---|---|
| `POST` | `/scan` | Scan image → detections + TTS | Optional |
| `POST` | `/tts/speak` | Text-to-speech synthesis | No |
| `POST` | `/auth/request-code` | Send OTP code | No |
| `POST` | `/auth/verify-code` | Verify OTP → JWT tokens | No |
| `POST` | `/auth/refresh` | Refresh JWT tokens | No |
| `GET` | `/auth/me` | Current user profile | JWT |
| `GET` | `/unknown/groups` | List unknown image groups | No |
| `POST` | `/unknown/upload` | Upload unknown image | JWT |

### System

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/readiness` | Readiness probe (checks deps) |
| `GET` | `/admin/login` | Admin panel login |

## Kazakh TTS (Piper — Offline)

The backend uses **Piper TTS** for high-quality offline Kazakh speech synthesis:

| Language | Engine | Output | Internet Required |
|----------|--------|--------|-------------------|
| Russian (`ru`) | gTTS (Google) | MP3 | Yes |
| Kazakh (`kz`) | Piper TTS (local) | WAV | No |

### Setup Piper TTS

```bash
# 1. Download model
# From: https://huggingface.co/rhasspy/piper-voices
# Place in backend/models/:
#   kk_KZ-issai-high.onnx
#   kk_KZ-issai-high.onnx.json

# 2. Enable in .env
KZ_TTS_ENABLED=true

# 3. Restart backend
```

## Accessibility (Flutter)

- **1 tap** → speaks button label (no action)
- **2 taps** → executes action
- **Language toggle** in header: 1 tap speaks, 2 taps switches
- **Speed control**: left/right edge zones on camera screen
- **Auto flashlight**: enables when low light detected

## Production Deployment Checklist

- [ ] Set `ENVIRONMENT=prod` in `.env`
- [ ] Generate and set strong values for:
  - `JWT_SECRET_KEY` (`python -c "import secrets; print(secrets.token_hex(32))"`)
  - `OTP_HMAC_SECRET`
  - `ADMIN_PASSWORD`
  - `ADMIN_SESSION_SECRET`
- [ ] Set `OTP_DEV_MODE=false`
- [ ] Set `ALLOWED_ORIGINS` to your actual frontend domains
- [ ] Set `LOG_JSON=true` for structured logging
- [ ] Set `LOG_LEVEL=WARNING` to reduce log volume
- [ ] Configure `DATABASE_URL` for PostgreSQL
- [ ] Configure `REDIS_URL` pointing to production Redis
- [ ] Place ML weights in `backend/weights/best.pt`
- [ ] (Optional) Place Piper models and set `KZ_TTS_ENABLED=true`
- [ ] Configure S3 credentials for unknown image storage
- [ ] Configure SMTP or Twilio for OTP delivery
- [ ] Build Flutter app with production API URL
- [ ] Set up TLS/HTTPS termination (reverse proxy)
- [ ] Set up log aggregation
- [ ] Test all endpoints via `/readiness`

## Database Migrations

Using Alembic for schema management:

```bash
cd backend

# Generate a new migration after changing models
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

## License

CC BY 4.0 (dataset). Project code — proprietary diploma project.

# KozAlma AI

**Visual assistant for visually impaired users** — detects objects via camera, estimates distance using depth (MiDaS), generates RU/KZ speech, and collects unknown images for future labeling.

## Architecture

```
koz_alma_ai/
├── backend/             # FastAPI + ML pipeline
│   ├── app/
│   │   ├── main.py          # App entry point
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── ml/              # YOLOv8 detector + MiDaS depth
│   │   ├── tts/             # gTTS engine (RU/KZ)
│   │   ├── storage/         # S3 unknown image manager
│   │   ├── api/routes/      # /scan, /unknown endpoints
│   │   └── admin_web/       # Admin panel (Jinja2)
│   ├── scripts/             # train_yolo, eval_yolo, data_checks
│   └── requirements.txt
├── frontend/            # Flutter (Android + iOS)
│   └── lib/
│       ├── core/            # accessibility, app_state, constants
│       ├── screens/         # welcome, camera, result, settings
│       ├── widgets/         # accessible_button, language_toggle
│       └── services/        # api, tts, camera
├── data/                # Dataset (data.yaml, splits)
├── experiments/         # Jupyter notebooks
└── docs/                # Documentation
```

## Quick Start

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt

# Copy and configure .env
cp ../.env.example .env
# Edit .env: set S3 keys, ADMIN_PASSWORD, YOLO_WEIGHTS_PATH

# Run server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs  
Admin panel: http://localhost:8000/admin/login

### Frontend (Flutter)

```bash
cd frontend
flutter pub get
flutter run
 docker exec -it redis redis-cli ping 


 docker start redis


```

> **Note:** Set `AppConstants.apiBaseUrl` in `lib/core/constants.dart` to your backend URL.  
> For Android emulator: `http://10.0.2.2:8000`

### ML Training

```bash
cd backend
python scripts/train_yolo.py --epochs 100 --imgsz 640 --batch 16
python scripts/eval_yolo.py --weights runs/detect/koz_alma_train/weights/best.pt
python scripts/data_checks.py --data ../data/data.yaml
```

## Environment Variables (.env)

| Variable | Description |
|---|---|
| `S3_ACCESS_KEY` | Yandex Object Storage access key |
| `S3_SECRET_KEY` | Yandex Object Storage secret key |
| `S3_BUCKET` | S3 bucket name |
| `S3_ENDPOINT` | S3 endpoint URL |
| `ADMIN_PASSWORD` | Admin panel password |
| `YOLO_WEIGHTS_PATH` | Path to YOLOv8 weights (best.pt) |
| `MIDAS_MODEL` | MiDaS model variant (default: MiDaS_small) |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/scan` | Scan image → detections + TTS audio |
| `GET` | `/unknown/groups` | List unknown image groups |
| `GET` | `/unknown/groups/{id}/images` | List images in a group |
| `GET` | `/unknown/groups/{id}/download` | Download group as ZIP |
| `GET` | `/admin` | Admin dashboard |
| `GET` | `/health` | Health check |

## Dataset

- Format: YOLO (txt labels)
- Classes: 39 (see `data/data.yaml`)
- Current: 171 labeled images, target ~3000
- Split: 80% train / 10% val / 10% test

## Accessibility (Flutter)

- **1 tap** → speaks button label (no action)
- **2 taps** → executes action
- **Language toggle** in header: 1 tap speaks, 2 taps switches
- **Speed control**: left/right edge zones on camera screen
- **Auto flashlight**: enables when low light detected

## License

CC BY 4.0 (dataset). Project code — proprietary diploma project.

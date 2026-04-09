# ML — Training / Evaluation / Analysis

## Current Model

- **Architecture:** YOLOv8 (custom-trained)
- **Classes:** 39 (see `data/data.yaml`)
- **Training data:** 3,000 labeled images
- **Training:** 60 epochs, imgsz=640
- **Split:** 80% train / 10% val / 10% test

## Scripts

Located in `backend/scripts/`:

| Script | Description |
|--------|-------------|
| `train_yolo.py` | Train YOLOv8 on labeled dataset |
| `eval_yolo.py` | Evaluate model on test split |
| `data_checks.py` | Data analytics + visualizations |

## Workflow

### 1. Prepare labeled data

Place labeled images in YOLO format:
```
data/annotated/images/   — .jpg files
data/annotated/labels/   — .txt label files
```

### 2. Split dataset

```bash
python backend/scripts/data_checks.py --data ../data/data.yaml
```

### 3. Train

```bash
cd backend
python scripts/train_yolo.py --epochs 60 --imgsz 640 --batch 16
```

### 4. Evaluate

```bash
python scripts/eval_yolo.py --weights runs/detect/koz_alma_train/weights/best.pt
```

### 5. Deploy weights

Copy `best.pt` to `backend/weights/best.pt` and set in `.env`:
```
YOLO_WEIGHTS_PATH=weights/best.pt
```

### 6. Calibrate depth

```bash
python scripts/calibrate_depth.py --images data/calib_images --csv data/calib.csv
```

Result is saved to `backend/app/assets/calibration.json`.

## Configs

- `ml/configs/data.yaml.template` — YOLO dataset config template
- `backend/app/assets/calibration.json` — MiDaS depth calibration
- `backend/app/assets/class_dict.json` — Class name translations (RU/KZ)

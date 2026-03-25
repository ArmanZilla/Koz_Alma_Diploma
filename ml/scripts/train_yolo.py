import argparse
from ultralytics import YOLO

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=str, required=False)
    ap.add_argument("--model", type=str, default="yolov8n.pt")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--imgsz", type=int, default=512)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--project", type=str, default="../runs")
    ap.add_argument("--name", type=str, default="detect")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--checkpoint", type=str, default="")
    args = ap.parse_args()

    if args.resume:
        if not args.checkpoint:
            raise ValueError("For resume mode, provide --checkpoint path to last.pt")
        model = YOLO(args.checkpoint)
        model.train(resume=True)
    else:
        if not args.data:
            raise ValueError("For new training, provide --data path")
        model = YOLO(args.model)
        model.train(
            data=args.data,
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            project=args.project,
            name=args.name,
            save=True,
            save_period=1,
            exist_ok=True,
            workers=2,
        )

if __name__ == "__main__":
    main()
# Pill detector (third party, not used in the demo)

`fetch_pill_model.sh` downloads `pill-yolov8s.pt` (22.5 MB) and checks its SHA-256.

| | |
|---|---|
| Source | [thulasi-bikku/YOLO11-Based-Pill-Recognition-OCR-Classification-System](https://github.com/thulasi-bikku/YOLO11-Based-Pill-Recognition-OCR-Classification-System), commit `8b4988cf`, `models/best.pt` |
| Model | YOLOv8s, one class: `pill` |
| Trained on | the upstream author's Kaggle/Roboflow "Pill Detection PoC" set (Aug 2025) |
| Reported accuracy | mAP50 0.992 on that set's own validation split; not measured on our camera or black mat |
| Licence | none published upstream, so the weights are linked, not committed |

## Why it is not in the demo

The `viam-labs:YOLOv8` module is a 2.9 GB package with bundled CUDA libraries. On the Pi 5 (4 GB) it
downloaded, then failed on every start while unpacking them, and the sync restarted viam-server and took the
arm module down with it (24 Oct). The filmed demo uses the colour detector already on the robot.

## Running it

Off the robot only, for example on a laptop over saved `follower-cam` frames:

```
./models/fetch_pill_model.sh
pip install ultralytics   # in a separate venv; not a project dependency
yolo predict model=models/pill-yolov8s.pt source=<frames dir>
```

Found by Sammy Suliman.

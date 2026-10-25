# Module cloud-pill-vision

This module provides a Viam Vision service that captures frames from a
configured camera, sends them to the DoseDay detector on a Brev GPU, and
returns a bounding box only when exactly one pill matches the selected primary
color and shape.

## Model

- [`doseday:cloud-pill-vision:cloud-pill-detector`](doseday_cloud-pill-vision_cloud-pill-detector.md)

## Local test

```bash
./setup.sh
venv/bin/python -m unittest discover -s tests -v
```

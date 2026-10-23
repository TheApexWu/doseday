# Doseday

A robot arm that sorts single pills from a matte black mat into a 7-day organizer and logs each placement.

The demo uses candy or vitamins only. Nothing in this repository is medical advice, and the code is not validated for handling medication.

## Setup

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -B -m pytest -q
```

`poses.json`, `calib.json` and `pills.json` are generated on site and are ignored by git. Do not commit them.

## Status

Repository skeleton and hygiene checks. Vision, scheduling and the arm layer are added in later stages.

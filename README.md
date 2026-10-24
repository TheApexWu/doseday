# Doseday

A robot arm that sorts single pills from a matte black mat into a 7-day organizer and logs each placement.

The demo uses candy or vitamins only. Nothing in this repository is medical advice, and the code is not validated
for handling medication.

Built at the Spooky Civic Hackathon (NYC, 23-24 Oct 2026), Team 02: a medicine sorter for low-vision patients.

## Status (24 Oct)

| | State |
|---|---|
| Lid closing (`box.py stroke <day>`) | runs on the arm; Tuesday and Wednesday latch, Thursday and Friday spring back half-open |
| Box registration (`box.py mark mon/fri`, `fit`) | two claw touches locate the organizer; every lid and drop position follows from them |
| Arm tools (`armctl.py`) | status, hand-guided mode, teleop, align, teach and replay named poses |
| Recordings ([`runs/`](runs/)) | 8 day-1 sessions (teleop picks, lid closing, hand demos), labelled in `runs/DATASET.md` |
| Autonomous pick and drop | written (branch `alex/trial-pick-drop`), not yet run on the arm |
| Pill detection | colour detector on the robot; a YOLOv8s pill model is linked in [`models/`](models/) but runs off the robot only |

Day-1 measurements and open issues: [`docs/DAY1-FINDINGS.md`](docs/DAY1-FINDINGS.md). Rebuilding the table: [`docs/VENUE-SETUP.md`](docs/VENUE-SETUP.md).

## What it does

1. Enroll one example of each pill type (closed set, up to 5 types).
2. Photograph the mat, find each pill, and classify it. Unknown pills go to a reject bin.
3. Turn the wrist to the pill's long axis, pick, and drop it through a funnel into its day slot.
4. Log each placement, and ask a caretaker to approve the finished organizer before release.

The arm is an SO-101 under Viam. The full sort loop in `demo.py` has not run on the arm yet; today's hardware
moves go through `armctl.py` and `box.py`.

## Setup

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -B -m pytest -q
```

Offline runs need no arm and no Viam SDK. See `docs/ONBOARDING.md`.

## Vision service

`demo-anything-detector` is Viam's built-in `color_detector` on `follower-cam`. It boxes orange regions
(`#FFA500`) and labels them `orange-object`. It is not connected to arm planning or motion. In the Viam app,
open **CONTROL**, select `demo-anything-detector`, and choose `follower-cam` to see the overlay.

To verify the same service from the SDK without moving the arm:

```
PILL_CAMERA=follower-cam python vision_probe.py
```

The command uses the same `VIAM_ADDRESS`, `VIAM_API_KEY_ID`, and `VIAM_API_KEY` environment variables as
`arm.py`. Override the service name with `PILL_VISION_SERVICE`.

## Camera settings at boot

The icSpring camera defaults to automatic exposure, which can lift a black mat to gray. On the robot, install
the supplied systemd service to apply an initial manual baseline at every boot:

```
sudo ./scripts/install_camera_settings_service.sh
```

Watch `follower-cam` in the Viam Control tab, then edit the defaults in `scripts/apply_camera_settings.sh` if the
lighting requires a different exposure. Reinstall and apply changes immediately with:

```
sudo ./scripts/install_camera_settings_service.sh
```

The defaults select 60 Hz anti-flicker. Persistent site overrides can be placed in
`/etc/default/doseday-camera-settings`, for example `CAMERA_EXPOSURE=80` or
`CAMERA_POWER_LINE_FREQUENCY=1` for a 50 Hz location. The other settings can also be overridden with the
environment variables declared at the top of the script.

## Docs

| File | Read it for |
|---|---|
| `docs/ONBOARDING.md` | setup, repo tour, first hour on the arm |
| `CONTROL.md` | control logic, safety gates, fallback plans |
| `docs/GOVERNANCE.md` | caretaker approval, family and SMS notices, what pauses the arm |
| `TESTS.md` | the numbered hardware tests (T-1 to T8) |
| `AGENTS.md` | rules for changing the code |
| `docs/TEAMWORK.md` | branches, merge rules, timeline |

## Secrets and site data

Credentials come from the environment only. `poses.json`, `calib.json`, `pills.json` and `.env*` are site data
and are gitignored. Do not commit them.

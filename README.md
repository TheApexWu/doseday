# Doseday

A robot arm that sorts single pills from a matte black mat into a 7-day organizer and logs each placement.

The demo uses candy or vitamins only. Nothing in this repository is medical advice, and the code is not validated
for handling medication.

## What it does

1. Enroll one example of each pill type (closed set, up to 5 types).
2. Photograph the mat, find each pill, and classify it. Unknown pills go to a reject bin.
3. Turn the wrist to the pill's long axis, pick, and drop it through a funnel into its day slot.
4. Log each placement, and ask a caretaker to approve the finished organizer before release.

The arm is an SO-101 under Viam. The motion and gripper calls are stubs until the SO-101 port lands,
so the code does not move hardware yet.

## Setup

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -B -m pytest -q
```

Offline runs need no arm and no Viam SDK. See `docs/ONBOARDING.md`.

## Portal vision smoke test

The optional `demo-anything-detector` Viam vision service is a portal-only smoke test. It returns one
`demo-object` box around the camera frame and is not connected to arm planning or motion. In the Viam app,
open **CONTROL**, select `demo-anything-detector`, and choose `follower-cam` to see the overlay.

To verify the same service from the SDK without moving the arm:

```
PILL_CAMERA=follower-cam python vision_probe.py
```

The command uses the same `VIAM_ADDRESS`, `VIAM_API_KEY_ID`, and `VIAM_API_KEY` environment variables as
`arm.py`. Override the service name with `PILL_VISION_SERVICE`.

## Local pill-selection demo

Before connecting an arm, prompt for a pill's primary color and shape, launch the local recognition UI, and
draw boxes only around matching detections:

```
python main.py --local-demo
```

Choose an image in the browser page that opens. This mode does not connect to Viam or move hardware. Press
`Ctrl+C` in the terminal to stop the local server. It expects the pill-recognition repository to be checked out
beside this repository.

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
| `TESTS.md` | the numbered hardware tests (T-1 to T8) |
| `AGENTS.md` | rules for changing the code |
| `docs/TEAMWORK.md` | branches, merge rules, timeline |

## Secrets and site data

Credentials come from the environment only. `poses.json`, `calib.json`, `pills.json` and `.env*` are site data
and are gitignored. Do not commit them.

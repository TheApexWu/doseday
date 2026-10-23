# Onboarding: Doseday

Tags: **verified** = checked against the repo or the Viam docs this session; **inferred** = read off the code; **recalled** = from notes, check on the day.

## 1. The pitch

A caregiver enrolls one example of each pill type. For the venue, use candy or vitamins only. The arm photographs a
matte black mat, finds each pill, turns the wrist to match its long axis, picks it, and drops it through a funnel
into the right day slot of a 7-day organizer. Anything it cannot classify goes to a reject bin, never a slot.
Every placement is logged with its type, slot and yaw.

The approval loop sends a photo to the caretaker over Telegram and waits for Approve or Flag. A timeout means not
released. Approval is a logged decision, not a physical lock. Say "sorts what a caregiver enrolled," not "identifies
pills." Do not claim medical accuracy.

## 2. Repo tour

| File | What it does |
|---|---|
| `capture.py` | Saves labelled frames with a camera sidecar. Downstream steps refuse phone photos. |
| `camera.py` | Viam camera, webcam, or a folder of frames. |
| `provenance.py` | Refuses images without a sidecar, and refuses runs on a different camera than enrollment. |
| `vision.py` | Threshold per mat half, contours, long axis, merged-blob flag. |
| `calib.py` | Tags to homography, touch-off to robot mm. Refuses residuals over its limit. |
| `pills.py` | Closed-set nearest neighbour, or reject when unsure. |
| `inventory.py` | Week schedule plus an append-only placement log. Replays stock on reload. |
| `demo.py` | The loop and every no-arm command (`run`, `enroll`, `loo`, `calibrate`, `assist`, `crosshair`). |
| `arm.py` | Arm wrapper. Check, then plan-only, then move, then log. Hardware calls are stubs until the SO-101 port. |
| `trust.py` | Approval channel. Dry-run by default; Telegram when a token is set. |
| `config.py` | Names and paths, with environment overrides for the site. |
| `schedule.json` | Sample week: six slots, 9 pills, candy stock. |
| `tests/` | Offline tests on synthetic images. `test_repo_hygiene.py` checks tracked files. |

## 3. Tonight, no arm (laptop webcam)

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -B -m pytest -q
python capture.py oval -n 10          # webcam:0; press Enter before each shot
python capture.py capsule -n 10
python demo.py enroll oval --dir data/oval
python demo.py enroll capsule --dir data/capsule
python demo.py loo
python demo.py assist --source webcam:0
```

`assist` opens a window: `q` quits, `s` saves a frame. Add `--headless` to print instead. Do not run `arm.py`
without the Viam SDK and live credentials.

**What the offline checks prove:** the logic runs on synthetic images. `loo` needs at least 95% correct and zero wrong.
With 2 types at 10 frames each, that is 20 samples. The result says nothing about real pills.

### Rehearse the loop on a simulated arm

`python demo.py run --sim` runs the live loop (photo, detect, identify, pick, drop, inventory) against a simulated
arm. Options: `--sim-lite` (no grip feedback), `--sim-theta-sign -1` (the wrist turns the wrong way),
`--no-yaw` (rotation off), `--sim-slip 0.3` (random missed grabs).

## 4. First hour on the arm: T-1 to T2

Record numbers, not "pass." Keep the printed lines and `logs/arm-*.jsonl` for every test. The full list is in
TESTS.md.

1. **T-1:** `python arm.py ping`. Note the connect time and the resource names.
2. **T0:** find the gripper percentages that open and close (`set_position`), and write them into
   `GRIPPER_OPEN_PCT` and `GRIPPER_CLOSE_PCT` in `arm.py`. Never call `grab()`.
3. **T1:** copy `poses.example.json` to `poses.json`. Its coordinates are zero placeholders, not measured poses, so
   teach every name before any move. Teach `photo` and `touch-0`, `touch-1`, `touch-2`. Run
   `python demo.py calibrate --touch 0 1 2`, then `python demo.py crosshair --tags 3 4`.
4. **T2:** `python demo.py run --dry-run --image <photo>` in each lighting, and check the `.plan.png`.

**Camera:** set `PILL_CAMERA` and `PILL_CAMERA_SOURCE` (default `color`). The Viam camera helper refuses depth frames.

## 5. Fallback ladder

Plans A to E are in CONTROL.md section 4. Plans C and D are not built. Plan E (`assist`) runs today on a webcam.

Switch rules: decide the plan at each gate from the recorded numbers, not from feel. Anyone calls the physical
stop at any time. If a pill is in the gripper, open it first. Two refused moves in a row mean stop the arm and
switch to plan E.

## 6. Open risks

1. **Picks have no grip check yet.** `holding()` returns `None` until the gripper reports grip state. A missed pick is then confirmed only by the photo check, so expect `grip_verified=None` in the log.
2. **Stop path runs only inside `live()`.** `PillArm.stop()` halts the arm and opens the gripper, and it is called
   when `live()` hits an exception. It has not run on hardware. Use the physical stop first.
3. **Hardware calls are stubs.** Every `_hw_*` method raises `NotImplementedError` until the SO-101 port. Nothing moves yet.
4. **Accuracy is warn-only.** `PillArm.move` prints a warning above `ACCURACY_MM` and the pick continues.
5. **Inventory carries over between live runs.** Only `live()` reloads placements from `logs/inventory.jsonl`.
   Move the log aside before a fresh live run.
6. **Schedule and TESTS disagree.** `schedule.json` has six slots and 9 pills. Check the count against the organizer.
7. **Approval is not a lock.** Demo with candy or vitamins only. Do not send photos of real medication.
8. **Announce is not wired.** `trust.announce` has no caller, so the arm does not speak before a move.
9. **Recorder is not wired.** The video recorder is tested but not called from the loop.

## 7. Unverified

- Viam SDK signatures for the arm, gripper and motion clients on the SO-101 module.
- The camera stream name and the depth MIME type on the kit (`color` is a default, not checked).
- The TCP offset from the wrist.
- The Telegram behaviour in `trust.py` (no live send has been made).

**Skipped:** real-pill identification, live Telegram send, the physical grip test.
**Fragile:** calibration validity at one photo pose, and the Viam cloud link on venue Wi-Fi (inferred).
**Breaks first:** the grip is not verified by the gripper, so a missed pick can record a placement for an empty slot.

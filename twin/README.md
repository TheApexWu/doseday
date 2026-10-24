# Doseday twin (MuJoCo)

A simulated copy of the day 1 table: the SO-101, the 7-day box and a Tums, built from our own recordings. Use it to rehearse a move before spending robot time on it.

It runs offline and never talks to the robot.

## Setup (once)

```bash
bash twin/fetch_model.sh              # the vendor's SO-101 model (Apache-2.0), pinned to one commit
pip install -r twin/requirements.txt  # mujoco 3.17 and friends; the robot code doesn't need them
python twin/decompose.py              # convex pieces for the arm's collision shapes, a few minutes
```

## What's in it, and how far to trust each part

| Part | Source | Checked against |
|---|---|---|
| Arm | Vendor model `so101_new_calib`, the same joint chain Viam uses | `validate.py`: run 04's parked rows land 0.04 mm from the arm's own reported wrist (a 5° joint error shows 13.7 mm) |
| Box position | `box.demo_box()`: the 6.2° skew and the 32.7 mm pitch from Alex's run-04 presses | Same data as `box.py` |
| Lids | Hinge 25 mm behind the registered edge, open lids upright at 88°, lid edge 10 mm ahead of the registered edge | `replay.py calibrate`: 13 of 14 run-05 strokes match (shut where the real lid shut, untouched where it was missed). The hinge is pinned to 22–28 mm; the edge offset (0 to −12) is not, and the photos favour −10 |
| Wrist camera | Placed on the vendor's camera mount, aimed past the jaw tips | Jaw angle, position and pill scale match a run-06 frame by eye |
| Jaw reading | Viam % mapped linearly onto the jaw joint | 8.6 % on a Tums vs 8 % real; empty close 0 % vs 0.4–0.7 % real |

**What it can't tell you:**
- **Whether a grip survives the lift:** the twin's fingers are smooth boxes, and real jaws have teeth.
- **The latch:** whether Thursday or Friday stays shut.
- **Real bounce.**
- **Sag beyond the vendor's servo model.**

## Commands

| Command | What it answers |
|---|---|
| `python twin/validate.py` | Does the simulated arm sit where the real one reported? |
| `python twin/replay.py calibrate` | Which lid geometry reproduces run 05? |
| `python twin/rehearse.py final` | Does the recommended drop land inside, on the trial path and the app path, for both lid sizes, with a bouncy pill too? |
| `python twin/rehearse.py drop-design` | Which release points keep the claw off every lid? |
| `python twin/rehearse.py lifts` | Does the lift drag a closed lid back open? |
| `python twin/grasp_map.py` | From which spots on the paper can the claw take a Tums, and how should it come at it? |
| `python twin/rehearse.py pick-video OUT.mp4 box` | A clip of the pick: hover, grip, carry, release |
| `python twin/rehearse.py stroke-video OUT.mp4 side wed` | A clip of the stroke |

Renders run offscreen (`MUJOCO_GL=cgl` on macOS); heavy runs went to a separate machine.

## Findings, night of 23 Oct

All are from the twin and untested on the robot unless stated.

1. **Release point.**
   - The app's current drop pose (22 mm behind the edge, 30 mm above the lids) misses all five days under both lid sizes. With the lids upright, it releases where the lid stands. The claw comes within 0.6 mm of the lids, or touches them.
   - `trial_pick.py`'s front-edge release depends on where the lid's real edge is:
     - edge where we registered it: the pill lands in front of Friday
     - edge 10 mm further forward: it lands inside, on its rim, but the jaw opening to 91 % hits Saturday's taped lid
2. **Recommended release:**
   - Where: 6 mm behind the registered edge, 22 mm above the lid tops.
   - Claw: lean 6°, heading −88 (the jaws across the box, as in run 06), jaw opened to 30 %.
   - Result: 24/24 inside (trial path into Friday, app path into all five days, both lid sizes, stock and bouncy pill).
   - Closest approach to any part of the box, measured directly: 6.5–8.8 mm.
3. **The app's path from the tray needs a high crossing.**
   - Today's single joint move from `tray_hover` sweeps through the open lids, which stand about 50–60 mm high.
   - Going via the trial's carry point (300, −85, 115), then 30 mm above the day, then down, clears them.
4. **Pickup distance.**
   - Within about 26 cm of the turntable, the claw can come straight down (lean 0, pill 8 mm into the jaw, heading −45 at 61 of 65 spots) and still fits with the pill 6 mm off in any direction. All 65 spots in that band qualify.
   - Beyond 26 cm, a lean is needed and none of the spots tolerate 6 mm.
   - Day 1's tray, 33 cm out, is in the hard band. See `results/grasp_map.png`.
5. **Thursday/Friday reopening (hypothesis).**
   - In the twin, the fixed finger, about 11 mm off the claw axis, can sit under the lid's front lip and pull the lid about 45° open on the lift, without any spring.
   - It happens or not depending on where the lid's real front edge sits, to within a few mm. That fits Tue/Wed latching while Thu/Fri reopen.
   - Test: film Thursday's lift in slow motion.
6. **Grasp point.** The vendor's grasp point sits on the fixed jaw's face, 7.9 mm off `box.py`'s jaw tip. A 19 mm Tums gripped across its face centres about 1.6 mm from `box.py`'s point, so no correction is needed.

## Known artifacts

- `replay.py` drives the arm exactly along a recording, with unlimited force. It can push a lid through its stop, and the lid then flies back open. Use replays for "did the claw reach the lid", not for where the lid ends up. `rehearse.py stroke` drives the arm through the servo model instead.
- Clearances reported during runs come from a probe that skips part pairs whose bounding boxes don't overlap. They are upper bounds; contacts at 0 or below are reliable. True minima for the recommendations were measured with `mj_geomDistance`.

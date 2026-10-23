# Day 1 findings (23 Oct 2026, Civic Hall)

What the arm does now, what we measured, and what is still open. Each claim is marked:
- **verified:** run on `pi-arm1` today
- **inferred:** read off code or data, not tested on the arm

## Working on hardware

- **Lid closing, scripted (verified).** `python box.py stroke wed` swings an open, upright lid shut from behind and presses it.
  - It runs as one continuous ~5 s motion with no stops.
  - The claw is turned so its narrow side faces the neighbouring lids.
  - Tuesday and Wednesday latched.
  - Thursday and Friday close under the claw but spring back half-open after the lift. That held at three press depths and two press points, so the latch, not the motion, is the suspect. A finger test is still owed.
  - Run 05 has every try.
- **The page's "Close lid" button uses that stroke (verified in tests, not yet clicked on the arm).** It applies once a box is registered; Sunday and Saturday are refused.
- **Box registration (inferred: math tested, the two-touch flow not yet run on the arm).**
  1. Touch the claw tip to the Monday and Friday lid edges.
  2. Run `box.py fit`.
  3. Every lid stroke and drop position follows from those two points.
  - The fit refuses marks that are not 4 lids apart or not level.
- **Pick (demonstrated by hand, recorded; not yet run by the robot).**
  - Alex hand-guided a Tums pick from the far mat (jaw tip 346, −108, 11; claw leaning 22°) and a release over Friday's front.
  - Our inverse kinematics reproduces the recorded grasp joints within 0.5° (verified offline).
  - A one-shot trial script (pick at a fixed tray spot, carry high, release) is written but was not run.

## Measured about the arm

All verified unless marked.

- **The reported pose is the wrist-roll joint, not the jaw tips.** The jaw grasp point is about 98 mm further along the claw axis (SO-101 URDF). Our forward kinematics from the arm's model matches its reported poses to a median 0.3 mm.
- **Moves can return before the arm moves:** 2 of 6 timed moves. All code checks the real joint angles before continuing (`wait_arrival`).
- **Wrist camera lag:** 1–2 s behind the arm. Wait 2 s before trusting a frame.
- **Torque cap 35% sags 2–6 mm at full reach.** 60% holds the path.
- **`move_through_joint_positions` blends through sparse waypoints:**
  - it cut 10–15 mm corners and skipped the press
  - waypoints ≤2° apart track within ~6 mm
  - a call always reaches its last point
- **Wrist limit ±95°:** a near-vertical claw high above the box is unreachable. Lift with the claw leaned ~12°.
- **The box sat 6.2° off square:** treating it as square put the Thu/Fri presses 3–6 mm off the lid edge. The two-mark registration measures this.
- **Jaw:** open 30% settles at 27.4%; an empty close reads 0.4–0.7%; holding a Tums read 8%. The 3% "holding" threshold has margin.
- **Servo load in manual mode saturates at the torque limit (30):** useless for sensing contact.

## Data (for Sammy)

- `runs/` holds one folder per recording, each with a README.
  - **01:** teleop candy picks
  - **02:** teleop lid closing
  - **03:** lid opened by tab
  - **04:** hand-guided survey with lid presses
  - **05:** scripted lid-close tries
  - **06:** hand pick-and-place demo (on the labels branch)
- Phase labels, jaw-tip coordinates, a frame index per run and a data card (`runs/DATASET.md`) are on branch `data/labels-1023`. They merge into `dev` once checked.

## Open, in priority order

1. **Pick by the robot.** Run the tray-spot trial, then make it a station pose: `tray_hover`/`tray_down` from the recorded grasp.
2. **Thursday/Friday latch.** Finger-test it. If the latch is worn, demo on Mon–Wed.
3. **Pill identification.** No photos are enrolled yet, so `identify.py` and `--claude` have nothing to compare against. Use `capture.py` with the follower camera.
4. **New venue tomorrow.** See `~/Desktop/Doseday-Venue-Move-Checklist.txt` (Alex's laptop). The biggest risks are the Pi's WiFi and the USB port names.
5. **Retry-grasp bonus** (branch `bonus/retry-grasp`): set `NUDGE_MM = 0` before any hardware run.

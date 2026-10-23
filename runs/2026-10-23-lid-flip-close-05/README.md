# Run 05: scripted lid closing on open lids (box.py)

**When:** 23 Oct 2026, 18:40–18:51 ET.
**Machine:** `pi-arm1`, base clamped.
**Box:** Mon–Fri lids open, standing upright at the hinge; Sun/Sat taped, never touched.
**Recording:** each `teleop-HHMMSS.csv` is `record_teleop.py --no-teleop --follower-only` started with that try. Frames come from `snap.py` at 2/s; only contact sheets are kept.

## What the stroke is

`box.py` plans every pose from the box frame. It uses inverse kinematics on the arm's own kinematic model, which reproduces its reported poses to a median 0.3 mm. Each stroke:

1. A transit pose high in front of the box.
2. Down behind the upright lid.
3. A 30 mm arc about the hinge that swings the lid shut.
4. A press.
5. A lift.

Everything up to the press is one dense continuous trajectory (`move_through_joint_positions`), with torque capped at 600/1000.

## Tries (all Wednesday unless noted)

| Try | Change | Result |
|---|---|---|
| 1 | Waypoint by waypoint, torque 350, hinge assumed 40 mm behind the edge | Stopped at the first arc point. The claw passed 42.6 mm without meeting the lid and sagged 5.6 mm at 350. Lid untouched. |
| 2 | One continuous call, torque 600, hinge 35 mm | The arm blended past sparse waypoints, cutting 10–15 mm corners, and never pressed. Lid untouched. |
| 3 | Path densified to ≤2° steps; the call ends on the press | Followed the plan within ~6 mm; press reached −2.4 mm. Lid closed but did not latch ("not enough push down", Alex). |
| 4 | Jaws turned 90° (heading −87 → +3) so the narrow side faces neighbours; press −9 mm | **Wednesday latched** ("perfect it closed", Alex). |
| 4b | Thu, then Tue | Tue latched. Thu sprang back open. |
| 4c | Mon, Fri | Both pressed to depth. Fri sprang back. Mon not checked. |
| 5 | Box refit 6.2° off square from the run-04 presses; Thu, Fri | Both swung shut (frames 4 and 10 of the sheet) and sprang back open after the lift. |
| 6 | Press −13 mm at 5 mm behind the edge; Thu, Fri | Stalled at −11.3/−11.6 against the lid. Still sprang back. |
| 7 | Press mid-lid (12 mm behind the edge, −11 mm); Thu, Fri | Same. In every after-photo both lids rest at the same half-open angle. |

## Open question

Thursday and Friday close under the claw but do not latch, while Tuesday and Wednesday latch with the same stroke. The motion is not the suspect. A hand test of those two latches (press shut with a finger) separates a worn latch from a stroke problem.

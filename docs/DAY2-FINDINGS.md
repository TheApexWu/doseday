# Day 2 findings (24 Oct 2026, Jay Conference)

What the arm did, which script did it, and what is still open. Successes marked "seen" were confirmed by Alex at the
table; the rest come from the run logs.

## Worked on hardware

| Result | Script | Run folder | Evidence |
|---|---|---|---|
| 3 of 3 tablets picked and dropped, first grab each (red to Sun, peach to Tue, cream to Fri) | `scripts/replay_run.py --picks 4,5,6 --no-lids` | `runs/2026-10-24-robot-run-1558` | jaw 8.9% held on each; filmed |
| Tuesday lid closed | `scripts/stroke_lid.py tue` (box.py stroke as it stood at 15:23) | `runs/2026-10-24-stroke-tue-1523` | seen; camera frame after shows the lid flat |
| Monday lid closed | `scripts/lid_arc.py mon` (hinge arc at 45% force, then full-force press) | `runs/2026-10-24-lid-arc-1630` | seen |
| Wednesday lid closed | `scripts/lid_wed.py --deeper N` (loop N = 1..4, 45 deg/s, full force) | not recorded (recorder off to free the servo bus) | seen; which N is unknown |
| Hover over all 7 pick spots with the wrist held still | `scripts/hover_spots.py` | `runs/2026-10-24-hover-check-05` | each pill in frame |

## Learned from the hand demonstrations

- **Drops** (`scripted-demo-04/labels.json`): enter from the front nearly level, release 36-45 mm up (8-17 above the
  lids), claw 5-13 deg away from the arm, pull straight back.
- **Lids** (`lid-teach-13`, `lid-teach-1608`, `manual-1641-15hz`): arrive vertical behind the lid, catch it low,
  drag it to the front edge with the claw trailing 10-24 deg, fast (peak 80-175 mm/s), each lid in 1.5-2.5 s.
- **Lid midpoints** along the box are measured per lid (`box.LID_Y_24OCT`, stored in box.json as `lid_y`); a
  straight-line fit was 8 mm off at Sunday.
- **Why lids failed:** a push at the hinge has no leverage and slides the whole box; servos push in proportion to how
  far short of the target they are, so a press must aim well below the lid top; a tilted claw slides along the lid.

## Open

- **White arm power:** the servo bus dropped out under load at least ten times (presses, full reach). Every dropout
  could also reset the wrist servo's turn count (wrist read one turn off, e.g. -466.8 for -106.8); only a power cut
  at the arm's own board fixed it. Software (reinitialize, module restart, set_homing) did not.
- **Wrist calibration changed:** `set_homing` at ~14:00 wrote a homing offset of 2047 to the old white arm's wrist.
  Day 1 called the arms pre-calibrated; tell Viam.
- **Arm swapped ~17:00:** a different follower arm is now on `/dev/ttyACM2` with different calibrated ranges
  (`scripts/linear.py` CAL_RAW). Its gripper servo did not answer. Box coordinates were measured with the old arm.
- **Pale-blue tablet** missed at its recorded spot on every robot try.
- **Recording at 15 Hz** competes with motion for the servo bus; record at ~4 Hz (`record_demo.py`) during runs.

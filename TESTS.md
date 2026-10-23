# Falsification checklist (T-1 to T8)

Run in order. Each test can kill a component, and the fallback is on the same line. Write the number, not "pass".

**Every image comes from `python capture.py` with the camera you will run with. No phone photos.** The tools refuse them.

Rehearse the loop with no hardware first: `python demo.py run --sim`. Add `--sim-lite` (no grip feedback),
`--sim-theta-sign -1`, `--no-yaw` or `--sim-slip 0.3` to rehearse each failure.

## T-1 Connect (first 5 minutes at the venue)

- [ ] `python arm.py ping`: connect time, resources. Over 45 s or a hang: switch to a phone hotspot.
- [ ] Note the viam-server and module versions from the app, and `pip show viam-sdk`. Do not upgrade on the day.
- Result: connect ____ s  route ____

## T0 Hardware ID (5 minutes)

- [ ] Confirm the arm model and the gripper component name in the Viam app. Set `PILL_ARM`, `PILL_GRIPPER` if they differ.
- [ ] Find the gripper percentage that opens and the one that closes, with `set_position`. Write them into
      `GRIPPER_OPEN_PCT` and `GRIPPER_CLOSE_PCT` in `arm.py` (both are placeholders until this test).
- [ ] Measure the closed gap with calipers at the closing percentage. The smallest pill must be wider than that gap.
- Result: arm ____ open % ____ closed % ____ closed gap ____ mm

## T1 Calibration

- [ ] `table_z` from a fingertip touch on the mat, not from depth. `python arm.py teach` for `photo`, `touch-0`, `touch-1`, `touch-2`.
- [ ] `python demo.py calibrate --touch 0 1 2`: refuses if the tag or touch residual is over the limit in `calib.py`.
- [ ] `python demo.py crosshair --tags 3 4`: hovers 2 mm over each tag NOT used for the touch-off. Measure the miss
      with a ruler and type it in. The pass limit is `--t1-limit`, default 2.0 mm.
- **Pass:** every miss at or under the limit. Misses: __ __ mm
- Kill: re-touch the tags, or restrict picks to the centre of the frame.

## T2 Detection

- [ ] 20 mixed placebo pills on the matte black mat (white and bright colours; dark pills vanish on black),
      under 3 lighting conditions, one with a lamp off to one side.
      `python demo.py run --dry-run --image <photo>`, then check the `.plan.png`.
- **Pass:** 20 of 20 found and 0 false blobs in all three lightings. Found: __/__/__, false: __/__/__
- Kill: diffuse the lamp, or tune `--delta` on captured photos.

## T3 Orientation

- [ ] 10 elongated pills at protractor-set angles. Compare the detected angle with the true one.
- **Pass:** every error at or under 8 degrees; the round check fires on every disc. Max error ____ deg
- Kill: switch the angle source to the moments-based angle.

## T4 Jaw to theta mapping

- [ ] `python arm.py jaw 0`, `jaw 45`, `jaw 90`. Photograph the jaw line from above each time.
- [ ] Set `THETA_SIGN` and `JAW_AT_THETA0_DEG` in `arm.py` from the photos.
- **Pass:** the jaw line rotates as predicted and the sign is known. Sign ____ offset ____ deg
- Kill: add the measured offset. That is the fix.

## T5 Grip

- [ ] 20 picks of isolated pills, smallest pill first, then a 300 mm move.
- **Pass:** at least 18 of 20 lifted and held. Result __/20
- Kill: foam under the paper and softer fingertips.

## T6 Yaw necessity (negative control for the headline claim)

- [ ] Same 10 elongated pills and positions as T5, with `python demo.py run --no-yaw` (wrist fixed).
- **Pass:** success visibly lower than T5. Write both: yaw on __/10, yaw off __/10.
- If the two are equal, drop "auto edge align" from the claims.

## T7 Drop

- [ ] 20 drops into funnelled slots from saved poses.
- **Pass:** 20 of 20 in the correct slot. Result __/20
- Kill: wider funnel cones.

## T8 End to end

- [ ] 7 pills, 2 types, full week fill, timed. `python demo.py run`. Check `logs/inventory.jsonl` against the organizer.
- **Pass:** 0 wrong-slot placements. Wrong __, seconds per pill __
- Kill: cut the scope to one day column.

## Offline (no hardware)

- [ ] `python -B -m pytest -q` is green. These tests check the logic on synthetic images only. They say nothing about T1 to T8.

## Pill identification (after T1)

- [ ] `python capture.py TYPE -n 10 --source viam --arm-photo-pose` for each type. Move and rotate the pill between shots.
- [ ] `python demo.py enroll TYPE --dir data/TYPE --calib calib.json` for each type.
- [ ] `python demo.py loo --calib calib.json`. Pass: at least 95% correct and 0 wrong (errors must land in reject).
- [ ] Fail: swap in types that differ more, or change the colour. Do not tune thresholds on site.
- Result: correct ____ / ____  wrong ____  reject ____

# Teach 10 (24 Oct, Jay Conference)

Hand-guided run of the white arm (torque off), 178 s, 727 samples at about 4 Hz with one wrist-camera frame per
sample. One connection gap, 125.8-132.4 s, in the middle of the lid presses. `script.json` is the cleaned run;
`labels.json` drives `scripts/replay_run.py`.

## What happened

Seven pills are picked straight down from the same mat spots as demo-04 and pushed into their day from the front.
The closed claw then presses each lid at its front edge (pass 1) and makes a fast back-and-forth sweep along the
lid fronts (pass 2), then rests.

| # | Pill | Grab t | Pick tip (mm) | Jaw held | Release t | Drop tip (mm) | Day | Seen in |
|---|---|---|---|---|---|---|---|---|
| 1 | white capsule | 27.7 | (139, 105, 0) | 4.5 | 32.2 | (201, 55, 30) | Mon | frame 166 |
| 2 | white capsule | 42.5 | (78, -143, -1) | 4.2 | 46.4 | (195, -21, 40) | Wed | frames 237-244 |
| 3 | white capsule | 54.7 | (293, -103, -13) | 4.0 | 62.7 | (183, -91, 30) | Fri | frames 331-332 |
| 4 | pale-blue tablet | 73.9 | (229, 193, -8) | 10.7 | 82.9 | (178, -42, 40) | Thu | frame 372 (at the mouth) |
| 5 | red tablet | 88.9 | (270, 119, -14) | 10.9 | 95.1 | (199, 90, 28) | Sun | frame 394 |
| 6 | cream tablet | 98.3 | (278, -60, -12) | 10.6 | 105.4 | (210, 12, 31) | Tue | frame 431 |
| 7 | peach tablet | 112.3 | (207, -201, -12) | 10.5 | 116.9 | (184, -121, 28) | Sat | frame 490 |

Every day gets exactly one pill. All seven drops land within 10 mm of demo-04's box fit (Sunday y = 80.8, pitch
-32.6). Drops sit at tip z 28-40 and x 178-210 with the claw at heading -108 to -116.

- Pick 1: the hand first closed on nothing at 21.9 s (jaw 0%), reopened and regripped at 27.7 s.
- Pick 7: first close at 109.9 s (8.9%), reopened and regripped 9 mm lower at 112.3 s.
- Drops 1-4 had no jaw opening: the pill stayed in the compartment as the claw pulled back. A replay should open
  the jaw at the drop pose anyway.

## Lids

- Pass 1, 122.8-151.4 s: one press per lid. The claw lands behind the latch (x 231-257) and slides toward the arm
  to x 192-215 at tip z 16-20, then dwells. The press points are at y 58 (Mon, inferred from y), 11 (Tue), -16 (Wed),
  -46 (Thu), -74 (Fri) and -109 (Sat). The Sunday centre (y 81) is never visited. Whatever happened during
  the 125.8-132.4 s data gap is unrecorded.
- Pass 2, 155.6-160.6 s: a continuous sweep at x 184-214, z 16-30, with strokes y 60 to -129, back to 68, and
  again to -109.

## Not replayable as recorded (planner limits = calibrated servo ranges intersected with the kinematics file)

- Picks 1-3 are refused by `replay_run.py` because the grab pose is out of limits. Pick 1: elbow 42.0 (+7.0 over 35)
  and wrist -162.3 (5.1 past -157.2). Pick 2: wrist -168.1 (+10.9). Pick 3: wrist -170.6 (+13.4). Turning the wrist
  180 deg fixes the wrist on picks 2-3, because the jaws grip the same way. A joint grid search reaches pick 1's tip
  straight down with elbow 32 (shoulder 4, wrist flex 67), so pick 1 needs IK rather than joint replay.
- Hand drops used elbow 45-63 deg. The elbow at release is 47 / 57 / 63 / 45 / 35 / 47 / 33 for drops 1-7, so drops
  1, 2, 3, 4 and 6 are 10-28 deg past the elbow stop. IK reaches the same drop tips with elbow 19-33. Drop 4 at
  x 178 does not solve, but it does at x 190.
- During carries the wrist flex reaches 104.5 (+2.2 over the servo range, +9.5 over the planner's 95).
- Pick 6's carry needs a 12.1 deg clamp and is refused (the cap is 12). Picks 4, 5 and 7 replay with 9.6-10.2 deg
  clamps, and the clamp on pick 4 moves its drop pose itself.
- The 151.4-155.6 s lift between the lid passes reaches shoulder -93.3 (29 past -64) and elbow 70.5 (35.5 past 35).
  The rest pose (shoulder -99.7, elbow 75) is also out. Use the taught home.

## Versus demo-04

- Pick spots are the same within 5-19 mm. The red tablet moved most: (285, 108) to (270, 119).
- Order: picks 6 and 7 are swapped (cream then peach). Days are Mon, Wed, Fri, Thu, Sun, Tue, Sat, so Saturday now
  gets a pill and Friday gets one, not two.
- Drops are lower (z 28-40 vs 36-45), and capsules are released by retracting with no jaw opening.
- Lids: demo-04 had a single closed-jaw sweep from Sunday to Saturday. This run has a press per lid plus a
  three-stroke sweep.

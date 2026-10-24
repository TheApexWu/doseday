# Scripted demo 04 (24 Oct, Jay Conference)

Hand-guided run of the white arm (torque off), 176 s, 702 samples at about 4 Hz with one wrist-camera frame per
sample and no connection gaps. Pills were placed at fixed spots on the mat so the run can be repeated.
`script.json` is the cleaned version of the run that a replay should follow.

## What happened

The box starts with every lid open. Seven pills are picked straight down from the mat and dropped into their day,
one at a time; then the closed claw sweeps along the lids from Sunday to Saturday and the arm returns home.

| # | Pill | Pick (claw tip, mm) | Drop | Drop offset from day centre |
|---|---|---|---|---|
| 1 | white capsule | (136, 104) | Mon | +1 mm |
| 2 | white capsule | (73, -139) | Wed | -11 mm |
| 3 | white capsule | (301, -112) | Fri | +10 mm |
| 4 | pale-blue tablet | (224, 185) | Thu | +1 mm |
| 5 | red tablet | (285, 108) | Sun | -5 mm |
| 6 | peach tablet | (212, -195) | Tue | +12 mm |
| 7 | cream tablet | (281, -54) | Fri | -5 mm |

Saturday gets nothing; Friday gets two pills. Lid sweep: 112-149 s, jaw closed. Home: 150 s.

## How the days were assigned

- Mon, Wed, Thu, Sun and Tue were seen in the camera with the pill inside (frames 58, 116, 346, 272, 340).
- The five seen drops fit a straight line with a 32.6 mm pitch along y (the lids are 32.7 mm apart), Sunday's
  centre at y = 80.8. Drops 3 and 7 were assigned from that fit; the camera agrees for drop 3 (frame 185).
- Tip = wrist + 98 mm along the claw axis. The claw pointed straight down (z component -0.98 to -1.00) at every
  drop. Pick tips read 2-17 mm below z = 0, so the table sits slightly below the arm's z = 0.

## Known issue in this recording

The white wrist-roll reading is offset (about -460 deg instead of a value inside -157..163). Do not replay raw
wrist values until the wrist is re-zeroed and the offset is measured.

# Run 02: closing the organizer lids by teleop

**When:** 23 Oct 2026, 14:07:48 ET, 130 s recorded.
**Machine:** `pi-arm1`, arm base not yet clamped.
**Task:** an operator on the leader arm presses each open lid of a 7-day organizer (Sun–Sat) shut, with the jaw closed (0.3% the whole run).
**Setup before start:** `armctl.py align` brought the gap from 7.8° to 0.2°, then `armctl.py teleop`.

## Files

| File | What |
|---|---|
| `motion.csv` | ~6.3 rows/s: leader `L0-L4` and follower `F0-F4` joints, tip `x y z` (mm, follower base frame), orientation, `jaw_pct`, `load0-4` (blank: not in manual mode) |
| `frames/` | wrist camera at 1 frame/s, named by seconds since 14:07:48 |
| `frames_fast/` | wrist camera at ~3 frames/s, named by seconds since **14:08:15** (add 27 s to align with `motion.csv`) |

## Results (measured from motion.csv unless marked)

- **Presses:** 14 dips of ≥ 5 mm in tip z. 12 bottom out at z 96–112 mm: **median 108.8, interquartile range 105.5–110.0**. Two shallow ones (146.6, 150.0 mm at 98–101 s) look like touches on a raised lid edge (inferred).
- **Approach:** from about 140–175 mm, so roughly 30–60 mm of descent per press.
- **Lids:** Sun to Sat appear shut after the presses (read from frames at 24/28, 43/47, 63/67 s; inferred, no lid sensor).
- **Organizer pose in the arm frame:**
  - the press points lie along a line about **20° off square** to the arm (fit angle −110° vs the x axis; 90° would be square)
  - 198 mm long, 13.5 mm scatter across the line
  - radial distance 147–252 mm, so the Sun end sits at the edge of the straight-down reach (~250 mm)
- **Closing vs opening:** the lid-open run (13:4x, not published) bottomed out at z 105–120. A scripted close should press to about 107 mm and stop.

## Next

1. Square the organizer to the arm and move it about 30 mm closer. Then every lid is `start + k × pitch` along one axis, all within reach.
2. Measure the lid pitch with a ruler; the presses suggest about 33 mm (198 mm / 6, inferred).
3. Clamp the base, teach `lid_sun` and the pitch, script `close_lids`: hover 30 mm above, press to 107 mm, lift.

# Lid buttons pressed by hand, manual mode

**When:** 23 Oct 2026, about 13:44 ET, 153 s.
**Machine:** `pi-arm1`, arm base not clamped.
**Mode:** follower in manual mode (pushed by hand), recorded with `record_teleop.py --no-teleop`. No camera frames, and no load columns (load logging was added afterwards).
**Task:** press each of the 7 lid buttons of the organizer with the follower's jaw tip.

## Press bottoms (measured from `motion.csv`)

| Button | Tip x, y (mm) | Start of push z | Bottom z | Travel |
|---|---|---|---|---|
| 1 | 144, +108 | 122.0 | 119.9 | 2 mm |
| 2 | 135, +84 | 121.6 | 116.8 | 5 mm |
| 3 | 137, +56 | 120.6 | 115.4 | 5 mm |
| 4 | 138, +23 | 115.4 | 111.7 | 4 mm |
| 5 | 137, +11 | 121.7 | 111.8 | 10 mm |
| 6 | 135, −23 | 119.2 | 110.0 | 9 mm |
| 7 | 127, −47 | 114.7 | 105.4 | 9 mm |

"Start of push" is the highest point in the 3 s before each dip. True contact lies between that and the bottom: the arm has no touch sensing.

## Takeaways

- **Push travel:** 2–10 mm past the start of the push, typically 5–9 mm. Pushing further nearly snapped a lid.
- **Box placement:** bottoms drop about 14 mm across the box and x drifts 144 → 127, so the box sat skewed and maybe tilted relative to the arm. Teach each lid's height, or square and level the box.
- **Button spacing** from hand placement is noisy. Tape measure: 32.7 mm pitch, 229 mm length (23 Oct, photo).

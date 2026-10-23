# Run 04: hand-guided survey of the workspace, follower in manual mode

**When:** 23 Oct 2026, 18:15:06 ET, 156 s.
**Machine:** `pi-arm1`; follower in manual mode (torque limit 30), leader limp and not used.
**Recording:** `record_teleop.py 600 --no-teleop --follower-only` (joints, tip pose, jaw, servo load at ~7/s) and wrist frames at 1/s.

## What the operator showed the camera (from the frames)

- **The whole week in one view:** Sunday to Saturday visible at about 84 s. Saved as pose `view_week` (tip x 252, y −4, z 176, camera tilted).
- **Box from above:** Sunday to Friday at 120–156 s. Saved as `view_box_high` (x 185, y 44, z 215).
- **Loose pills beyond the box:** peach, white, red and mint, at 5 s, 55 s and 69 s. The lowest point, z 104 at x 307 and y −101, sat right over a pill. Saved as `view_far_pills`. It is reachable only with the claw tilted, not pointing straight down.
- **All seven lids were closed during this session.**

## Measured

- **Tip range:** x 183–308, y −119–84, z 103–271 mm. The jaw stayed closed (0.4–0.7%).
- **Servo load is saturated:** every joint read |load| ≤ 30, the same as the manual-mode torque limit, so in this mode load cannot show contact or force. Contact sensing needs a higher limit or another signal.

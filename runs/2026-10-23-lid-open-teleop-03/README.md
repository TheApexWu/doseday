# Run 03: teleop session with the organizer, one lid opened by its latch tab

**When:** 23 Oct 2026, 16:45:00 ET, 300 s recorded.
**Machine:** `pi-arm1`, leader on `/dev/ttyACM2` after a USB re-plug (the config said `ttyACM0`, which no longer existed).
**Recording:** `record_teleop.py 300 --no-teleop --follower-only` (follower only: teleop already reads the leader 100 times a second on the same serial line, and the extra reads lined up with this afternoon's timeouts). Wrist camera at 2 frames/s; `frames/` keeps every second one (1 per second), named by seconds since 16:45:00 (about 1 s ahead of `motion.csv`'s `t`).

## What happened (from motion.csv and the frames)

- **Tuesday's lid opened by a fingertip press** on its latch tab's black dot, between about 84 and 88 s: shut at 84 s, compartment showing at 88 s, lid flipped back by 91 s. The jaw was closed (0.3%) as the fingertip. Tip at x 255–264, y 43–64 mm, pressed to z 87–91 mm from about z 100–114.
- Monday holds a pill under its closed lid. A red pill sits near the box at 37–41 s.
- At 137–143 s someone put a marker between the jaws; the jaw read 4.5%, so a held object shows up in the jaw reading.
- 47 dips of 8 mm or more in tip z over the session; tip ranged x 25–344, y −123–198, z 80–389 mm.

## Decisions taken from it

- **The tab press is too forceful to risk in a demo** (Alex, 23 Oct). Lids start open; `actions.Station` refuses `open` unless `allow_open=True`. Closing stays: run 02 showed it's easy.
- **The box sat too far out:** Tuesday's tab at about 265 mm from the base axis, beyond the ~250 mm comfortable straight-down reach. Move it about 2.5–3 in toward the arm before teaching drop poses.

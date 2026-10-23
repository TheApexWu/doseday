# Arm exploration sessions, 23 Oct evening (17:51–18:17 ET)

Three recordings from before run 04, plus the photos and JSON written while exploring the workspace with the white (follower) arm.
- **Motion:** `motion.csv` follows the same format as the other runs. `x y z` is the wrist-roll joint; `box.Kinematics().tip(joints)` gives the jaw tips.
- **Frames:** every second wrist-camera frame is kept. Names are seconds since the camera started.
- **No labels yet.** Statements below are either **measured** from the CSV or **recalled** from the session.

| Folder | Start | Length | What (measured) | What (recalled) |
|---|---|---|---|---|
| `a-175149` | 17:51:49 | 600 s | Follower in auto mode the whole time (no load columns); moving 6% of the time. Jaw-tip x 176–235, y −104–115, z 47–124. Leader also recorded. | Claude driving the follower to explore the workspace and camera views. The pillbox was shifted about 2 in further from the arm mid-session. The Tuesday lid was closed by hand while the box was moved (frames ~270–330 s). |
| `b-180722` | 18:07:22 | 173 s | Mostly manual mode (load columns filled); nearly still at jaw tip ~(218, 32, 110). | Purpose unclear; treat as idle. Frames start 1 s before the CSV. |
| `c-181020` | 18:10:20 | 420 s | Mixed auto/manual (load in 1210 of 2951 rows); moving 26%. Jaw-tip x 191–349, y −123–88, z 14–200. | Likely contains the straight-line test (`scratch/line/line.json`, 26 waypoints at wrist z ~198, y +60 → −60) and exploration views (inferred from the ranges). |

## `scratch/`

Outputs written during exploration (photos at known poses and their JSON):
- `explore*/`
- `views/` (camera tilt tests)
- `drops/`
- `health/health.json`
- `line/line.json`: per waypoint: commanded y, reached xyz, joints, max joint jump.

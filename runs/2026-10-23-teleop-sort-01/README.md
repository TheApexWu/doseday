# Run 01: teleop colour sort, bare gripper

**When:** 23 Oct 2026, 12:21:03–12:24:03 ET (180 s recorded).
**Where:** Civic Hall Rm 615, machine `pi-arm1`.
**Who:** two operators taking turns on the leader arm (teleop). Code did not drive the arm.
**Task:** pick M&Ms (blue, red, yellow, dark brown) off white paper and place them in groups by colour.
**Gripper:** stock SO-101 jaws, no padding. **This is the baseline for the rubber-grip run.**

## Files

| File | What |
|---|---|
| `motion.csv` | ~8.7 rows/s from `record_teleop.py --no-teleop`: leader joints `L0-L4`, follower joints `F0-F4` (degrees), follower tip `x y z` (mm, world = follower base), orientation `o_x o_y o_z theta`, follower jaw `jaw_pct` |
| `frames/` | wrist camera (`follower-cam`), 1 frame/s, named by seconds since start, aligned to `motion.csv` `t` |
| `per_second.csv` | written by `analyze_run.py`: jaw, camera hold score, tip pose for each frame |

Reproduce: `python analyze_run.py runs/2026-10-23-teleop-sort-01`

## Results

| Measure | Value | How |
|---|---|---|
| Transports pick → drop area | 7 | `analyze_run.py` (tip x ≤ 200 mm, then ≥ 250 mm) |
| Transports carrying candy | **6 of 7** | camera hold score > 0.15 during the move; the empty one is at 103 s (jaw closed to 1.4%, score 0.00) |
| Closures at the pick spot with nothing between the jaws | 7 (49, 52, 78, 85, 90, 97, 102 s) | read by hand from `per_second.csv`; 1 Hz frames, so a quick regrab can be missed |
| First-try grab rate | about **6 / 13 closures ≈ 46%** | from the two rows above; approximate |
| Jaw opening used | 0.7–18.2% | the leader trigger never opened the follower past ~18% |
| Jaw reading while holding | 2.6–9.8% | a dark M&M held at 2.6%, close to an empty close (0.7–2.0%) |
| Tip height at pick | z 91–104 mm | |
| Pick area / drop area | x 104–200 mm / x 258–289 mm | |
| Teleop tracking | follower within 0.3° of leader at rest | `lag` column of the live print |

## What we learned

1. **The jaw reading alone can't confirm a grip.** A held dark M&M (2.6%) reads nearly the same as an empty close (1.6–2.0%). The **wrist camera can**: empty jaws score 0.00 (3/3 idle frames), held candy 0.21–0.41.
2. **Most failures happen at the grab, not in transit.** Once the camera saw candy between the jaws, it reached the drop area 6 of 6 times. The one empty transport closed on nothing at the pick.
3. **Small, round, hard candy rolls out of a hard plastic jaw with one moving side.** Hence the next change.

## Not recorded

- About 3 minutes of teleop before 12:21 and after 12:24 (the loop ran 36,607 cycles ≈ 6 min in total).
- Failed attempts in those windows are not in this data.

## Next run (02): one change only

Rubber or grip tape on both jaw tips. Same candy, same paper, same pick and drop areas, same recording (`record_teleop.py 180 --no-teleop` + `snap.py 180`). Compare carried transports and misses per closure with this run.

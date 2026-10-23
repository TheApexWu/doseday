# Run 01 analysis

Offline, from `motion.csv` and `frames/`. Per-attempt features: `python runs/2026-10-23-teleop-sort-01/attempts.py`. **measured** = computed from the recording; **inferred** = a judgement on top of it.

## Grasp attempts

- 17 attempts: 6 hit, 11 miss, **35% first try**. Hit/miss labels are inferred from the frames; the features are measured. The README's ~46% came from the 1 Hz table, which misses quick regrabs.
- **No feature separates hits from misses at this sample size** (all permutation p ≥ 0.12):
  - lowest tip z: hits 94.7 mm, misses 97.0 mm (p 0.14)
  - jaw opening before close: 13.8% vs 13.0% (p 0.59)
  - candy offset toward the moving jaw: 340 vs 349 px (p 0.34)
- Every hit approached slowly: under 12 mm/s in xy and 19 mm/s downward. The two fastest approaches both missed. n = 2, so a lead, not a result.
- 7 of 11 misses stopped closing at 5–7.5%, meaning the candy was pinched and then escaped. Empty full closes end at 0.7–1.8%.

## Camera hold check (measured)

- **Too close to the table it gives false positives.** With empty jaws 20–38 mm above the paper, candy lying underneath scored 0.22–0.31, above the 0.15 threshold.
- **From 60 mm up it separates cleanly:** empty frames scored ≤ 0.12 (n = 6), held candy ≥ 0.20 (n = 4). `pick.py` checks only after lifting at least 55 mm.
- The margin is thin (0.12 vs 0.20, n = 10). Re-measure after pads change what sits in the jaw gap.

## Kinematics (model)

- **Forward-kinematics check:** the model (`so101.json`) matches the recorded tip pose to a median of 0.06 mm, against 158 mm for random joint vectors.
- **Slowest joints:**
  - descent and lift are limited by wrist pitch (23° of travel)
  - transfer is limited by the elbow (77°)
- **Reach:**
  - the pick area is reachable pointing straight down
  - the drop corner beyond x 280 mm, y 100 mm is not
- **Descent speed:** below about 27°/s the module's 12°/s per-joint floor breaks the coordinated descent: about 29 mm off vertical at 12°/s, 2.4 mm at ≥ 30°/s. So `pick.py` descends at 30°/s.
- **Cycle-time lower bounds** (excluding per-command and camera latency, which are unmeasured):

| Speed, acceleration | Jaw opening | Cycle |
|---|---|---|
| 50°/s, 500°/s² | 18% | 5.7 s |
| 50°/s, 500°/s² | 95% | 10.0 s |
| 80°/s, 500°/s² | 18% | 4.4 s |

## Next session

1. Thin (1–2 mm) high-friction pads flush with both jaw tips. Then re-measure the empty and holding jaw readings.
2. Teach `pick_down` with the fixed jaw's inner face about 1 mm from the candy, so the moving jaw pushes it against a wall. The worst-offset miss escaped sideways.
3. A dimple tray: about 15 mm wide and 3–4 mm deep, one candy per dimple. At least 5 of 17 attempts had candies touching.
4. Teach the hover ≥ 60 mm above the pick. Run `pick.py --trials 10` supervised at the default speed before trying 80°/s.

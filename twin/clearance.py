"""True minimum gaps between the claw and the box along the recommended moves, measured pair by pair with
mj_geomDistance. The run-time probe in rehearse.py only bounds gaps from above (it skips pairs whose bounding
boxes don't overlap), so the numbers quoted in README.md come from here.

    python twin/clearance.py
"""
import sys
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import box  # noqa: E402
from twin import rehearse as R  # noqa: E402
from twin.scene import Twin  # noqa: E402

DISTAL = ("lower_arm", "wrist", "gripper", "wrist_camera_mount", "wrist_camera", "moving_jaw_so101_v1")


def nearest(twin: Twin, arm, boxg) -> tuple[float, str]:
    ft = np.zeros(6)
    return min((mujoco.mj_geomDistance(twin.model, twin.data, a, b, 0.05, ft) * 1000, twin.model.geom(b).name)
               for a in arm for b in boxg)


def main():
    behind, above, lean, heading = R.RECOMMENDED_DROP
    for front in (0.0, -10.0):
        t = Twin(front=front)
        m = t.model
        distal = {m.body(n).id for n in DISTAL}
        arm = [g for g in range(m.ngeom) if m.geom_bodyid[g] in distal and m.geom_contype[g] in (1, 2)]
        boxg = [g for g in range(m.ngeom) if (m.geom(g).name or "").split("_")[0] in box.DAYS]
        qs = R.trial_pick_path()
        q_trial = R.pose(t.box.point("fri", behind, above), lean, heading, qs[-2])
        t.reset()
        for pct in (R.HELD_PCT, R.STATION_OPEN_PCT, R.TRIAL_OPEN_PCT):
            t.set_arm(q_trial, pct)
            mujoco.mj_kinematics(m, t.data)
            gap, part = nearest(t, arm, boxg)
            print(f"lid edge {front:+.0f} | trial release, jaw {pct:4.0f}%: {gap:5.1f} mm ({part})", flush=True)
        routes = {"trial carry -> fri": ([qs[-2], q_trial], R.TRIAL_OPEN_PCT)}
        for day in box.ROBOT_DAYS:
            q_drop = R.pose(t.box.point(day, behind, above), lean, heading)
            q_above = R.pose(t.box.point(day, behind, above + 30.0), lean, heading, q_drop)
            routes[f"app tray -> high -> {day}"] = ([qs[0], qs[3], q_above, q_drop], R.STATION_OPEN_PCT)
        for name, (legs, open_pct) in routes.items():
            path = np.array(box.densify([[float(v) for v in q] for q in legs]))
            worst = (np.inf, "", -1)
            for i, q in enumerate(path):
                for pct in ((R.HELD_PCT, open_pct) if i == len(path) - 1 else (R.HELD_PCT,)):
                    t.set_arm(q, pct)
                    mujoco.mj_kinematics(m, t.data)
                    gap, part = nearest(t, arm, boxg)
                    if gap < worst[0]:
                        worst = (gap, part, i)
            print(f"lid edge {front:+.0f} | {name:22s}: {worst[0]:5.1f} mm ({worst[1]}, step {worst[2]}/{len(path) - 1})",
                  flush=True)


if __name__ == "__main__":
    main()

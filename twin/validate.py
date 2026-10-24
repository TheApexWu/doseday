"""Check the MuJoCo arm against the real one: drive the vendor model with recorded joint angles and compare where it
puts the wrist with where the arm reported its own wrist (run 04). A 5 degree joint error must show up.

    python twin/validate.py        exit 1 if a check fails
"""
import csv
import sys
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import box  # noqa: E402

MODEL = ROOT / "twin" / "vendor" / "SO101" / "so101_new_calib_camera.xml"
RUN04 = ROOT / "runs" / "2026-10-23-manual-survey-04" / "motion.csv"
ARM_JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
PARKED = (125.0, 155.0)  # arm still: joints and pose were read at the same configuration
POS_TOL_MM, ANG_TOL_DEG, CONTROL_MIN_MM = 2.0, 2.0, 10.0


def rows(t_lo=None, t_hi=None):
    out = []
    for r in csv.DictReader(RUN04.open()):
        t = float(r["t"])
        if (t_lo is None or t >= t_lo) and (t_hi is None or t <= t_hi):
            out.append(r)
    return out


def joints(r):
    return np.array([float(r[f"F{i}"]) for i in range(5)])


class Arm:
    def __init__(self):
        self.model = mujoco.MjModel.from_xml_path(str(MODEL))
        self.data = mujoco.MjData(self.model)
        self.adr = [self.model.jnt_qposadr[self.model.joint(n).id] for n in ARM_JOINTS]
        self.gripper = self.model.body("gripper").id
        self.site = self.model.site("gripperframe").id

    def pose(self, q_deg):
        self.data.qpos[self.adr] = np.radians(q_deg)
        mujoco.mj_kinematics(self.model, self.data)
        return self.data.xpos[self.gripper] * 1000, self.data.xmat[self.gripper].reshape(3, 3).copy()

    def gripperframe(self):
        return self.data.site_xpos[self.site] * 1000


def errors(arm, rs, bias=np.zeros(5)):
    pos, ang = [], []
    for r in rs:
        p, rot = arm.pose(joints(r) + bias)
        pos.append(np.linalg.norm(p - [float(r["x"]), float(r["y"]), float(r["z"])]))
        o = np.array([float(r["o_x"]), float(r["o_y"]), float(r["o_z"])])
        # The arm reports the tool frame: the wrist frame turned half a turn about y, so its z is the wrist's -z.
        ang.append(np.degrees(np.arccos(np.clip(-rot[:, 2] @ o / np.linalg.norm(o), -1, 1))))
    return np.array(pos), np.array(ang)


def main() -> int:
    arm, kin = Arm(), box.Kinematics()
    parked, everything = rows(*PARKED), rows()
    fails = []

    pos, ang = errors(arm, parked)
    print(f"parked rows ({len(parked)}): wrist position error median {np.median(pos):.2f} mm, max {pos.max():.2f}; "
          f"axis error median {np.median(ang):.2f} deg")
    if not (np.median(pos) < POS_TOL_MM and np.median(ang) < ANG_TOL_DEG):
        fails.append("model does not match the arm's reported poses")

    pos_all, _ = errors(arm, everything)
    print(f"all rows ({len(everything)}, arm moving in most): median {np.median(pos_all):.2f} mm, "
          f"95th percentile {np.percentile(pos_all, 95):.2f} mm")

    neg, _ = errors(arm, parked, bias=np.array([0, 5.0, 0, 0, 0]))
    print(f"negative control, shoulder_lift +5 deg: median {np.median(neg):.1f} mm")
    if not np.median(neg) > CONTROL_MIN_MM:
        fails.append("a 5 degree error is invisible, so the check can't discriminate")

    gap, offsets = [], []
    for r in parked[::10]:
        q = joints(r)
        p, rot = arm.pose(q)
        gap.append(np.linalg.norm(kin.wrist(q)[:3, 3] - p))
        tip, _ = kin.tip(q)
        offsets.append(rot.T @ (arm.gripperframe() - tip))  # in the wrist frame, so it doesn't depend on the pose
    off = np.mean(offsets, axis=0)
    print(f"box.Kinematics vs MuJoCo wrist: max {max(gap):.3f} mm")
    print(f"vendor grasp point (gripperframe) minus box.py jaw tip, wrist frame: [{off[0]:+.1f} {off[1]:+.1f} "
          f"{off[2]:+.1f}] mm, {np.linalg.norm(off):.1f} mm apart")

    for f in fails:
        print("FAIL:", f)
    print("PASS" if not fails else "FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

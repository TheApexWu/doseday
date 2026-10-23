"""The fill loop: photo -> detect -> classify -> yaw-align pick -> funnel drop -> inventory.

  python demo.py run --dry-run --image mat.jpg [--calib calib.json]   no arm, prints the plan
  python demo.py run [--no-yaw] [--max 14]                             HARDWARE-ONLY; --no-yaw = T6 control
  python demo.py enroll --image one_pill.jpg NAME [--calib calib.json]
  python demo.py enroll NAME --dir data/NAME [--calib calib.json]     10 arm frames per type (preferred)
  python demo.py loo [--data data] [--calib calib.json]                leave-one-out ID test, pass >= 95%, 0 wrong
  python demo.py calibrate --mat-only [--image F | --source webcam:0]  tags only: real mm, no arm
  python demo.py calibrate [--image mat.jpg] --touch 0 1 2             robot XY from poses.json touch-N
  python demo.py assist [--source webcam:0] [--calib calib.json]       NO ARM: live screen shows each pill's slot

Images come from capture.py (any camera, sidecar), and the run must use the camera the pills were
enrolled on. Phone photos taken on the side are refused.

Live mode re-photographs after every pick: picked pills leave the image and clusters loosen.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

import cv2
import numpy as np

import provenance
import vision
from calib import (DEFAULT_LAYOUT, Calibration, CalibrationError, build, build_mat_only, detect_tags, outside_mat,
                   tag_mask, tag_sides)
from inventory import Inventory
from pills import MIN_SAMPLES, REJECT, Registry, features, from_samples

HERE = Path(__file__).parent
PHOTO_POSE_TOL_MM = 1.0
MISSES_PER_PILL = 2      # then leave that pill on the mat: retrying one pill burned a whole sim run
MISSES_IN_A_ROW = 3      # then stop: the cause is systematic (wrist sign/offset, calibration), not bad luck
SAME_PILL_PX = 15.0


def area_scale(cal: Calibration | None, cx: float, cy: float) -> float:
    """mm^2 per px^2 near (cx, cy): perspective makes it vary across the frame."""
    if cal is None:
        return 1.0
    sq = cal.px_to_mat([(cx - 5, cy - 5), (cx + 5, cy - 5), (cx + 5, cy + 5), (cx - 5, cy + 5)])
    return float(cv2.contourArea(sq.astype(np.float32))) / 100.0


def isolation(pills) -> dict[int, float]:
    """Distance to the nearest other pill, px. Most isolated first leaves clusters for last."""
    pts = np.array([(p.cx, p.cy) for p in pills])
    out = {}
    for i, p in enumerate(pills):
        d = np.hypot(*(pts - pts[i]).T)
        d[i] = np.inf
        out[p.id] = float(d.min()) if len(pills) > 1 else float("inf")
    return out


def plan_picks(pills, registry: Registry, inv: Inventory, cal: Calibration | None = None) -> list[dict]:
    """One step per detected pill. Pure: does not touch inv (assigns against a scratch copy)."""
    scratch = Inventory(inv.schedule)
    scratch.placed = inv.placed.copy()
    iso = isolation(pills)
    steps = []
    for p in sorted(pills, key=lambda q: -iso[q.id]):
        s = {"pill": p.id, "px": (round(p.cx, 1), round(p.cy, 1)), "round": p.round, "aspect": round(p.aspect, 2),
             "angle_img": p.angle_deg, "angle_moments": p.angle_moments_deg}
        if p.merged:
            steps.append({**s, "action": "skip", "why": "merged blob: spread these pills"})
            continue
        kind, dist = registry.classify_pill(p, area_scale(cal, p.cx, p.cy))
        s.update(type=kind, dist=round(dist, 2))
        if cal is not None:
            s["robot_xy"] = tuple(round(v, 1) for v in cal.px_to_robot([(p.cx, p.cy)])[0])
            s["axis_yaw"] = None if p.round else round(cal.axis_yaw_deg(*p.axis_px), 1)
        if p.angle_disagree:
            s["warn"] = "boxPoints and moments disagree on the axis"
        if kind == REJECT:
            steps.append({**s, "action": "reject"})
            continue
        slot = scratch.next_slot(kind)
        if slot is None:
            steps.append({**s, "action": "skip", "why": f"surplus {kind}: week already has enough"})
            continue
        scratch.record(slot, kind)
        steps.append({**s, "action": "pick", "slot": slot})
    order = {"pick": 0, "reject": 1, "skip": 2}
    return sorted(steps, key=lambda st: order[st["action"]])


def detect_masked(img, delta: float):
    tags = detect_tags(img)
    ignore = tag_mask(img.shape, tags, sides=tag_sides(img)) if tags else None
    off_mat = outside_mat(img.shape, tags)
    if off_mat is not None:
        ignore = off_mat if ignore is None else cv2.bitwise_or(ignore, off_mat)
    return vision.detect(img, delta=delta, ignore=ignore)


def print_plan(steps, inv):
    seen = {}
    for st in steps:
        if st.get("type") and st["type"] != REJECT:
            seen[st["type"]] = seen.get(st["type"], 0) + 1
    for st in steps:
        print(json.dumps(st, default=str))
    for line in inv.mismatch(seen):
        print("ALERT", line)


def dry_run(args):
    meta = provenance.require(args.image, args.allow_foreign)
    img = cv2.imread(args.image)
    if img is None:
        raise SystemExit(f"cannot read {args.image}")
    cal = Calibration.load(args.calib) if args.calib else None
    registry = Registry.load(args.pills) if Path(args.pills).exists() else Registry()
    provenance.same_camera({t.camera for t in registry.types}, meta.get("camera"), args.allow_foreign)
    inv = Inventory.from_json(args.schedule)
    pills = detect_masked(img, args.delta)
    steps = plan_picks(pills, registry, inv, cal)
    if cal is None:
        print("# no calibration: positions and angles are in IMAGE pixels (y down), not robot frame")
    print_plan(steps, inv)
    for st in steps:
        if st["action"] == "pick":
            inv.record(st["slot"], st["type"], pill=st["pill"], dry_run=True)
    labels = {st["pill"]: st.get("slot") or st["action"] for st in steps}
    out = Path(args.out or Path(args.image).with_suffix(".plan.png"))
    cv2.imwrite(str(out), vision.annotate(img, pills, labels))
    print(f"\nannotated -> {out}\n")
    print(inv.summary())
    return steps


def preflight(poses: dict, inv: Inventory) -> None:
    """Every pose the run can reach for must exist before the arm moves: a missing key after a
    close would leave a pill clamped mid-run."""
    need = {"photo", "table_z"} | {slot for slot in inv.schedule}
    missing = sorted(k for k in need if k not in poses)
    if missing:
        raise SystemExit(f"REFUSED: poses.json is missing {missing}; teach them first (arm.py teach NAME)")


async def live(args):
    """HARDWARE-ONLY, except --sim: the same loop against sim.SimArm (no Viam, no arm)."""
    from arm import FIXED_THETA
    log_dir = HERE / "logs"
    log_dir.mkdir(exist_ok=True)
    inv_log = log_dir / ("sim-inventory.jsonl" if args.sim else "inventory.jsonl")
    if args.sim:
        inv_log.unlink(missing_ok=True)  # each rehearsal starts from an empty week
    inv = Inventory.from_json(args.schedule, log_path=inv_log)
    robot = a = None
    if args.sim:
        import sim
        a, cal, poses, registry = sim.build(args, inv)
    else:
        from arm import PillArm, connect, load_poses
        poses = load_poses()
        cal = Calibration.load(args.calib)
        if cal.mat_only:
            raise SystemExit("REFUSED: mat-only calibration has no robot frame; run `calibrate --touch 0 1 2` with the arm")
        registry = Registry.load(args.pills)
    preflight(poses, inv)
    if not args.sim and any(abs(poses["photo"][k] - cal.photo_pose[k]) > PHOTO_POSE_TOL_MM for k in ("x", "y", "z")):
        raise SystemExit("photo pose in poses.json differs from the calibrated one: recalibrate")
    try:
        if a is None:
            robot = await connect()
            a = PillArm(robot, table_z=cal.table_z, limits=poses.get("limits"), yaw_align=not args.no_yaw)
        misses: list = []          # [px, count] per pill location that failed
        streak = 0
        pending = None             # a pick the gripper could not confirm; the next photo decides it
        for i in range(args.max):
            ph = cal.photo_pose
            reached = await a.move(ph["x"], ph["y"], ph["z"], FIXED_THETA, "photo")
            if np.hypot(reached["x"] - ph["x"], reached["y"] - ph["y"]) > PHOTO_POSE_TOL_MM:
                raise SystemExit(f"arm did not reach the photo pose ({reached}); homography invalid here")
            await asyncio.sleep(0 if args.sim else 0.5)  # let the arm settle before the frame used for coordinates
            img = await a.photo()
            photo = log_dir / f"photo-{time.strftime('%H%M%S')}-{i}.jpg"
            cv2.imwrite(str(photo), img)
            pills = detect_masked(img, args.delta)
            if pending:
                ok = _confirm_pick(pending, img, len(pills), inv, a)
                streak = 0 if ok else streak + 1
                if not ok:
                    _count_miss(misses, pending["px"])
                pending = None
                if streak >= MISSES_IN_A_ROW:
                    print(f"STOPPED: {streak} unconfirmed picks in a row. Check the closed jaw gap (T0) and "
                          f"the T1 crosshair before more picks. Placed so far:")
                    break
            steps = plan_picks(pills, registry, inv, cal)
            given_up = [m[0] for m in misses if m[1] >= MISSES_PER_PILL]
            steps = [s for s in steps
                     if not any(np.hypot(s["px"][0] - g[0], s["px"][1] - g[1]) < SAME_PILL_PX for g in given_up)]
            step = next((s for s in steps if s["action"] == "pick"), None)
            if step is None and "reject" in poses:
                step = next((s for s in steps if s["action"] == "reject"), None)
            if step is None:
                print("nothing left to pick:", [s.get("why", s["action"]) for s in steps])
                break
            x, y = step["robot_xy"]
            theta = await a.pick(x, y, step["axis_yaw"], f"pill{i}")
            held = await a.holding()
            if held is False:  # missed: nothing to drop, and nothing to record
                await a.gripper_open()
                streak += 1
                _count_miss(misses, step["px"])
                a.log({"miss": step["px"], "type": step["type"], "streak": streak})
                print(f"{i}: missed {step['type']} at {step['px']} ({streak} in a row)")
                if streak >= MISSES_IN_A_ROW:
                    print(f"STOPPED: {streak} misses in a row. Systematic, not luck: check T4 wrist sign/offset "
                          f"(--no-yaw to compare), then the T1 crosshair. Placed so far:")
                    break
                continue
            if held:  # only a confirmed grip resets the run of misses; Lite (None) waits for the photo check
                streak = 0
            dest = step.get("slot") or "reject"
            await a.drop(poses[dest], f"drop/{dest}")
            if dest != "reject":
                # Recorded now so the planner does not fill the slot twice; a pick the gripper could
                # not confirm (Lite: held is None) is retracted if the next photo says it never left.
                inv.record(dest, step["type"], photo=str(photo), px=step["px"], axis_yaw=step["axis_yaw"],
                           theta=theta, yaw_align=a.yaw_align, grip_verified=held)
                if held is None:
                    p = next(q for q in pills if q.id == step["pill"])
                    length = float(np.hypot(p.axis_px[1][0] - p.axis_px[0][0], p.axis_px[1][1] - p.axis_px[0][1]))
                    pending = {"slot": dest, "type": step["type"], "px": step["px"], "before": img,
                               "count": len(pills), "radius": max(8, int(0.6 * length))}
            print(f"{i}: {step['type']} -> {dest}  theta {theta:.0f}  grip {held}")
        if pending:  # the last unconfirmed pick needs one more look
            ph = cal.photo_pose
            await a.move(ph["x"], ph["y"], ph["z"], FIXED_THETA, "photo/final-check")
            img = await a.photo()
            _confirm_pick(pending, img, len(detect_masked(img, args.delta)), inv, a)
        print(inv.summary())
        if args.approve:
            import trust
            final = log_dir / f"final-{time.strftime('%H%M%S')}.jpg"
            cv2.imwrite(str(final), await a.photo())
            print(trust.request_approval(final, inv.summary()[:1000], args.approve_timeout))
        return inv
    except BaseException:
        if a is not None:
            await a.stop()
        raise
    finally:
        if robot is not None:
            await robot.close()


def _count_miss(misses: list, px) -> None:
    m = next((m for m in misses if np.hypot(m[0][0] - px[0], m[0][1] - px[1]) < SAME_PILL_PX), None)
    if m is None:
        misses.append([px, 1])
    else:
        m[1] += 1


def _confirm_pick(pending: dict, after, count_after: int, inv: Inventory, a) -> bool:
    """Photo evidence for a pick the gripper could not confirm: the spot changed and exactly one
    pill left the mat. Otherwise the placement is retracted and the slot is planned again."""
    import trust
    # ROI sized to the pill: a fixed 80 px box made a removed 4 mm pill look like "no change" (sim, 22 Oct)
    chk = trust.verify_pick(pending["before"], after, pending["px"], pending["count"], count_after,
                            radius=pending.get("radius", 40))
    a.log({"photo_check": pending["px"], "slot": pending["slot"], "ok": chk.ok, "why": chk.why,
           "roi_change": round(chk.roi_change, 3)})
    if not chk.ok:
        inv.retract(pending["slot"], pending["type"], why=chk.why, px=pending["px"])
        print(f"   photo check: {pending['slot']} {pending['type']} NOT confirmed ({chk.why}); will refill")
    return chk.ok


def _single_pill(path, args, cal):
    meta = provenance.require(path, args.allow_foreign,
                              allowed=(provenance.ARM, provenance.CAPTURED) if not args.allow_foreign else ())
    img = cv2.imread(str(path))
    pills = [p for p in detect_masked(img, args.delta) if not p.merged]
    if len(pills) != 1:
        raise SystemExit(f"{path}: enrollment wants exactly one pill in view, saw {len(pills)}")
    p = pills[0]
    return features(p, area_scale(cal, p.cx, p.cy)), meta.get("camera", "")


def _frames(d) -> list:
    return sorted(Path(d).glob("*.png"))


def enroll(args):
    cal = Calibration.load(args.calib) if args.calib else None
    registry = Registry.load(args.pills) if Path(args.pills).exists() else Registry()
    unit = "mm" if cal else "px"
    paths = _frames(args.dir) if args.dir else [args.image]
    if args.dir and len(paths) < MIN_SAMPLES:
        raise SystemExit(f"{args.dir}: {len(paths)} frames; capture at least {MIN_SAMPLES} (10 is better)")
    got = [_single_pill(p, args, cal) for p in paths]
    cams = {c for _, c in got}
    if len(cams) > 1:
        raise SystemExit(f"{args.name}: frames from several cameras {sorted(cams)}; enroll from one")
    t = from_samples(args.name, [f for f, _ in got], unit, cams.pop())
    registry.types = [x for x in registry.types if x.name != args.name]  # re-enrolling replaces
    registry.enroll(t)
    registry.save(args.pills)
    size = " x ".join(f"{v:.2f}" for v in t.size)
    spread = " x ".join(f"{v:.2f}" for v in t.size_std) or "n/a"
    print(f"enrolled {args.name}: n={t.n} size {size} {unit} (spread {spread}) lab {np.round(t.lab, 1).tolist()}")


def loo(args):
    """Leave-one-out: each frame is classified against types built from every other frame."""
    cal = Calibration.load(args.calib) if args.calib else None
    unit = "mm" if cal else "px"
    data = {d.name: [_single_pill(p, args, cal)[0] for p in _frames(d)]
            for d in sorted(Path(args.data).iterdir()) if d.is_dir() and not d.name.startswith("scene")}
    data = {k: v for k, v in data.items() if len(v) > MIN_SAMPLES}
    if len(data) < 2:
        raise SystemExit(f"need >= 2 labels with > {MIN_SAMPLES} frames each in {args.data}")
    tally = {"correct": 0, "wrong": 0, "reject": 0}
    for name, feats in data.items():
        for i, f in enumerate(feats):
            reg = Registry([from_samples(n, fs[:i] + fs[i + 1:] if n == name else fs, unit) for n, fs in data.items()])
            got, dist = reg.classify(*f)
            kind = "correct" if got == name else "reject" if got == REJECT else "wrong"
            tally[kind] += 1
            if kind != "correct":
                print(f"  {name} #{i}: -> {got} (d={dist:.2f})")
    n = sum(tally.values())
    ok = tally["correct"] / n >= 0.95 and tally["wrong"] == 0
    print(f"LOO {tally} of {n}: {'PASS' if ok else 'FAIL'} (need >= 95% correct, 0 wrong)")
    return tally


def t1_verdict(misses: dict, limit: float) -> bool:
    """T1 passes only when every check tag has a number in [0, limit]. A blank entry is NaN, and
    NaN fails every comparison, so it cannot slip through the way max() skips it."""
    return bool(misses) and all(0 <= m <= limit for m in misses.values())


def crosshair_targets(img, cal: Calibration, tag_ids) -> dict:
    """Robot xy over each tag centre, through the same transform the picks use. T1 sends the
    pen/fingertip there and you ruler the miss: tags not used for the touch-off are the honest check."""
    tags = detect_tags(img)
    missing = [t for t in tag_ids if t not in tags]
    if missing:
        raise SystemExit(f"tags {missing} not visible in the photo")
    return {t: tuple(float(v) for v in cal.px_to_robot([tags[t]])[0]) for t in tag_ids}


async def crosshair(args):
    """HARDWARE-ONLY. T1: hover 2 mm over each check tag, you measure and type the miss."""
    from arm import FIXED_THETA, PillArm, connect, load_poses
    cal = Calibration.load(args.calib)
    if cal.mat_only:
        raise SystemExit("REFUSED: mat-only calibration has no robot frame")
    poses = load_poses()
    robot = await connect()
    a = None
    try:
        a = PillArm(robot, table_z=cal.table_z, limits=poses.get("limits"))
        ph = cal.photo_pose
        await a.move(ph["x"], ph["y"], ph["z"], FIXED_THETA, "photo")
        await asyncio.sleep(0.5)
        targets = crosshair_targets(await a.photo(), cal, args.tags)
        misses = {}
        for t, (x, y) in targets.items():
            await a.move(x, y, cal.table_z + 20, FIXED_THETA, f"crosshair/{t}/hover")
            await a.move(x, y, cal.table_z + 2, FIXED_THETA, f"crosshair/{t}/check", straight=True)
            misses[t] = float(input(f"tag {t}: miss in mm from tag centre? ") or "nan")
            await a.move(x, y, cal.table_z + 20, FIXED_THETA, f"crosshair/{t}/up", straight=True)
        a.log({"crosshair_mm": misses})
        verdict = "PASS" if t1_verdict(misses, args.t1_limit) else "FAIL"
        print(f"T1 misses mm {misses}: {verdict} (limit {args.t1_limit})")
    except BaseException:
        if a is not None:
            await a.stop()
        raise
    finally:
        await robot.close()


def calibrate_mat_only(args):
    if args.image:
        provenance.require(args.image, args.allow_foreign)
        img = cv2.imread(args.image)
    else:
        from camera import open_source
        cam = open_source(args.source)
        try:
            img = cam.frame()
        finally:
            cam.close()
    try:
        cal = build_mat_only(img, DEFAULT_LAYOUT)
    except CalibrationError as e:
        raise SystemExit(f"REFUSED: {e}")
    cal.save(args.calib)
    print(f"saved {args.calib} (mat only, no robot frame): tag residual mm {cal.tag_err_mm}")
    return cal


def assist(args):
    """NO ARM. Live view: each pill labelled with its type and target slot; the person places it.
    s = save frame + plan, a = send the current view to the caretaker for approval, q = quit.
    The same plan the arm would run, so this is also the fallback demo."""
    from camera import camera_id, open_source
    cal = Calibration.load(args.calib) if args.calib else None
    registry = Registry.load(args.pills) if Path(args.pills).exists() else Registry()
    provenance.same_camera({t.camera for t in registry.types}, camera_id(args.source), args.allow_foreign)
    inv = Inventory.from_json(args.schedule)
    cam = open_source(args.source)
    out = Path(args.data) / "assist"
    try:
        for _ in range(args.frames or 10 ** 9):
            img = cam.frame()
            pills = detect_masked(img, args.delta)
            steps = plan_picks(pills, registry, inv, cal)
            labels = {st["pill"]: st.get("slot") or st["action"] for st in steps}
            view = vision.annotate(img, pills, labels)
            if args.headless:
                print_plan(steps, inv)
                continue
            cv2.imshow("pill assist (s=save, q=quit)", view)
            k = cv2.waitKey(30) & 0xFF
            if k == ord("q"):
                break
            if k == ord("a"):
                import trust
                out.mkdir(parents=True, exist_ok=True)
                f = out / f"approve-{time.strftime('%H%M%S')}.png"
                cv2.imwrite(str(f), view)
                print(trust.request_approval(f, inv.summary()[:1000], args.approve_timeout))
            if k == ord("s"):
                out.mkdir(parents=True, exist_ok=True)
                f = out / f"{time.strftime('%H%M%S')}.png"
                cv2.imwrite(str(f), img)
                provenance.write(f, provenance.CAPTURED, camera=camera_id(args.source), label="assist")
                cv2.imwrite(str(f.with_suffix(".plan.png")), view)
                print_plan(steps, inv)
    finally:
        cam.close()
        if not args.headless:
            cv2.destroyAllWindows()


async def calibrate(args):
    """Touch points come from `python arm.py teach touch-N` with the TCP on tag N's centre."""
    from arm import FIXED_THETA, PillArm, connect, load_poses
    poses = load_poses()
    robot = None
    if args.image:
        provenance.require(args.image, args.allow_foreign)
        img = cv2.imread(args.image)
    else:  # HARDWARE-ONLY
        robot = await connect()
        a = PillArm(robot, table_z=poses["table_z"])
        ph = poses["photo"]
        await a.move(ph["x"], ph["y"], ph["z"], FIXED_THETA, "photo")
        await asyncio.sleep(0.5)
        img = await a.photo()
    try:
        touches = [(DEFAULT_LAYOUT[n], (poses[f"touch-{n}"]["x"], poses[f"touch-{n}"]["y"])) for n in args.touch]
        cal = build(img, DEFAULT_LAYOUT, touches, poses["table_z"], poses["photo"])
    except CalibrationError as e:
        raise SystemExit(f"REFUSED: {e}")
    finally:
        if robot:
            await robot.close()
    cal.save(args.calib)
    print(f"saved {args.calib}: tag residual mm {cal.tag_err_mm}, touch residual mm {np.round(cal.touch_res_mm, 2)}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("run", "enroll", "calibrate", "loo", "assist", "crosshair"))
    ap.add_argument("name", nargs="?")
    ap.add_argument("--image")
    ap.add_argument("--calib", default=None)
    ap.add_argument("--pills", default=str(HERE / "pills.json"))
    ap.add_argument("--schedule", default=str(HERE / "schedule.json"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-yaw", action="store_true", help="T6 negative control: fixed wrist yaw")
    ap.add_argument("--max", type=int, default=14)
    ap.add_argument("--delta", type=float, default=50.0, help="grey levels a pill must differ from its zone")
    ap.add_argument("--touch", type=int, nargs="+", default=[0, 1, 2],
                    help="tag ids touched; 2 touches cannot see a sideways miss, so the default touches 3")
    ap.add_argument("--tags", type=int, nargs="+", default=[3, 4], help="crosshair: tags NOT used for touch-off")
    ap.add_argument("--t1-limit", type=float, default=2.0, help="crosshair pass limit, mm")
    ap.add_argument("--out")
    ap.add_argument("--dir", help="enroll from every captured frame in this folder")
    ap.add_argument("--source", default="webcam:0", help="viam | webcam[:N] | dir:PATH (assist, mat-only calibrate)")
    ap.add_argument("--mat-only", action="store_true", help="calibrate from tags alone: real mm, no arm")
    ap.add_argument("--headless", action="store_true", help="assist: print plans instead of a window")
    ap.add_argument("--frames", type=int, default=0, help="assist: stop after N frames (0 = until q)")
    ap.add_argument("--approve", action="store_true", help="live: send the final photo to the caretaker and wait")
    ap.add_argument("--sim", action="store_true", help="run: rehearse the live loop against a simulated arm")
    ap.add_argument("--sim-theta-sign", type=float, default=None, help="sim: the arm's TRUE wrist sign (try -1)")
    ap.add_argument("--sim-slip", type=float, default=0.0, help="sim: chance a well-aimed grip still misses")
    ap.add_argument("--sim-seed", type=int, default=0)
    ap.add_argument("--sim-lite", action="store_true", help="sim: gripper with no grip feedback (photo check decides)")
    ap.add_argument("--approve-timeout", type=float, default=600)
    ap.add_argument("--data", default=str(HERE / "data"))
    ap.add_argument("--allow-foreign", action="store_true",
                    help="accept images without an arm-camera sidecar (synthetic geometry tests only)")
    args = ap.parse_args(argv)
    if args.cmd == "run" and args.dry_run:
        return dry_run(args)
    if args.cmd == "run":
        args.calib = args.calib or str(HERE / "calib.json")
        return asyncio.run(live(args))
    if args.cmd == "enroll":
        return enroll(args)
    if args.cmd == "loo":
        return loo(args)
    if args.cmd == "assist":
        return assist(args)
    if args.cmd == "crosshair":
        args.calib = args.calib or str(HERE / "calib.json")
        return asyncio.run(crosshair(args))
    if args.cmd == "calibrate" and args.mat_only:
        args.calib = args.calib or str(HERE / "calib.json")
        return calibrate_mat_only(args)
    args.calib = args.calib or str(HERE / "calib.json")
    return asyncio.run(calibrate(args))


if __name__ == "__main__":
    main()

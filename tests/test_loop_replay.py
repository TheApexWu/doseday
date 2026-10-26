import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import loop_replay  # noqa: E402

HEAD = "frame,unix_time,F0,F1,F2,F3,F4,L0,L1,L2,L3,L4,x,y,z,o_x,o_y,o_z,theta,jaw_pct,leader_jaw_pct\n"


def run_dir(tmp_path, rows):
    (tmp_path / "samples.csv").write_text(HEAD + "".join(
        f"{i},{1000 + t},{i},0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,{jaw},{lead}\n" for i, (t, jaw, lead) in enumerate(rows)))
    return tmp_path


def test_window_and_rate_rescale_time(tmp_path):
    run = run_dir(tmp_path, [(t / 10, 1.0, "") for t in range(0, 101)])  # 10 s at 10 Hz
    path = loop_replay.load(run, until=8.0, start=2.0, rate=2.0)
    assert path[0][0] == 0.0 and path[0][1][0] == 20  # starts at the 2 s sample, re-timed to zero
    assert abs(path[-1][0] - 3.0) < 0.11                 # 6 s of motion at 2x is 3 s
    assert all(b[0] > a[0] for a, b in zip(path, path[1:]))


def test_leader_grip_wins_over_the_followers_partial_mirror(tmp_path):
    run = run_dir(tmp_path, [(0.0, 2.0, 30.0), (0.5, 2.0, "nan"), (1.0, 2.0, "")])
    assert [g for _, _, g in loop_replay.load(run)] == [30.0, 2.0, 2.0]


def test_jaw_open_turns_a_small_opening_into_a_real_one(tmp_path):
    run = run_dir(tmp_path, [(0.0, 9.0, ""), (0.5, 3.0, "")])
    assert [g for _, _, g in loop_replay.load(run, jaw_open=40.0)] == [40.0, 0.0]

# AGENTS.md

Read README.md, docs/CONTROL.md and docs/TESTS.md before changing anything. This repo sorts candy or vitamins with a
SO-101 arm under Viam. Picks, drops and lid closes have run on the arm (docs/DAY2-FINDINGS.md); docs/TESTS.md lists the numbered tests.

## Tests

- Clear caches before a baseline: `find . -name __pycache__ -type d -exec rm -rf {} +`, then `python -B -m pytest -q`.
  A stale .pyc can make a mutation check lie.
- Hardware methods (`_hw_*` in `arm.py`) are overridden by a fake in `tests/test_arm.py`. Any new hardware path
  needs a dry-run test built on that override before it is pushed.

## Rules

- **Secrets:** only from the environment: `VIAM_ADDRESS`, `VIAM_API_KEY_ID`, `VIAM_API_KEY`, the Telegram
  variables read in `trust.py` and `notify.py`, and the Vonage variables in `notify.py`. Never put them in code,
  `poses.json`, logs or commits. Logs hold message text, never keys.
- **Moves:** every arm move goes through `PillArm.move`: limits check, then plan-only, then move, then log.
  New code must not call the `_hw_move` hook or the motion client directly.
- **Plan-only first:** a move path calls `_hw_plan` before `_hw_move`, and has a test that a planner refusal means no move.
- **Log commanded poses:** log the commanded x, y, z and theta. Do not trust read-back theta at the gripper-down pole.
- **Gripper:** the SO-101 gripper is set by percentage with `set_position`. Never call `grab()`.
- **Images:** only from `capture.py`, with a provenance sidecar. Enrollment and runs use the same camera.
- **Approval:** `trust.request_approval` is the only path to the caretaker. It stays fail-closed: timeout and Flag
  do not release. Approval is a logged decision, not a physical lock.
- **Refuse, don't guess:** raise `MoveRefused` or `SystemExit` with the reason. Missing poses stop the run before the first move.
- **Thresholds:** do not change the calibration limit, `ACCURACY_MM` or the pill thresholds on site without
  recording the test number in docs/TESTS.md.
- **Repo hygiene:** no local paths, private notes, personal details or credentials in tracked files.
  `tests/test_repo_hygiene.py` enforces the path and ignore rules.
- **Diffs:** small. One change per commit.

## Style

- Comments say why, not what. Keep comments under about 20% of lines.
- Guard clauses and early returns.
- Mark hardware-only code with a HARDWARE-ONLY note in its docstring.
- Keep pure logic free of Viam imports so it runs offline.

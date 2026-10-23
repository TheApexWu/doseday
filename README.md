# Doseday

A robot arm that sorts single pills from a matte black mat into a 7-day organizer and logs each placement.

The demo uses candy or vitamins only. Nothing in this repository is medical advice, and the code is not validated
for handling medication.

## What it does

1. Enroll one example of each pill type (closed set, up to 5 types).
2. Photograph the mat, find each pill, and classify it. Unknown pills go to a reject bin.
3. Turn the wrist to the pill's long axis, pick, and drop it through a funnel into its day slot.
4. Log each placement, and ask a caretaker to approve the finished organizer before release.

The arm is an SO-101 under Viam. The motion and gripper calls are stubs until the SO-101 port lands,
so the code does not move hardware yet.

## Setup

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -B -m pytest -q
```

Offline runs need no arm and no Viam SDK. See `docs/ONBOARDING.md`.

## Docs

| File | Read it for |
|---|---|
| `docs/ONBOARDING.md` | setup, repo tour, first hour on the arm |
| `CONTROL.md` | control logic, safety gates, fallback plans |
| `TESTS.md` | the numbered hardware tests (T-1 to T8) |
| `AGENTS.md` | rules for changing the code |
| `docs/TEAMWORK.md` | branches, merge rules, timeline |

## Secrets and site data

Credentials come from the environment only. `poses.json`, `calib.json`, `pills.json` and `.env*` are site data
and are gitignored. Do not commit them.

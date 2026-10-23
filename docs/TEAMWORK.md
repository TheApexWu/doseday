# Teamwork

One repo, one hackathon day. Everyone reads AGENTS.md before writing code. Roles are split once the kit is in hand.

## Branches and commits

- One branch per task: `<name>/<task>`. Branch from `dev`.
- Save and share work with `./checkpoint.sh "what changed"`. It runs the tests, commits everything on your branch
  and pushes. A red test run still pushes, tagged WIP. Run it every 30 minutes, after every test result, and before any arm run.
- Subject line imperative. Add one line on the cause when the change is a fix.
- Merge with a merge commit, not a squash, so each step stays visible in history.

## Merge rules

- Open a pull request into `dev`. Another person reads the diff before merge.
- Before merging, `python -B -m pytest -q` is green.
- Changes to the live path (`live()`, `PillArm.stop()`, `PillArm.move`) or the approval path
  (`trust.request_approval`) get two reviewers, even when the change looks small.

## Timeline

H0 is the moment the kit is in hand. Each gate passes on a recorded number. A failed gate drops to the fallback;
it does not get retried past its limit.

| When | Work | Gate (record the number) | If it fails |
|---|---|---|---|
| Before the event | Environment and `pytest`; rehearse plan E (`assist`) on a webcam; enroll stand-ins; run `loo` | tests green, `loo` PASS | fix before the event |
| H0 to +20 min | T-1 connect, T0 gripper percentages | open and closed percentages | log replies, ask the organizers |
| +20 to +75 min | T1 teach, `calibrate --touch`, `crosshair` | residual and crosshair misses (mm) | re-touch twice, then centre-only picks or plan E |
| +75 to +105 min | T2 detection in venue light; enroll on the venue camera; `loo` | found and false counts; `loo` result | diffuse light, larger stand-ins |
| +105 to +165 min | T5 grip (10 picks, no yaw), T4 yaw sign | picks held out of 10; yaw sign and offset | cups (plan D) or plan E; drop auto-align if T4 fails |
| +165 to +240 min | Full loop on 3 pills; verify each | 3 placed, 0 wrong slot | plan E for the demo |
| +240 to +300 min | Approval loop; record the best clean run | the caretaker's phone shows the photo | show the recorded run and say the send is not live |
| +300 min | Freeze the code, push, write down the numbers | pushed | |

Before editing a file someone else touched in the last hour, say so in chat.

## Questions for the organizers

- Is code written before the event allowed, and does it need to be disclosed?
- Which arm kit, gripper and camera does each team get?
- Does the venue Wi-Fi isolate devices, and is Ethernet available at the robot tables?
- Can a person's hands be near the arm while it moves?
- When do submissions close, and do judges see a live run or a video?
- What are the judging criteria for the track?

## Status line, every hour

One line in the team chat:

`HH:MM | Done: ... | Doing: ... | Blocked: ...`

## Raise it immediately

Stop the arm first, then say it in chat:

- The arm moves in a way the log does not show, or a move lands more than `ACCURACY_MM` from its target.
  The code only warns at that distance, so the warning is the signal, not a stop.
- A calibration residual is over its limit.
- Anything near a person's hand, or a pill held with the arm idle.
- Two plan refusals in a row.

`PillArm.stop()` runs only when `live()` hits an exception. It is not a physical stop. Use the hardware stop first.

## Showing the work

- Write the number for every test in TESTS.md (`Result: ____`), as a count.
- Keep the T-1 to T2 log in one place. `logs/` is gitignored, so copy the `logs/arm-*.jsonl` lines you rely on into the write-up.
- Each person presents the part they built and measured.

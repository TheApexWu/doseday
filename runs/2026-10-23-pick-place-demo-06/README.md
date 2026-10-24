# Run 06: hand-guided pick and place of a Tums (manual mode)

**When:** 23 Oct 2026, 19:10:32 ET, 240 s.
**Machine:** `pi-arm1`; follower in manual mode at torque 30, guided by Alex's hand. Jaws opened to 42% before the start.
**Recording:** `record_teleop.py 240 --no-teleop --follower-only` and wrist frames at 1/s (`frames/`, seconds since 19:10:32; content lags ~1-2 s).

## What happened (CSV measured; frames read by eye)

| t (s) | Event |
|---|---|
| 0-84 | Parked, jaw tip (262, −64, 73) |
| 84-99 | Alex moves the claw out over the far mat (hand in frames 88-94) |
| 99-171 | Claw held around a Tums at jaw tip (346, −108, 11), leaning ~22° with heading −88° (frames 100-140) |
| ~171-180 | Jaw closes to ~8%: held (an empty close reads under 1%) |
| 180-226 | Carried over the box; at 197-209 s the claw goes down by a second TUMS (frame 200) while still holding the first |
| 226 | Jaw opens to 91% at Friday's front edge, jaw tip (248, −68, 30): release |
| 228-240 | Lift over Thursday, then down by a red M&M and a mint pill (frame 239) |

The release put a pill in Friday's front. The frames can't tell whether it is inside the compartment or resting on the half-open lid.

`box.Kinematics().ik` reproduces the grasp joints at 140 s within 0.5° (`scripts/trial_pick.py` uses this grasp).

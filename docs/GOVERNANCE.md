# Governance

Doseday moves pills into a pill box that someone will take medicine from. A person stays responsible for every fill.
The rules below are enforced in code (`governance.py`, `trust.py`, `notify.py`) and tested in
`tests/test_governance.py` and `tests/test_trust.py`.

## Rules

1. **A caretaker checks every fill.** After a fill, "Ask caretaker to check" sends the caretaker a photo of the
   organizer on Telegram with Approve and Flag buttons.
   - Each request has a fresh run id, so an old Approve cannot release a new fill.
   - Only a press from the caretaker's own Telegram account (`TELEGRAM_CARETAKER_ID`) counts.
   - No answer before the wait ends (10 minutes) means not released.
2. **Flag pauses the arm.** While the last fill is flagged, the server refuses every "place" command. STOP, close
   and home still run. The pause ends when a later fill is approved.
3. **No answer escalates.** If the caretaker hasn't answered, they get an SMS through Vonage. The fill stays
   not released.
4. **The family is told, not shown.** The family group on Telegram gets plain-text notices: the fill was sent,
   approved, flagged, not answered, or the arm was stopped. Photos of pills go only to the caretaker.
5. **STOP always wins.** STOP cancels the running action, empties the queue and stops the arm. The family and the
   caretaker are then told the arm was stopped. Those messages go out in the background, so STOP never waits on the
   network.
6. **Everything is logged.** Arm actions go to `logs/station-*.jsonl`, caretaker decisions to `logs/trust.jsonl`,
   and notices and governance events to `logs/governance.jsonl`. A notice that fails to send is logged as
   `send_failed`, never hidden.
7. **No medical decisions.** Doseday does not choose doses or give medical advice. It places what a person asked
   for. The pill detectors (Viam colour detector, YOLOv8) are display only and never decide a placement.
8. **Demos use candy and vitamins**, never real medication.

## Channels

| Who | How | Env (all in `.env`, never committed) |
|---|---|---|
| Caretaker (photo + decision) | Telegram bot | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_CARETAKER_ID` |
| Family group (text only) | Telegram bot | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_FAMILY_CHAT_ID` |
| Caretaker SMS (escalation, STOP) | Vonage SMS API | `VONAGE_API_KEY`, `VONAGE_API_SECRET`, `VONAGE_FROM`, `CARETAKER_PHONE` |

A channel with missing env runs in **demo mode**: it logs what it would have sent and sends nothing. The page shows
"live" or "demo mode" for each channel. With no caretaker connected, the page offers "Demo: act as caretaker"
buttons. The server refuses those (403) as soon as a real caretaker is connected.

`python trust.py whoami` prints the chat and user ids that have messaged the bot, to fill in the Telegram ids.
A Vonage trial account can text only numbers verified on its dashboard.

## Not covered

- Approval is a logged decision, not a physical lock on the box.
- There is no sign-in on the page. The server listens on this laptop only (127.0.0.1).

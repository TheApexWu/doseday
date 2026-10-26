# Demo Day (25 Oct 2026, Luma Studios): what ran and what broke

Doseday won the Physical AI track. The live demo ran on a second Viam kit, `pi-arm3`, because `pi-arm1` could not
join the venue WiFi.

## What ran live

- **Teleop:** Viam's `so101-arm/teleop` service (`arm-teleop` on this kit) mirrored the black leader arm onto the
  white follower at 100 Hz. `armctl.py align 15` brought the follower to the leader slowly before each start.
- **Teaching data:** `scripts/record_demo.py` saved both arms, both grips and the wrist camera while we drove it
  (`runs/DATASET.md`, 25 Oct section). The page's Teaching data panel showed the recording live.
- **Replay on a loop:** `scripts/loop_replay.py` replayed a recorded pick on the follower by itself, trimmed to the
  motion and at 1.5x, with an auto-restart when the cloud connection dropped.
- **Caretaker check:** the photo from the arm's camera went to a phone over Telegram with Approve and Flag; the page
  spoke the result out loud. The no-answer reminder went over Telegram because Vonage was not set up.

## What broke, and the fix

- **pi-arm1 setup page:** `viam-setup-pi-arm1` came up, but saving a network failed with "settings plugin does not
  support adding connections". It had worked from the same page on 24 Oct about 16:05.
- **Leader and follower swapped in pi-arm3's config:** softening "leader-arm" softened the white arm. Swapping the
  two in the config fixed it.
- **Leader wrist roll read a full turn off** (-527 for -167) after being twisted; the follower stopped at its own
  limit (-166) and the claw stopped turning. A power cycle of the leader's board fixed the count.
- **Grip mirroring was partial** on this kit; recordings now include the leader's grip.

## Running it on another kit

Part names come from `.env`: `PILL_TELEOP` (teleop service), `PILL_CAMERA` and `PILL_CAMERA_SOURCE` (empty for a
plain webcam). `app.py --fake --live-cam` shows the real camera while the arm stays with teleop. Without a colour
detector service the page shows the camera with no boxes and never edits the machine's cloud config.

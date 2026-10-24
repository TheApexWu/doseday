# Moving to a new venue

Pack tonight, rebuild tomorrow. All lid and drop positions come from the pillbox position (`box.py`), so only the pill tray needs re-teaching by hand.

```text
DOSEDAY: PACK TONIGHT, REBUILD TOMORROW
(all poses now come from the pillbox position, so nothing needs re-teaching by hand except the pill tray)

=== BEFORE YOU PACK (tonight) ===
1. Pi network for tomorrow. Ask Nick how pi-arm1 joins a new WiFi.
   Safest: add your phone hotspot (name + password) to the machine's network settings tonight, so the
   Pi comes online anywhere. Without network the laptop cannot reach the arm.
2. USB ports: ask Nick to switch the follower/leader ports in the config to /dev/serial/by-id/... paths.
   Today the leader moved to ttyACM2 after a re-plug and broke the config.
3. Photos with your phone, top-down and side: arm clamp position on the table edge, pillbox position
   and tape marks, black paper, lamp position.
4. Power-off: the white arm drops when torque cuts. Run  python armctl.py free 30  (manual mode),
   fold it down onto the table by hand, then power off. The black leader is already limp.

=== TOMORROW (about 10 min) ===
1. Clamp the arm at the table edge. Lay the black paper.
2. Pillbox: front edge about 20 cm in front of the centre of the arm's rotating base, Wednesday
   straight ahead, roughly square. Tape both ends (Sun/Sat). Today's box sat 6 deg skewed and was fine.
3. Power on. Check the Viam app shows pi-arm1 online. Close the CONTROL tab before running scripts.
4. Register the box (2 touches):
     python armctl.py free 30          manual mode
     (rest the closed claw tip on MONDAY's lid, front edge, centred)
     python box.py mark mon
     (same on FRIDAY)
     python box.py mark fri
     python box.py fit                 refuses marks that are not 4 lids apart, or not level
     python armctl.py off
     python box.py show                every Mon-Fri stroke must print (an error = box out of reach: move it)
5. Test: open Wednesday by hand, then  python box.py stroke wed
6. Re-teach the pill tray:  python armctl.py teach tray_hover / tray_down  (manual mode, claw over the tray)
7. python app.py  ->  the page.
```

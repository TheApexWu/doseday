# Rebuilding at a new venue

All lid and drop positions come from the pillbox position (`box.py`), so only the pill tray needs re-teaching by hand. Layout numbers, wiring and photos are in `docs/HARDWARE-SETUP.md`.

```text
DOSEDAY: REBUILD AT THE NEW VENUE (Sat 24 Oct)
Doors close at 5 PM: shoot every robot clip before then.
Submit the 3-min video and the repo by 11:59 PM.
Layout, wiring, photos: docs/HARDWARE-SETUP.md

=== STILL OPEN FROM PACK-UP ===
1. Pi network. Ask Nick how pi-arm1 joins the venue WiFi (or a phone hotspot).
   Without network the laptop cannot reach the arm.
2. USB port names. Ask Nick to switch the follower/leader ports in the config to
   /dev/serial/by-id/... paths. On day 1 the leader moved to ttyACM2 after a re-plug.

=== REBUILD (about 10 min) ===
1. Clamp the arm at the table's front edge, turntable centre about 5 cm in from the edge.
   Lay the black paper: the first sheet flush against the base plate (photo 03).
2. Pillbox: latch tabs facing the arm, Sun on the arm's left, Wednesday straight ahead with
   its front edge 20.5 cm from the turntable centre. Sunday's front corner about 9.4 in
   (24 cm) from the table edge. Tape both ends (Sun/Sat). Skew doesn't matter: step 5 measures it.
3. Wiring, both arm boards: barrel power, USB-C to the hub, servo chain in the TOP socket,
   jumper on the USB-Servo pins. Hub into the Pi's lower blue USB 3 port. Pi power last.
   Read each power brick's voltage before plugging in (boards take 14 V max).
4. Power on. Check the Viam app shows pi-arm1 online. On the Pi: ls -l /dev/serial/by-id/
   Close the CONTROL tab before running scripts.
5. Register the box (2 touches):
     python armctl.py free 30          manual mode
     (rest the closed claw tip on MONDAY's lid, front edge, centred)
     python box.py mark mon
     (same on FRIDAY)
     python box.py mark fri
     python box.py fit                 refuses marks that are not 4 lids apart, or not level
     python armctl.py off
     python box.py show                every Mon-Fri stroke must print (an error = box out of reach: move it)
6. Test: open Wednesday by hand, then  python box.py stroke wed
7. Pill tray: put it about 33 cm from the turntable centre, 19 deg to the right (HARDWARE-SETUP.md),
   or re-teach:  python armctl.py teach tray_hover / tray_down  (manual mode, claw over the tray)
8. python app.py  ->  the page.

=== PACKING UP AT 5 PM ===
The white arm drops when torque cuts. Run  python armctl.py free 30  (manual mode),
fold it down onto the table by hand, then power off. The black leader is already limp.
```

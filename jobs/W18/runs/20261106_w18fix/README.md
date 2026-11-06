# W18 fix round 1 probe: run 20261106_w18fix (2026-11-06)

Round 1's fix (a) rests on something the review had not proven: that a DPI-unaware window's `WM_WINDOWPOSCHANGING` carries the physical target mapped through the monitor's two rects. This run measures it.

- `own_move_probe.py.txt`: the probe (Python ctypes, stdlib; a record, not a tool, so `.txt`). A thread in the named DPI context owns a popup and logs each `WM_WINDOWPOSCHANGING`. A per-monitor V2 thread moves it with `SWP_ASYNCWINDOWPOS`, the flags `PlaceLocked` uses, across all three monitors: each monitor's whole rect and two rects inside it, in both orders. No game, no lock, no display setting.
- `own_move_probe_output.txt`: its output on Liam's PC, four states: `unaware`, `system`, and each again `cloaked` (DWM-cloaked first, then shown: the game's state during a relocation; `cloak hr 0`, visible flag 1, so nothing reached a screen).

Monitors: DISPLAY1 at 150 %, DISPLAY2 at 125 %, the virtual display (DISPLAY10) at 100 %.

Result: in all four states the message matched the map within 1 px on every edge over every move, and exactly (0) for a whole-monitor move, the only move the main window makes. `kLogicalSlack` (1) covers it. An unaware context keeps a monitor's origin and scales its size; a system-aware one scales the origin too (DISPLAY10 3839,2160 is seen at 5759,3240), so the map reads the monitor's own rects and never derives a scale from a DPI.

Limit: this is a probe window, not the game. Proof c (the game on a scaled target) stays Liam's opt-in.

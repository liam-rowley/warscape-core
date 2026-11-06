# W18 review probe: run 20261106_w18review (2026-11-06)

Round 1's check of `LogicalRect` (`proxy/src/headless.cpp:110`): does `PhysicalToLogicalPointForPerMonitorDPI` convert a point outside the window?

- `p2l_probe.py.txt`: the probe (Python ctypes, stdlib; saved as `.txt` because it is a record, not a tool). It creates one never-shown `WS_POPUP` window under a DPI-unaware
  thread context, then asks from a per-monitor thread, as `PlaceLocked` does under `DpiScope`, and destroys the window. No game, no display setting, no lock.
- `p2l_probe_output.txt`: its output on Liam's PC. The window landed on DISPLAY1 (dpi 144): logical 100,100 300,300 is physical 150,150 450,450.

Result: a point inside the window or on its edge converts (`ok=1`); a point outside it is refused (`ok=0`, the point unchanged). Two same-sized rects have both corners of one inside the
other only when they are identical, so for a main window moving to a new target `LogicalRect` returns false and no logical rect is armed.

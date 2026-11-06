# W18 review round 2: run 20261106_w18r2 (2026-11-06)

A reviewer's own check of what the fix rests on, on Liam's PC. Never-shown windows only: no game, no lock, no display setting, nothing reached a screen.

- `own_move_probe_r2.py.txt`: the fix round's probe (`../20261106_w18fix/own_move_probe.py.txt`) with one addition, `WM_WINDOWPOSCHANGED` logged as well (`CHANGED`). `GuardProc` calls `OwnLocked` on that message too, and the fix round measured only `WM_WINDOWPOSCHANGING`.
- `own_move_probe_r2_unaware.txt`, `own_move_probe_r2_system.txt`: its output. Same monitor rects as the fix round; largest edge difference 1 over all moves, 0 for a whole monitor. `WM_WINDOWPOSCHANGED` carries the same rect as `WM_WINDOWPOSCHANGING` on every move, flags `0x421c` (neither `SWP_NOMOVE` nor `SWP_NOSIZE`), so the `ownChanged` path sees what the gate saw.
- `logicalrect_replay.py.txt`, `logicalrect_replay_output.txt`: `LogicalRect`'s calls in its order, with the context from `GetWindowDpiAwarenessContext(h)` rather than a constant: compare with both per-monitor contexts, set the context, `GetMonitorInfoW`, restore. An unaware window on DISPLAY1 or DISPLAY2 arms; a per-monitor window never does. `prev` is non-null every time.
- **Not expected from the proofs:** a system-aware window arms on DISPLAY10 too, the 96 DPI display (it sees 5759,3240), so "a 96 DPI target: nothing to arm" holds only for an unaware or per-monitor window. No proof log has an `own move armed` line, so the game's window is not system-aware; the logs cannot say which of the other two it is.

Limit: Python calling the same Windows functions, not the compiled `LogicalRect` and not the game. The compiled path has still never returned a logical rect anywhere.

# W6 review

## Round 1 (2026-11-03, branch job/W6 at fe92baa)

**Verdict: merge.**

The two should-fix items were fixed on the branch by this review (be8276d, f190ba2). No blocker is left; the later items are backlog row B58.

### Machines
- `python3 wsc.py gates` on fe92baa: 13 ok, 1 warn (the POSIX hook test, skipped on Windows), 0 failed. `gates --fast` on f190ba2: 13 ok.
- CI on fe92baa: `gates` (push and pull request runs, with `proxy` and `harness-windows`) green; `policy` skipped on the draft, as designed.
- `build.sh all` in CI's image (`wsc-w6-build:local`, null game, `WSP_BUILD_ID=w6-review`) on f190ba2: the DLL built and all 15 host suites passed,
  `test_gesture` 784 checks, `test_ui_core` 212 and `test_ui_rml` 25 unchanged (verified 2026-11-03, run w6-review). `repro` and `smoke` were not
  re-run locally: CI's `proxy` job ran them on fe92baa, and the review's fixes touch only a header's maths and a host test.

### Against the brief
- All seven deliverables are present: the pure headers, a gesture stage in W2's one subclass (with no second `SetWindowLong`, linted), the overlay in
  W2's `hk_Present` before `Frame`, `GestureAdapter` with `CameraRead` and `OrdersGroundAt`, the ctl verb with parser cases, `controls.gestures` in the
  null game's tables and ini, the docs, and `VERSION` 0.13.0. That is the number the brief allots; main is at 0.10.0, and W3, W4 and W5 are still open.
- Deviations: each is named in the report with a reason. The largest is that gestures need `ui.enabled=1`, the brief's W2 sharing case, handled
  as the brief says (stop rather than change W2) and filed as B57. That is acceptable.
- Kill criteria are respected. No game names appear in core files, and the provenance links are allowed.

### Risk-first reading
I picked `proxy/src/gesture.cpp` and the `ui_host.cpp` additions, because they run in the game's window procedure, in Present (device state) and in
engine calls (`OrdersGroundAt`). The checks:
- The stage is fully inert when off: `GestureMessage` returns before the lock when `!s_on`, and `GesturePresent` returns at once.
- Key messages pass, and only mouse messages inside a gesture are swallowed.
- The preview runs inside a `D3DSBT_ALL` state block. The render target and depth surface are restored by hand, because a state block does not
  capture them.
- The commit runs off the lock on the Present thread.
- `CameraRead` checks offsets and readability, and refuses a pose that is not finite.

None of this is wrong for the consumer's first walk. The smaller issues are in B58.

### Findings

**should-fix (fixed here)**
1. `proxy/src/gesture_math.h:188` (fe92baa): `FootDepth` returned a unit's own depth unfloored, but its comment said "(the provenance's rule)". The
   provenance (`block_math.py`, empire-remastered `gesture_math.h` `Footprint`) draws `max(4, depth or width / 4)`.
   - How to see it fail: run every `foot` line of empire-remastered `rml_mod/src/tests/gesture_vectors.txt` through `Footprint`. Line 53 (depth 3.03)
     misses by about 0.48 m at all four corners, failing 4 checks. The report did not name this as a deviation.
   - Fixed in be8276d: the floor is restored, and the comment cites the vector.
2. `proxy/tests/test_gesture.cpp:68-87` (fe92baa): only 18 of the 130 applicable vector lines were inline. The brief asks for `gesture_vectors.txt` to
   be ported, and the sample missed finding 1. The report says a permission refusal stopped the copy.
   - Fixed in f190ba2: the file is copied verbatim to `proxy/tests/gesture_vectors.txt`. The test reads it through `tk::ReadFile("tests/...")` and
     checks every `pt`, `move`, `rot` and `foot` line under both bearing signs (48, 24, 24 and 24). `ang` and `ord` lines (functions not ported) are
     counted and skipped, and a count check fails on a truncated file. `test_gesture` went from 416 to 784 checks.

**later** (backlog B58, on this branch)
3. `gesture.cpp:250-261`: the adapter's callbacks (`scene`, `selection`, `cameraRead`, `groundAt`, `placeable`) run under `s_lock`, a non-re-entrant
   SRW lock. A callback that sends a message to the game window on the window thread re-enters `GestureMessage` and hangs. The null adapter does not
   do this, and the consumer should not; a re-entry guard would make it impossible.
4. `gesture_feed.h:28-35`: `Classify` treats `WM_KILLFOCUS` and `WM_ACTIVATEAPP` (deactivate) as focus loss, but not `WM_CAPTURECHANGED`. The
   no-button move rule recovers a stuck gesture, one move late.
5. `gesture.cpp:332-335`: `ctl gesture press` sets `s_ctlHeld` even when the press was inert. The next `ctl gesture move` then sends `MK_LBUTTON`,
   which the game reads as a plain drag (a box select during a headless walk).
6. `gesture.cpp:174`: a `D3DSBT_ALL` state block is created and released on every preview frame. That is cheap enough for a preview, but it could be
   kept across frames and rebuilt on `Reset`.
7. `build.sh smoke` only proves the layer starts and stays inert. No launch walks `ctl gesture press/move/release` with a commit readback, because the
   stand-in exe has no window. The end-to-end ctl path is first exercised by napoleon J29.

### For napoleon J29
The list in the report's "What napoleon J29 must do" stands, with one addition: footprint depths below 4 m now draw 4 m deep, as in the provenance. If
the game's measured depths should draw true, that is a core change: add a backlog row, and do not patch the core.

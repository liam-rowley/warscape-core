# W6: The gesture layer in the proxy (napoleon J29's core half)

Model: Opus, reason: DLL work in a 32-bit process across the window procedure, the D3D9 Present path and input, with a pure state machine ported and
re-proved by host tests (napoleon-remastered J29's brief recommends Opus for this half). Budget about 150 tool calls for the core part; at the cap, stop,
commit, report what is left. Napoleon J29 keeps about 200 more (adapter, frontage facts, pick and walk proof, bindings, 20 acceptance passes, Liam's feel sign-off).

## What
The game-agnostic half of napoleon-remastered J29 (its brief, `jobs/J29/brief.md` on that repo's `main`, is the full specification: read
"The route, and why", "Behaviour" and "The core job" first). Alt+drag moves the selected units to a drawn line, Alt+Ctrl+drag rotates them in place, a preview
is drawn while the button is down, and the orders go out once on release. The game supplies the selection and the orders; this job is everything else.
Provenance (read-only evidence, never edited): `empire-remastered` `rml_mod/src/gesture_sm.h`, `gesture_math.h`, `gesture_feed.h`, `gesture_group.h`, `gesture_v4.h`,
`gesture_v5.h`, `rml_mod/src/tests/gesture_test.cpp` with `gesture_vectors.txt`, and `rml_mod/docs/runs/20261026_controls_v5/README.md`.
**Not ported, on purpose:** the depth-prepass ground pick (`gesture_ground.h`), the camera vertex-shader capture (`gesture_cam.h`) and the engine's per-man marker call
(`gesture_marker.h`); the pick here is geometry from a readable camera.

1. **Pure headers, `proxy/src/gesture_*.h`, no Windows types:** the state machine (Idle, Pending, Active, Drain, with the transition table in the header comment),
   the math (pick ray from camera position, target, vertical field of view and client aspect; ray-plane hit with refinement against `GroundAt`; world-to-screen
   projection; line layout across the drawn line with per-unit frontage clamps; rotate by horizontal travel as an absolute orbit angle), the feed (messages to events,
   the Ctrl switch with its pose rebase), the per-unit plan (rectangle corners draped on the ground, facing tick, refused units marked) and the grouped-selection case.
   Host tests `proxy/tests/test_gesture.cpp` port Empire's `gesture_test.cpp` and `gesture_vectors.txt` (state machine, math vectors, the Ctrl switch, the v4 and v5
   cases, the drain rules) and add vectors for the line layout, the ray pick and the projection round trip, a drag shorter than the threshold, Escape, right press,
   focus loss, a move without the button, and "key messages are never swallowed" (Alt+F4 and Alt+Tab among them). Only mouse messages inside a gesture are swallowed.
2. **The window-message hook, one shared subclass.** The layer sits in the order RmlUi panels, then gestures, then the game. W2 (`job/W2`, open as PR #17, not merged
   when this brief was written) subclasses the window procedure for RmlUi input (`proxy/src/ui_host.cpp` `Subclass`/`WndProc`, `UiDecide` in `ui_core.h`). This job builds
   on W2's hook once W2 is merged: start from `main` with W2 in it, add a gesture stage behind the RmlUi stage in the same `WndProc`, and add no second
   `SetWindowLong` of its own. If W2 is still unmerged when this starts, stop before the first code commit and report (do not build a rival subclass; see the W2 sharing case below).
   The gesture stage is inert when the game has no `GestureAdapter` or `controls.gestures` is off, and passes every message the layer does not own.
3. **The D3D9 footprint overlay** in the Present path (lines and translucent quads from the plan, drawn with `DrawPrimitiveUP` before the real Present, device state saved
   and restored, nothing drawn when no gesture is active), chained beside the existing Present hook in `dev.cpp` and W2's frame pass (draw order: game, gesture
   preview, RmlUi panels). Refused units draw red.
4. **The adapter seam** in `proxy/src/adapter.h` (a `const GestureAdapter* gesture;` beside `orders`, `nullptr` = no gestures): `CameraRead` beside `CameraSet`
   (position and target from the camera mode, through `CameraAdapter`, so the layer reads the pose the same way the setter writes it), `GroundAt(x, z)` over the game's
   ground projector, the selection feed (ids, positions, facing, width, left-to-right order), the per-unit frontage clamps, the click and drag thresholds, the key
   bindings as data (modifier sets for move and rotate), the pivot offset (default 0), and the order commit called once, on the engine thread, from the Present tick.
5. **A ctl `gesture` verb** (`proxy/src/devcore.h` grammar and `dev.cpp`; `gesture press|move|release|cancel` with client x y and the modifier set, `gesture plan`,
   `gesture info`) that feeds the **same entry point as real window messages**, so a headless walk needs no physical mouse. The result is the plan and the counters
   (passed, swallowed, orders sent, why inert: ineligible scene, empty selection, deployment, no adapter, config off). Rules 77 and 78 apply: no `ok` without a readback.
   Parser cases go in `proxy/tests/test_dev.cpp`.
6. **Config key** `controls.gestures` (working name; boolean, default on in release, off in the null game's ini unless a test turns it on) as a `config_keys` row in the
   null game's registry (`proxy/tests/null_game/registries/config_keys.jsonl`, the generated `tables.h` and `nullgame.ini`), plus the null game's rows and a null `GestureAdapter`
   (a fixed camera, a flat `GroundAt`, a small fake selection) so `build.sh all` and `smoke` exercise the layer without a game.
7. **Docs and release:** `docs/PROXY_GESTURES.md` (the contract: what the adapter provides, the ordering with RmlUi panels, the ctl verb, the config key, what is inert and why),
   a pointer from `docs/CONSUMING.md` ("The proxy, the harness and the save tools"), `VERSION` at the next free minor. The registry rows for any new tool file; no CHANGELOG exists.

Files this job touches: `proxy/src/gesture_*.h` (new), `proxy/src/adapter.h`, `proxy/src/camera.h`/`camera.cpp` (`CameraRead`), `proxy/src/dev.cpp`, `proxy/src/devcore.h`,
`proxy/src/ui_host.cpp` and `ui_core.h` (only to add the gesture stage behind the RmlUi stage, once W2 is merged; no behaviour change for RmlUi), `proxy/src/dllmain.cpp`/`hooks.cpp`
(init), `proxy/tests/test_gesture.cpp` (new), `proxy/tests/test_dev.cpp`, `proxy/tests/null_game/` (adapter, config rows, `tables.h`, ini), `proxy/tools/build.sh` (the new test),
`docs/PROXY_GESTURES.md`, `docs/CONSUMING.md`, `VERSION`. No game names in core files: say "the game" or "a game" (`tests/test_moved_tools.py` `NoGameNames` bans them);
links to `empire-remastered` as provenance are allowed.

## Sequencing
Depends on W2 (`depends_on` in its row): W2 owns the first subclass of the window procedure and the Present-path structure W6 extends. Do not start the build until W2 is
merged to `main`; base `job/W6` on that `main`. The DLL inputs change, so the consumer re-runs its 20 acceptance passes (rule 79) on the build id it pins.

## The consumer's part (not here)
The game's `GestureAdapter` (camera read offsets with their site rows, the selection feed, thresholds), the frontage-clamp facts, the pick proof and the move and rotate walk on
`land_40` and `siege_small`, the hotkey rows `mod.gesture.move` and `mod.gesture.rotate`, the 20 acceptance passes (rule 79), the pin bump, and Liam's feel checklist all run under
napoleon-remastered J29 on `job/J29`, after Liam tags this. The core's own acceptance is host tests green, null-game `build.sh all`, `repro` and `smoke`, and `docs/PROXY_GESTURES.md`.

## Kill criteria
- J29's core-applicable ones: the window procedure cannot be subclassed without a second hook (stop and ask Liam); a core part needs engine reverse engineering or a write to game
  memory beyond the adapter seam (stop, record it open, propose a job); a pick or projection round trip off by more than 1 px in the host test after the maths is checked twice
  (stop that line after about 30 calls and report the error table; do not fall back to a depth-prepass pick); a crash or hang in the null game's smoke with the layer on, twice
  for the same cause (drop the overlay's draw and report).
- **The W2 sharing case:** the gesture stage cannot share W2's window-procedure hook without changing W2's behaviour (an RmlUi test in `test_ui_core.cpp` or `test_ui_rml.cpp`
  must change to stay green, or the order RmlUi, gestures, game cannot hold): stop and report. W2 is not edited here, and no second subclass is installed.
- CI red after 3 attempts for a cause in the change: stop and report.
- **Version collision:** on `origin/main` `VERSION` is 0.9.0. Claimed so far: W3 0.9.1, W2 0.10.0, W5 0.11.0, W4 0.12.0; W6 would take 0.13.0. Re-read `origin/main` `VERSION` and
  the open `job/*` branches before the last commit; the second to merge takes the next free number and merges `main` (never rebase). Say in the report which number was taken.

## Finish
Report in `jobs/W6/report.md` (what was built, the host test list, the ordering proof with W2, deviations, open questions, what napoleon J29 must do), then
`wsc reg set jobs W6 status=review report=jobs/W6/report.md` (`python3 wsc.py`). Liam merges and tags the core; stop after the PR.

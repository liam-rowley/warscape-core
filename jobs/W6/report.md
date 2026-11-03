# W6 report: The gesture layer in the proxy

The orchestrator wrote this from the build agent's hand-back. The build ran as a subagent, and the harness refuses a subagent's Write of a
report file, so the parent writes it. The Claude-Session is the same as the build's.

## What was built
- **Pure headers with no Windows types** (`proxy/src/gesture_*.h`, namespace `wsp::gest`):
  - `gesture_sm.h`: the state machine (Idle, Pending, Active, Drain), with the transition table in the header comment. It is ported from
    empire-remastered `gesture_sm.h`, with the key bindings as data: a press starts a gesture only when its modifier set is exactly `moveMods`
    or `rotateMods`.
  - `gesture_math.h`:
    - ported: the block maths, the v3 to v5 rotate (`DxAngleSigned`, `RotatePivotFwd`, `OrbitPose`), footprints and `QuadsOverlap`;
    - new here: `CameraVP` (LookAtLH x PerspectiveFovLH from the position, the target, the vertical fov and the client aspect), `PickGround`
      (a plane hit refined against `GroundAt`) and `LineLayout`.
  - `gesture_feed.h`: the Win32 message numbers written out as constants; `Feed()`, which turns messages into events and passes every key
    message; `Planner`, which handles the Ctrl switch and rebases the pose; and `ParseGestureArgs`.
  - `gesture_plan.h`: per-unit rectangles draped on the ground, the facing tick, refused marks, `OrdersOf`, and the XYZRHW overlay vertices.
  - `gesture_group.h`: the grouped-selection merge, ported.
- **The driver**, `proxy/src/gesture.cpp` and `gesture_host.h`. It runs as a stage in W2's single window subclass and Present chain, and
  installs no hook of its own:
  - A press is eligible when the adapter reports a gesture scene and a non-empty selection, the camera can be read, and there is ground under
    the cursor.
  - A move updates the plan, and the Ctrl switch rebases the pose.
  - A release queues the accepted orders, and the next Present calls the adapter's `commit` once.
  - The preview is drawn with `DrawPrimitiveUP` inside a `D3DSBT_ALL` state block, and the render target and depth surface are restored.
    Nothing is drawn unless a gesture is Active.
- **`ui_host.cpp`**, additions only:
  - `Subclass` passes the window to the stage.
  - `hk_Present` runs `GesturePresent` before `Frame`.
  - `WndProc` runs `GestureMessage` after `UiDecide`, with `mouseToEngine = r.to & kToEngine`. Then it swallows the message, clears the left
    button, or replays the click.
  - `WM_ACTIVATEAPP` and the default branch feed focus loss and the stage's probe message to the stage.
  - The DirectInput hooks blank the mouse buttons when `UiBlankDiButtons(s) || GestureOwnsMouse()`.
  - `UiInit`, `UiOnDirect3DCreate`, `UiDecide` and `StartRml` are unchanged.
- **The adapter seam:**
  - `adapter.h` adds `GestureAdapter`: scene, cameraRead, groundAt, selection, an optional placeable, commit, dragPx, shortDragM, moveMods,
    rotateMods, pivotFwdM, rotGain and rotSign. `GameAdapter::gesture` is its new last member.
  - `camera.cpp` adds `CameraRead(posOff, targetOff, pos, target, why)`, with the same chain and vtable check as `CameraSet`.
  - `orders.cpp` adds `OrdersGroundAt(x, z, y, why)`. It makes the same projector call as `MoveLocked`, and runs on the engine or Present
    thread only.
- **The ctl verb** `gesture press|move|release <x> <y> [mods] | cancel [esc|right] | plan | info`, with its grammar in `devcore.h` and its
  dispatch in `dev.cpp`:
  - Press, move, release and cancel post real window messages to the subclassed window.
  - Each result carries a readback: the counter changes, the phase and kind, the plan, and, for a release that committed, the adapter's answer
    from the next Present.
  - `info` answers even when the layer is inert, and says why. A probe message lets the window thread ask the adapter for the scene, the
    selection and the camera.
- **Config and the null game:**
  - A `controls.gestures` row (off) in `proxy/tests/null_game/registries/config_keys.jsonl`, with `generated/tables.h` and `nullgame.ini`
    regenerated.
  - A null `GestureAdapter`: a fixed camera at (0, 60, -80) looking at the origin with a 70-degree fov, flat ground, three units, and a
    commit that only counts.
  - `GestureInit` runs in `dllmain.cpp` before `UiInit`.
  - `build.sh smoke` has two new launches: gestures with the RmlUi host, where the layer starts, and gestures without it, where the layer is
    inert and no UI hook is installed.
- **Docs and release:** `docs/PROXY_GESTURES.md`, a pointer from `docs/CONSUMING.md` ("The proxy, the harness and the save tools"), `VERSION`
  0.13.0 and backlog row B57.

## Evidence
- **Build, host tests, repro and smoke**, verified 2026-11-03 on commit 3f0b076. The DLL inputs are unchanged at the next commit, 9af9adf,
  which changes only the jobs row.
  - How it ran: in CI's pinned image (`ubuntu@sha256:fe8156…`) with CI's packages plus wine, committed locally as `wsc-w6-build:local`. The
    core root was mounted, with `WSP_GAME_ROOT=/src/proxy/tests/null_game` and `WSP_BUILD_ID=w6-local`.
  - `build.sh all` built `d3d9.dll` with sha256 `8329d98c6642b9cb9a6619464a73ebc18521ab58b45fb5cbd7aa21474d187333`. It imports only
    advapi32, dbghelp, kernel32, msvcrt and user32, and all its exports are present.
  - Host tests, checks per suite, all with 0 failed: test_camera 17, capture 63, config 77, console 57, crash 18, dev 199, display_guard 227,
    **gesture 416**, guard 81, orders 732, patch_engine 166, sha1 135, **ui_core 212**, **ui_rml 25**.
  - `build.sh repro` printed "identical from another path".
  - `build.sh smoke` printed "passed (7 launches under wine, 2 dumps)".
- **Pick and projection** (test_gesture), verified 2026-11-03 on commit 3f0b076. The brief's kill criterion is 1 px, and nothing came close:
  - For 54 cursor points on a 1920x1080 client with a 70-degree camera, every picked point projects back within 1e-6 px.
  - On a 5-degree slope, the draped ground point lands within 1 px, and twelve refinements bring the residual under 5 cm.
  - The world to pixel to pick round trip is within 1e-6 (metres and pixels).
  - Half the vertical fov lands exactly on the top edge of the client.
- **Key messages are never swallowed**, verified 2026-11-03 on commit 3f0b076:
  - 792 key messages pass in the idle, pending, active and drain phases: 6 key message types x 11 keys (F4, Tab, Esc, Ctrl, Alt and others)
    x 3 modifier sets.
  - Alt+F4 and Alt+Tab pass in the middle of a drag, and leave the gesture as it was.
- **Gates:**
  - Verified 2026-11-03 on commit 75168c3: "gates: 13 ok, 1 warn, 0 failed". The warn is the hook test, which needs POSIX and was skipped.
  - On 9af9adf the only failures were the missing report file, which this commit adds.
- **Not run here:** the real game (no PC test; the PC game lock and `C:\napoleon_remastered_pc` were not touched). CI runs on the push.

## Deviations from the brief and why
1. **Gestures need `ui.enabled=1` as well as `controls.gestures=1`.**
   - The first attempt installed the host's hooks whenever gestures were on. That broke lines 131 to 134 of `test_ui_core.cpp` (the lints
     "ui.enabled=0: UiInit returns before any hook" and "no CreateDevice hook with the UI off"). That is the brief's W2 sharing case, so it was
     reverted.
   - No W2 test is changed, and there is no second subclass. The stage rides on the host only while the host is on.
   - `GestureInit` logs "the RmlUi host is off (ui.enabled=0)", and `gesture info` says the same.
   - Backlog B57 asks Liam whether W2's rule should be relaxed.
2. **Vectors:** an 18-line sample of `gesture_vectors.txt` is inline in `test_gesture.cpp`: one camera, 6 points, 2 moves, 3 rotates and 4
   footprints, with both bearing signs. The permission system refused a copy of the whole file out of empire-remastered.
   - The `ang` (sweep angle), `ord` (minimum-move order filter) and linear-Z pick lines are not ported, because the functions they test are
     not ported: from v3 on, rotate works by horizontal travel, and there is no depth prepass.
3. **Also not ported:** the v1c and v2 sweep and aim modes, `ResolveBlock` and `ResolvePerUnit` (no reach search, as J29 says), the sound
   gate, the cursor rule and the deployment route.
4. **Line layout:**
   - The core works out the left-to-right order from the unit positions across the new facing. The order the units arrive in only breaks
     ties.
   - When the line is re-laid, each block keeps its area (depth x width).
   - Each block's front edge sits on the drawn line. `frontRef` says whether a unit's order point is its front middle or its centre.
5. **`CameraRead` takes the camera mode's offsets as arguments**, and the game's `cameraRead` passes them. `CameraAdapter` is not extended:
   the setter's table stays as it is, and the offsets are only the gesture layer's concern.
6. **ctl `cancel` takes only `esc` or `right`.**
   - Sending `WM_ACTIVATEAPP` to a game could pause it, so the host tests cover focus loss instead.
   - Under ctl, the modifiers are injected for the stage only, so a replayed click reaches the engine as a plain click.
   - `cancel esc` really does reach the game.
7. **The local build used a hand-written `docker run` that mounts the core root**, because `build.sh --docker` cannot mount the null game
   inside the repo (B16).
8. **Added, not in the brief: the DirectInput mouse buttons are blanked while a gesture holds them**, because otherwise the engine also sees
   the press through DirectInput. It is a pure OR added to W2's condition, and it is false whenever the layer is inert.

## Open questions
- **B57:** should the host hook in with `ui.enabled=0` when gestures are on? Until that is decided, a game that ships gestures must also ship
  `ui.enabled=1`.
- **The ordering proof with W2:**
  - `test_ui_core.cpp` and `test_ui_rml.cpp` are unchanged and green (212 and 25 checks).
  - `test_gesture.cpp` lints that `ui_host.cpp` has exactly one `SetWindowLong` statement, and that `gesture.cpp` has no `SetWindowLong`,
    `VtableHook` or `IatHook`.
  - The same lint checks the order of the calls:
    - in `WndProc`, `UiDecide`, then the gesture stage, then `Engine(...g.wp...)`;
    - in `hk_Present`, `GesturePresent` before `Frame`;
    - W2's `if (!K.enabled) return;` is untouched.
  - In behaviour, a press that RmlUi took never reaches the gesture stage (a feed test). When the layer is inert, every added call returns at
    once, with `wp` unchanged.
- **What napoleon J29 must do:**
  - Pin 0.13.0, and add the 14th `GameAdapter` initialiser (`&kGesture` or `nullptr`).
  - Add a `controls.gestures` config_keys row (default and release true, per J29's brief), and add `ui.enabled=1` to `ctl.launch.keys`.
  - Keep `dev.camera` and `dev.orders` on, because `CameraRead` and `OrdersGroundAt` need them.
  - Write the `GestureAdapter`:
    - `scene`: land or siege, Deployment, and Ineligible for naval and campaign;
    - `cameraRead`: `CameraRead(0x8, 0x14, …)` with a fov of 70;
    - `groundAt`: `OrdersGroundAt`;
    - `selection`: `OrdersSelection` plus `OrdersUnit`, filtered by `UnitOrderable`. Bearing, width, depth and `frontRef` come from the J28
      facts, and the frontage clamps from the measured frontage facts;
    - `placeable`: `CheckMove`;
    - `commit`: `OrdersMove` for each unit;
    - the thresholds, and the bindings Alt = 1 and Alt+Ctrl = 3.
  - Run the pick proof against `BackProjectPosition`, and the move and rotate walk.
  - Find out whether the game reads mouse buttons from window messages or from DirectInput. A replayed Alt+click arrives by window messages
    only.
  - Add the hotkey rows, run the 20 acceptance passes (the DLL inputs changed), and get Liam's sign-off on the feel.
- **For later:**
  - Is keeping each block's area good enough for the preview, or should a game give a depth for each width?
  - The rotate pivot stays at 0 m until Liam signs off the feel.
  - Does `ctl gesture cancel esc` open the game's menu during the walk?

# The proxy's gesture layer (W6)

Battle gestures inside the proxy DLL: the move binding (Alt in the provenance) plus a left drag moves the selected units onto the line the
drag draws, the rotate binding (Alt+Ctrl) turns them in place by horizontal mouse travel, a footprint preview is drawn while the button is
down, and the orders go out once, on release. The game supplies the selection, the camera, the ground and the orders through a
`GestureAdapter`; this layer is everything else. Sources: `proxy/src/gesture_*` (pure headers, no Windows types) and `gesture.cpp`
(the driver). Host tests: `proxy/tests/test_gesture.cpp` (the headers), `test_dev.cpp` (the ctl grammar). Provenance (read-only):
empire-remastered `rml_mod/src/gesture_{sm,math,feed,group,v4,v5}.h` and its test `gesture_test.cpp` (ported with a sample of
`gesture_vectors.txt`); its depth-prepass pick, camera shader capture, engine markers, reach search and sound gate are not ported.

## Keys (rows in the game's config_keys registry; a game without them has no gestures)
| key | meaning |
|---|---|
| `controls.gestures` | 1: the layer starts when the adapter has a `GestureAdapter` and the RmlUi host is on. 0: every message passes. A game ships it on; the null game ships it off. |
| `ui.enabled` | the RmlUi host ([PROXY_UI.md](PROXY_UI.md)). The layer has no hook of its own: it is a stage in the host's window subclass and Present chain, and with `ui.enabled=0` the host hooks nothing (W2's rule, linted in `test_ui_core.cpp`), so the layer is inert and says so. |

## Order and ownership
- **One subclass, one Present chain.** `ui_host.cpp` subclasses the game window once (`SetWindowLong`) and hooks `Present` once. Its window
  procedure decides RmlUi's routing first (`UiDecide`, unchanged); a mouse message RmlUi gives to the engine then goes to the gesture
  stage (`GestureMessage`), which passes it, swallows it, clears a move's left-button flag, or replays a plain click; then the game.
  Order: **RmlUi panels, then gestures, then the game**. A press RmlUi took never reaches the gestures (over a panel nothing starts).
- **Keys are never swallowed.** The stage only observes key messages (Esc cancels, a modifier change switches move and rotate); every
  key message reaches its owner unchanged, Alt+F4 and Alt+Tab included (`test_gesture.cpp` feeds 792 key messages in every phase).
  Only mouse messages inside a gesture are swallowed: the press, the release, and a right press that cancels with its release.
- **DirectInput.** While a gesture holds the buttons (any phase but idle), the host's DirectInput hook blanks the mouse buttons as it does
  for RmlUi, so the engine never sees the press through that path either. A replayed click goes by window messages only.
- **Re-entry passes, it never waits.** The adapter's callbacks run under the stage's lock (an SRW lock, not re-entrant). `s_lockOwner` holds the thread that
  owns it; a message that reaches `GestureMessage` (or `GestureSetWindow`) from that same thread, because a callback sent one to the window, passes to the game
  untouched (no state change; `ReenteredBy` in `gesture_host.h`), is counted and shows as `reentered` in `gesture info`, with one log warning for the first.
  DirectInput reads `s_ownsMouse`, a word `GestureMessage` publishes under the lock after every message it feeds, not the machine's fields.
- **Draw order in Present:** the game's frame, then the gesture preview (`GesturePresent`), then the RmlUi panels (`Frame`).

## Behaviour (`gesture_sm.h` has the transition table)
- A left press whose modifier set is exactly the move set or the rotate set starts Pending, if the adapter says the scene is eligible,
  the selection is not empty, the camera is readable and the cursor is over the ground; otherwise it passes. Past the drag threshold
  (`dragPx`) it is Active; a release before that replays a plain click at the press point.
- **Move** (`LineLayout`): the press and the cursor are the ends of a line on the ground. The units keep their left-to-right order across
  the facing, each takes an equal share of the line clamped to its `[minWidth, maxWidth]` (packed edge to edge, centred, when the minimums
  add up to more than the line), the front edge of every block on the line, facing the line's normal on the side the selection faces;
  depth keeps the block's area. A line shorter than `shortDragM` keeps the widths and facings and moves the block's centre to the press point.
- **Rotate**: the selection turns rigidly about its centre plus `pivotFwdM` ahead (default 0: in place); theta = `rotGain` degrees per
  1000 px of horizontal travel at a 3840-wide client since the rotate began (absolute, so travelling back undoes it exactly).
- **Switch**: the modifier set changing mid-gesture (a key, or the set read on a move) switches move and rotate; the pose so far becomes the
  new base (move then rotate turns the laid-out line where it stands; rotate then move carries the turned block on by translation).
- **Cancel**: a right press, Esc, focus loss (`WM_ACTIVATEAPP` 0, `WM_KILLFOCUS`, or `WM_CAPTURECHANGED` unless the window gaining the capture is the game window itself: the stage
  calls no `SetCapture`, so a capture change is another window taking the mouse and the release may be lost) or a move without the button; after a right press or Esc
  the rest of the press is swallowed (Drain), so the engine never sees a lone release.
- **Release**: the plan at the release point; refused units (no ground under the target, or the adapter's `placeable` says no) are drawn
  red and skipped; the rest go to the adapter's `commit` once, from the next Present tick.

## The pick and the preview (`gesture_math.h`, `gesture_plan.h`)
The camera is geometry: `LookAtLH(pos, target)` x `PerspectiveFovLH(fovY, client aspect)` from the adapter's `cameraRead`. A cursor pixel
is a ray (D3D9 pixel centres); it meets the plane through the selection's mean height, then three refinements re-cut it at the ground
height under the hit (`groundAt`). The answer is on the ray, so it projects back onto the cursor (host test: under 1e-6 px for 54 points;
the draped point under it within 1 px on a 5 degree slope). The preview is each target's rectangle with every corner at the ground height
under it, plus a 3 m facing tick, projected with the same matrices and drawn with `DrawPrimitiveUP` (XYZRHW + diffuse, alpha blended,
no depth test) inside a `D3DSBT_ALL` state block with the render target and depth surface restored; nothing is drawn when no gesture is Active.
That is one state block per drawn preview frame, as the RmlUi pass; kept blocks would have to be released before every Reset.

## The adapter (`GestureAdapter` in `proxy/src/adapter.h`; `GameAdapter::gesture`, nullptr = no gestures)
| member | what the game gives |
|---|---|
| `scene(why)` | `Eligible`, `Deployment` (inert: deployment orders do not walk in the first consumer) or `Ineligible` (campaign, naval, menus). |
| `cameraRead(cam, why)` | eye, look-at target and vertical field of view; the core's `CameraRead(posOff, targetOff, ...)` reads them from the camera mode `CameraAdapter` finds (same chain and vtable check as `CameraSet`; needs `dev.camera`). |
| `groundAt(x, z, y)` | the ground height; the core's `OrdersGroundAt` calls the projector the move order uses (needs `dev.orders`, engine or Present thread). |
| `selection(units, why)` | the orderable selected units: id, order point (centre, or front middle with `frontRef`), y, bearing (0 = +z, clockwise from above), width, depth, frontage clamps. `gesture_group.h` merges a grouped selection if the game needs it. |
| `placeable(order, why)` | optional: would the game refuse this target? |
| `commit(orders, n, why)` | called once per release from Present with the accepted orders; returns how many went out. |
| `dragPx`, `shortDragM` | the click and drag thresholds (defaults 6 px, 3 m). |
| `moveMods`, `rotateMods` | the bindings as modifier sets (1 Alt, 2 Ctrl, 4 Shift), matched exactly (defaults Alt, Alt+Ctrl). |
| `pivotFwdM`, `rotGain`, `rotSign` | the rotate pivot offset (0), gain (225) and sense (+1). |

The callbacks run on the window thread (presses, moves) and on the Present thread (commit, the preview's camera read); the first consumer
proved those, and its Lua pump, are one thread. The ctl thread never calls the adapter.

## The ctl verb (`gesture_feed.h` `ParseGestureArgs`)
`gesture press|move|release <x> <y> [none|alt|ctrl|shift joined by +]`, `gesture cancel [esc|right]`, `gesture plan`, `gesture info`.
x y are client pixels. press, move, release and cancel send the same window messages real input sends (`SendMessageTimeout` to the
subclassed window), so they take the RmlUi stage and the gesture stage like a mouse; the modifier set is injected for the stage only
(the engine reads the real keyboard, so a replayed click is a plain one). `press` answers `"held": true|false`: true only if the stage took the press (phase Pending or Active). A press it did not take (inert, over a panel,
eligibility refused) went to the game as a real press; the verb leaves it there (send `release` as for any click), `last_why` says why, and a following `move`
is a plain cursor move, not a drag. Every result is a readback (rules 77, 78): the counters' delta
(passed, swallowed, passed without the button, presses, inert presses, begins, switches, cancels, replays, commits, orders sent and
refused), the phase and kind after, the plan (per unit: target, width, depth, refused and why, draped corners) and, for a release that
committed, the adapter's answer from the next Present (no Present within the timeout = failed). `gesture info` answers even when the layer
is inert: why (config off, no adapter, the RmlUi host off, the plan) and, through a probe message the window thread answers, the scene,
the selection count and the camera (so "ineligible scene", "deployment", "empty selection" come from the game's own answers).

## What is inert, and why
No `GestureAdapter`, `controls.gestures=0`, `ui.enabled=0` (or the host could not start), or the guard's pass-through plan: no stage runs,
every message passes, nothing is drawn. With the layer on, a press passes untouched when the scene is ineligible or in deployment, the
selection is empty, the camera cannot be read or inverted, or the cursor is over the sky; `gesture info` and the counters say which.

## The null game
`proxy/tests/null_game/proxy/null/adapter.cpp` has a null `GestureAdapter` (a camera 60 m up and 80 m back with 70 degrees vertical, flat
ground at 0, three units 30 m apart, a commit that only counts); the ini ships `controls.gestures=0`. `build.sh smoke` launches it with
gestures and the host on (the layer starts) and with the host off (inert, and no UI hook goes in).

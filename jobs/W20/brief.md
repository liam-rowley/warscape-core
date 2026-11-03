# W20: UI host and gesture driver hardening

Model: Sonnet, reason: none needed (Sonnet is the default). Small, local fixes in two drivers whose decisions are already pure and host-tested (`ui_core.h`,
`gesture_feed.h`, `gesture_sm.h`); each fix gets a pure function or a source lint. No reverse engineering, no new hook, no PC. Budget about 100 tool calls
(the C++ host tests may only run in CI if the session has no g++/MinGW; the optional smoke step e is capped separately). At the cap, stop, commit, and
report what is left.

## Goal
Backlog B53 (from the W2 review, `jobs/W2/review.md` "later") and B58 a to e (from the W6 review, `jobs/W6/review.md` findings 3 to 7). None blocked the
consumer's first walk; each is a race, a hang, a stray drag or a cost the real game would show first:
- **B53.** `ui_host.cpp` `hk_DIState`/`hk_DIData` copy `s_route` (a 12-byte struct) without the lock while the window thread writes it under `s_cs`; a torn
  read can blank or pass one DirectInput frame wrongly. `WM_ACTIVATEAPP` clears the button masks but not `s_rmlOwner`.
- **B58 a.** The adapter's callbacks (`scene`, `selection`, `cameraRead`, `groundAt`, `placeable`) run under `s_lock`, a non-re-entrant SRW lock: a callback
  that sends a message to the game window on its own thread re-enters `GestureMessage` and hangs the game.
- **B58 b.** `WM_CAPTURECHANGED` is not focus loss (`gesture_feed.h` `Classify`); a stuck gesture recovers only one move late.
- **B58 c.** `ctl gesture press` sets `s_ctlHeld` even when the press was inert, so the next `ctl gesture move` sends `MK_LBUTTON` to the game as a plain
  drag (a box select in a headless walk).
- **B58 d.** One `D3DSBT_ALL` state block is created and released per preview frame. Decided below: not built.
- **B58 e.** No smoke launch walks `ctl gesture press/move/release` with a commit readback (the stand-in exe has no window and no device).

## What exists (read before building)
- `docs/PROXY_UI.md`, `docs/PROXY_GESTURES.md` (the contracts), `jobs/W2/report.md`, `jobs/W6/report.md` and both reviews.
- `proxy/src/ui_host.cpp`: `s_route`/`s_rmlOwner` (line 61), `WndProc` (the `WM_ACTIVATEAPP` case, the locked `UiDecide` block, the gesture stage after it),
  `hk_DIState`/`hk_DIData` (they also call `GestureOwnsMouse()`, which reads the gesture machine's `phase` and `swallowRUp` unlocked: the same race on the
  gesture side), `hk_Reset`. `proxy/src/ui_core.h`: `UiRouteState`, `UiDecide`, `UiRmlOwnsPointer`, `UiBlankDiButtons`, `UiBlankDiWheel`.
- `proxy/src/gesture.cpp`: `s_lock`, `GestureMessage` (adapter calls in `PressEligible`, `Rebuild`, `Probe` under the lock), `GesturePresent` (camera read
  and `BuildOverlay` under the lock, the commit off it), `Draw` (the per-frame state block), `GestureCtl` (`s_ctlHeld`). `gesture_feed.h` `Classify`/`Feed`,
  `gesture_sm.h` (the transition table: a press that starts a gesture goes `Idle -> Pending`; the `begin` flag is the drag threshold, `Pending -> Active`).
- Tests: `proxy/tests/test_ui_core.cpp` (routing tables, lifecycle, source lints that quote exact lines of `ui_host.cpp`), `proxy/tests/test_gesture.cpp`
  (the headers, 784 checks, the 792 key messages, the W2 ordering lints that also quote exact lines). Update a quoted line together with the code it quotes;
  never delete a lint to make a change pass.

## Decisions already made (follow them; a deviation goes in the report with its reason)
### B53
1. **One atomic word, no lock on the input path.** A pure `UiDiMask(const UiRouteState&) -> uint32_t` in `ui_core.h` (bit 0 blank mouse buttons =
   `UiBlankDiButtons`, bit 1 blank wheel = `UiBlankDiWheel`, bit 2 text focus) and `ui_host.cpp` publishes it with `InterlockedExchange` into
   `volatile LONG s_diMask` at the end of every block that writes `s_route` (the locked `UiDecide` block and the `WM_ACTIVATEAPP` case; one helper,
   `Publish()`, called under `s_cs`). `hk_DIState`/`hk_DIData` read `s_diMask` once per call and never read `s_route`. Taking `s_cs` in the DirectInput
   hooks is refused: the Present thread holds it while RmlUi renders, so a DirectInput poll on another thread would wait a UI frame.
2. **The gesture side the same way:** `GestureOwnsMouse()` reads one `volatile LONG s_ownsMouse` that `GestureMessage` publishes under `s_lock` after every
   message it feeds (phase not idle, or `swallowRUp`), instead of reading two machine fields unlocked.
3. **Focus loss is pure:** `UiFocusLost(UiRouteState&, bool& rmlOwner)` in `ui_core.h` clears both button masks and sets the owner false;
   `WM_ACTIVATEAPP` calls it under the lock, then `Publish()`. (Whether `wp` is TRUE or FALSE, as today: a release can be lost either way.)

### B58
4. **(a) Re-entry passes, it never waits.** `gesture.cpp` records the owner of `s_lock` (`volatile DWORD s_lockOwner`, set after acquiring, cleared before
   releasing, inside the `Lock` struct). `GestureMessage` (and `GestureSetWindow`) first compares `s_lockOwner` with `GetCurrentThreadId()`: equal means a
   callback on this thread sent a message to the window while the stage holds the lock, so the message passes to the game untouched (no state change,
   `InterlockedIncrement(&s_reentered)`, reported in `gesture info` as `reentered`, one `LOGW` on the first). Only the owning thread can have written its own
   id, so the unlocked read cannot give a false match. Do not drop the lock around the adapter calls: the machine's state would then change under a call.
5. **(b) `WM_CAPTURECHANGED` (0x0215) is focus loss** unless its `lParam` (the window gaining the capture) is the subclassed window itself. `Classify` gains the
   message and the parameters it needs to decide (pure; `gesture.cpp` passes the window handle as an integer); host cases: in every phase, gaining window
   null, another window, and ours.
6. **(c) Held only after the stage took the press:** after the press messages, under `s_lock`, `s_ctlHeld = (phase is Pending or Active)`; the result gains
   `"held": true|false`. A press the stage did not take (inert, over a panel, or eligibility refused) went to the game as a real press; the verb leaves it
   there (the driver sends `release`, as it would for any click) and the result says why it was not taken (`last_why`, as today). (In B58 "a begin" means the
   press started a gesture; the machine's `begin` flag is the later drag threshold, so do not test that flag.)
7. **(d) Not built.** A state block kept across frames must be released before every device `Reset` or the game's own `Reset` fails (D3D9: state blocks
   block `Reset` like default-pool resources), the saving over one `CreateStateBlock` per drawn preview frame is not measured, the RmlUi render interface makes
   one per frame too (`ui_render_d3d9.cpp` `BeginFrame`), and no CI run can show a `Reset`. Add one sentence to `PROXY_GESTURES.md` ("one state block per drawn
   preview frame, as the RmlUi pass; kept blocks would have to be released before every Reset") and remove (d) from the backlog with that reason.
8. **(e) A smoke walk, kill-limited.** It needs a window and a device under wine in CI: the stand-in exe (`proxy/tests/smoke_host.cpp`) gains a `window` mode
   (a 800x600 top-level window, `CreateDevice` through the proxy's `Direct3DCreate9`, a message pump and a `Present` loop for a bounded time), and
   `build.sh smoke` one launch with `ui.enabled=1`, `controls.gestures=1`, `dev.ctl=1` that writes `gesture press`, `move` and `release` requests and checks
   the `.done` files (a commit with the null adapter's three orders) and the log. CI's runner has no display: wine needs `xvfb-run` and 32-bit Mesa, and the
   UI host needs a shader compiler at run time (wine's builtin `d3dcompiler_47`). **Stop this step after about 20 calls** if the device cannot be created or
   the host does not start under CI's wine; then keep (e) in the backlog, reworded with what failed (package, error line), and say so in the report. If it
   works, the packages go into `ci/gates.yml.in`'s `proxy` job and the rendered `.github/workflows/gates.yml` (`python3 wsc.py ci render`), and `build.sh smoke`
   skips the launch with a printed reason when `xvfb-run` is absent (the PC route has no xvfb).

## Scope: files this job touches
`proxy/src/ui_core.h` (`UiDiMask`, `UiFocusLost`), `proxy/src/ui_host.cpp` (publish, DirectInput hooks, `WM_ACTIVATEAPP`), `proxy/src/gesture.cpp` (lock
owner, `s_ownsMouse`, `s_ctlHeld`, `reentered`), `proxy/src/gesture_feed.h` (`Classify`), `proxy/tests/test_ui_core.cpp`, `proxy/tests/test_gesture.cpp`,
`docs/PROXY_UI.md` ("Input" and "Threads": the DirectInput hooks read one published word), `docs/PROXY_GESTURES.md` (re-entry, `WM_CAPTURECHANGED`, `held`, the
state-block sentence), `docs/BACKLOG.md` (remove B53 and B58; keep (e) reworded if dropped), `VERSION`; for (e) only: `proxy/tests/smoke_host.cpp`,
`proxy/tools/build.sh`, `ci/gates.yml.in`, `.github/workflows/gates.yml`. No change to `GestureAdapter` or any adapter. No game names in core files.

## Steps
1. Read "What exists"; check whether this session can build the host tests (`proxy/tools/build.sh tests`), else push early and read CI's `proxy` log.
2. **Failing tests first**, committed red: `UiDiMask` agrees with `UiBlankDiButtons`/`UiBlankDiWheel`/`textFocus` on every `UiRouteState` (exhaustive over
   the bools and the button masks 0-7); `UiFocusLost` clears masks and owner, and the next `UiDecide` behaves as on a fresh start; `Classify` cases for
   `WM_CAPTURECHANGED` (decision 5) through `Feed` in every phase (a gesture in Pending or Active cancels; Idle and Drain unchanged).
3. Build B53 (decisions 1-3), then B58 a, b, c (4-6), each its own commit, with source lints: the DirectInput hooks do not contain `s_route`; every write of
   `s_route` in `ui_host.cpp` is followed by `Publish()` before its lock ends (or one lint that `Publish()` appears in both blocks); `GestureOwnsMouse` reads
   `s_ownsMouse` only; `GestureMessage` tests `s_lockOwner` before taking `s_lock`; `s_ctlHeld = true` no longer appears unconditionally.
4. (d): the doc sentence and the backlog line (decision 7).
5. (e), within its cap (decision 8).
6. Docs, backlog, `VERSION`; `python3 wsc.py gates` (full), CI's `proxy` job green, `python3 wsc.py policy --branch job/W20 --base origin/main`.

## Tests and acceptance
- New cases red first, then green, with every existing proxy host test (`test_gesture` keeps its 784 checks plus the new ones; `test_ui_core` its routing
  tables); the null game's `build.sh all`, `repro` and `smoke` green in CI; the existing smoke launches 6 and 7 (gestures with and without the host) unchanged.
- No new import in the DLL; no new hook (`test_gesture.cpp`'s "gesture.cpp installs no subclass and no hook of its own" still passes).
- Re-entry (a) cannot be driven on a real window in CI: the proof is the lint plus a pure test of the owner check if you factor it out (recommended:
  `ReenteredBy(owner, me)` in `gesture_host.h`); say in the report what was and was not run.

## VERSION
A minor bump (new result members `held` and `reentered`, changed input behaviour; the DLL inputs change). Take the next free minor as `origin/main` stands
at merge time (0.15.0 when written; W7 expects 0.16.0; W17 and W19 also bump). Re-read `origin/main` `VERSION` and the open
`job/*` branches before the last commit; the second to merge takes the next free number and merges `main` (never rebase). Say which number you took. Tags are
Liam's.

## What consumers must do after the tag (napoleon-remastered)
- **Rule 79:** `proxy/src` is a DLL input, so the pin bump that crosses this tag needs 20 consecutive acceptance passes on the new build id. Bump across W19
  (capture), W17 and this job together where possible: one 20-pass run on the final build id covers every DLL change in the bump.
- J29 (the gesture walk), if not yet run: `gesture press` now returns `"held"`; a driver that sends `move` after a press with `"held": false` is moving the
  plain cursor, not dragging. A gesture now cancels when the game window loses mouse capture to another window.
- Nothing else: no adapter, config key or ini change.

## Kill criteria
- A fix would need a lock in a DirectInput hook or a second subclass or hook: stop and report; do not trade the race for a stall or a new hook.
- The re-entry guard would swallow, or change, a message the game should see: stop; re-entry must pass messages untouched.
- `WM_CAPTURECHANGED` handling would cancel a gesture the stage itself started capture for (it calls no `SetCapture` today; if you find it does, stop and report).
- (e) over about 20 calls without a device under CI's wine: drop (e) as decision 8 says; it never blocks the rest.
- Core CI red after three fix attempts for a cause in this change: stop and report. Version collision as in VERSION; never rebase a pushed branch.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **(d): build the kept state block anyway?** Recommended: no (decision 7). If Liam wants it, it is one block in `gesture.cpp`, `Capture()` each drawn
   frame, released in `ui_host.cpp` `hk_Reset` before `o_Reset` and on a device replacement, with a lint for that order; the risk is a failed `Reset` in the
   game, seen only on the PC.
2. **Lock or atomic word for B53?** Recommended: the atomic word (decision 1); B53 offers both, and the lock would put RmlUi's render time on the input path.
3. **An inert ctl press: leave it, refuse it beforehand with a probe, or release it at once?** Recommended: leave it (decision 6) and report `held`. A probe
   first races the press; an automatic release turns the press into a click, which selects or deselects units in the game.
4. **(e) in CI at all?** Recommended: try it within the cap. If wine needs `xvfb` and 32-bit Mesa, the `proxy` job grows by those packages (about a minute);
   if that flakes, drop it and leave the end-to-end ctl path to the consumer's J29, as today.
5. **File overlap with the other core rows**, for whoever merges second (merge `main`, never rebase):
   - **W19** (capture) hooks `CreateStateBlock`/`Apply` on the device; the preview's and the RmlUi pass's state blocks then appear in captures. No file overlap.
   - **W17** (dev channel) touches `dev.cpp` and `devcore.h`; this job does not (the `gesture` grammar in `gesture_feed.h` is unchanged).
   - **W21** (core CI) rewrites `ci/gates.yml.in` and the rendered workflow; step (e) would add packages to the same `proxy` job: the second to merge
     re-applies its change to the template and runs `wsc ci render`.
   - **W16** (the null game on its own) and step (e) both touch `proxy/tools/build.sh` (`smoke`) and possibly the null game's ini.
   - **W7** touches `patch_driver.cpp`, `patch_engine.h`, `config.h`: no overlap. All rows: `docs/BACKLOG.md`, `docs/CONSUMING.md`, `VERSION`.

## Finish
Report in `jobs/W20/report.md` (what was built per item, tests red then green and where they ran, whether (e) ran or why not, the version taken,
deviations, open questions, what napoleon must do), then `wsc reg set jobs W20 status=review report=jobs/W20/report.md` (`python3 wsc.py`). Push `job/W20`,
open the draft pull request, and stop: an independent reviewer merges (C18); Liam tags.

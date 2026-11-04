# W20 report: UI host and gesture driver hardening

Written by the orchestrator from the builder subagent's hand-back, because the harness refuses a subagent's write of a report file.
The text is the builder's own, except for this note and the section "CI evidence (orchestrator)" further down.

W20 closes B53 and B58 a, b and c in the proxy. It records the decision not to build B58 d, and leaves B58 e in the backlog, reworded.
VERSION is 0.23.0 on branch `job/W20`. The builder's PC had no g++ and no running Docker, so the C++ was first compiled and run in CI;
the section "CI evidence (orchestrator)" gives the runs.

## What was built
- **B53: the DirectInput race** (`proxy/src/ui_core.h`, `ui_host.cpp`, `gesture.cpp`).
  - `ui_core.h` gains a pure `UiDiMask(const UiRouteState&)`: bit 0 blanks the mouse buttons (`UiBlankDiButtons`), bit 1 blanks the
    wheel (`UiBlankDiWheel`) and bit 2 marks text focus.
  - `ui_core.h` also gains `UiFocusLost(UiRouteState&, bool& rmlOwner)`, which clears both button masks and the owner.
  - `ui_host.cpp` has a `volatile LONG s_diMask` and a `Publish()` helper (`InterlockedExchange`, called under `s_cs`). `Publish()`
    runs at the end of the locked `UiDecide` block and in the `WM_ACTIVATEAPP` case.
  - The `WM_ACTIVATEAPP` case now calls `UiFocusLost(s_route, s_rmlOwner)`, which also clears `s_rmlOwner`, and then `Publish()`.
  - `hk_DIState` and `hk_DIData` read `s_diMask` once per call. They no longer touch `s_route` and they take no lock.
  - `gesture.cpp`: `GestureOwnsMouse()` returns `s_ownsMouse != 0`. `GestureMessage` publishes that word with `InterlockedExchange`,
    under `s_lock`, after every message it feeds (when the phase is not Idle, or `swallowRUp` is set).
- **B58 a: re-entry passes** (`gesture.cpp`, `gesture_host.h`).
  - The `Lock` struct sets `volatile DWORD s_lockOwner` after acquiring the lock and clears it before releasing.
  - `GestureMessage` and `GestureSetWindow` compare it with `GetCurrentThreadId()` before they take `s_lock`, through the new pure
    `ReenteredBy(owner, me)` in `gesture_host.h`. An owner of 0 never matches.
  - On a match the message is returned untouched: no state change, `InterlockedIncrement(&s_reentered)` and one `LOGW` the first
    time. `gesture info` reports `"reentered"`.
  - The lock is not dropped around the adapter calls.
- **B58 b: `WM_CAPTURECHANGED`** (`gesture_feed.h`, `gesture.cpp`).
  - `kWmCaptureChanged = 0x0215`. `Classify(msg, wp, lp = 0, self = 0)` treats it as focus loss unless `self != 0` and `lp == self`,
    that is, unless our own window is gaining the capture.
  - `Feed` takes `lp` and `self` as two trailing defaulted parameters, so existing callers are unchanged. `GestureMessage` passes `lp`
    and the window handle as an integer.
  - The stage calls neither `SetCapture` nor `ReleaseCapture` (grepped across `proxy/src`), so that kill criterion did not fire.
- **B58 c: held only after the stage took the press** (`gesture.cpp`).
  - After the press messages, under `s_lock`, `s_ctlHeld = (phase is Pending or Active)`.
  - Every ctl result now starts with `"held": true|false`.
  - A press the stage did not take is left where it went (to the game), and `last_why` says why.
- **B58 d: not built** (decision 7). One sentence in `docs/PROXY_GESTURES.md`; d is removed from the backlog.
- **B58 e: not attempted.** See Deviations.
- **Docs.**
  - `PROXY_UI.md`: Input, Threads.
  - `PROXY_GESTURES.md`: re-entry, `WM_CAPTURECHANGED` under Cancel, `held`, and the state-block sentence.
  - `docs/BACKLOG.md`: B53 removed, B58 narrowed to the smoke walk.

## Tests, red then green
- **Red first.** Commit d68a698 holds only the tests, which cannot compile before the code lands: red by construction. The builder
  could not observe the red on the PC.
- **`test_ui_core.cpp`.**
  - `UiDiMask` against `UiBlankDiButtons`, `UiBlankDiWheel` and `textFocus`, exhaustive over the three bools and masks 0-7 x 0-7
    (512 states, 4 checks each, plus a check for stray bits).
  - `UiFocusLost`: the masks and the owner are cleared and the sensed bools kept, and the next `UiDecide` for all six event types
    equals a fresh start's. Exhaustive over hover, scroll, both masks 0-7 and the previous owner.
  - Source lints:
    - the DirectInput hooks contain no `s_route`, no `s_cs` and no `Lock`, and do use `s_diMask`;
    - `Publish()` and its `InterlockedExchange` exist;
    - the `WM_ACTIVATEAPP` block calls `UiFocusLost(s_route, s_rmlOwner)` and `Publish()`;
    - the `UiDecide` block calls `Publish()` after `s_rmlOwner = ...` and before `Count`, inside the lock.
- **`test_gesture.cpp`.** The existing 784 checks are untouched. New:
  - `Classify` for `WM_CAPTURECHANGED` with the gaining window null, another window, ours, and no handle.
  - `Feed` in all four phases (Idle, Pending, Active, Drain) against three gaining windows (null, other, ours): the message always
    passes; a Pending or Active gesture cancels to Idle; our own window leaves every phase alone.
  - `ReenteredBy`: a match, another thread, and owner 0.
  - Source lints:
    - `GestureOwnsMouse` reads only `s_ownsMouse`, and `s_ownsMouse` is published with `InterlockedExchange`;
    - `GestureMessage` and `GestureSetWindow` test `s_lockOwner` before their `Lock l;`, and `Lock` sets and clears the owner;
    - `s_reentered` is counted and reported;
    - `s_ctlHeld = true;` no longer appears, and `"held"` is reported.
  - The existing lint "gesture.cpp installs no subclass and no hook of its own" still applies.
- **On the PC.** The full `python3 wsc.py gates` gave 13 ok, 1 warn, 0 failed: 575 Python host tests passed, and the warn is five
  environment skips (no POSIX sh or symlinks; no capstone). The C++ was reviewed by hand for `-Wall -Wextra -Werror`; for example, an
  anonymous enum used in a `?:` against `0u` was replaced by a `constexpr uint32_t`.
- **Re-entry (a).** It cannot be driven on a real window in CI, so the proof is the lint plus the pure `ReenteredBy` test. The real
  two-callback path has not been exercised.

## CI evidence (orchestrator)
- **First CI build: run 41794029456, job `proxy`.** Every suite before `test_gesture` passed, then one compile error:
  `test_gesture.cpp:402: 'ReenteredBy' was not declared in this scope`. The test file uses only `wsp::gest`, while the check lives in
  `wsp`. The orchestrator qualified the four calls in d32f4a5, and changed nothing else.
- **Second CI build: run 41794563740, all green.**
  - `proxy` (5m34s): 14 host-test suites with 0 failures, among them `test_gesture` 824 passed and `test_ui_core` 6366 passed. The
    others: `test_camera` 17, `test_capture` 156, `test_config` 128, `test_console` 57, `test_crash` 18, `test_dev` 296,
    `test_display_guard` 227, `test_guard` 81, `test_orders` 732, `test_patch_engine` 209, `test_patch_value` 191, `test_ui_rml` 25.
  - `gen_tables`: ok.
  - `build.sh repro`: identical from another path.
  - `build.sh smoke`: passed, 8 launches under wine and 2 dumps.
  - `gates`: ubuntu and windows green.
  - `harness-windows`: skipped (no harness input changed).

## Version
0.23.0 was taken against `origin/main` at 0.22.0. If another job takes 0.23.0 first, the second to merge renumbers and merges main
(never rebase).

## Deviations from the brief, and why
1. **Step (e), the smoke walk, was not attempted.** It needs a window and a device under wine, with `xvfb-run` and 32-bit Mesa. The
   PC had no g++, no running Docker and no wine, so any attempt would have been edited blind into the required `proxy` job, with a red
   required check blocking the job. The brief allows dropping (e) when the device cannot be created under CI's wine. B58 stays in the
   backlog, reworded as the smoke walk only. `smoke_host.cpp`, `build.sh`, `ci/gates.yml.in` and the rendered workflow are unchanged.
2. **Commits are not one per item.** B53's UI side and gesture side and B58 a, b and c all touch `gesture.cpp` and its feed header, and
   each step could not be compiled on its own on the PC. They are one commit (6789f24). The tests come first (d68a698); the docs,
   backlog and VERSION are separate (d6b184b).
3. **`Feed` and `Classify` signatures.** The brief did not fix them. Defaulted `lp` and `self` parameters were appended. Calling
   `Classify` without `self` treats `WM_CAPTURECHANGED` as focus loss, never as ours.
4. **`held` is in every ctl result**, not only after `press`. For `move` and `release` it shows the verb's remembered state.
5. **Re-entry and the probe message.** A probe message that arrives re-entrantly passes to the game (an unknown registered message,
   harmless to the game), and `gesture info` then shows a stale probe. Re-entry passes everything untouched, as the kill criterion
   requires.

## Kill criteria checked
- No lock in a DirectInput hook.
- No second subclass or hook.
- Re-entry passes messages untouched.
- The `WM_CAPTURECHANGED` handling cancels no gesture the stage captured for (it calls no `SetCapture`).
- (e) never ran, so its cap did not come into play.

## Open questions
- **(d), keeping one state block:** the recommendation stands: no.
- **(e) in CI:** someone with working Docker, or a CI iteration budget, should try the `window` mode of `smoke_host.cpp` on a branch
  of its own. The backlog line says what to add.
- **The probe message under re-entry (deviation 5):** is it acceptable, or should the probe be swallowed even when re-entered? It is
  left as the brief says.

## What napoleon must do
- **Rule 79.** `proxy/src` is a DLL input, so the pin bump that crosses this tag needs 20 consecutive acceptance passes on the new
  build id. One 20-pass run on the final build id covers every tag the bump crosses.
- **J29 (the gesture walk).** `gesture press` now returns `"held"`. A driver that sends `move` after a press that came back with
  `"held": false` is moving a plain cursor, not dragging, and should send `release` for that untaken press.
- **Capture loss.** A gesture now cancels when the game window loses mouse capture to another window or to nothing.
- **`gesture info`** gains `"reentered"`.
- No adapter, config key or ini change is needed.

## Fix round 1
1. **Blocker, shadowed `mask` in `hk_DIState`.** Fixed: the blank decision is now the pure `UiDiBlankButtons(word, gestureOwns)` and
   `UiDiBlankWheel(word)` in `ui_core.h`; the hooks read the published word as `dim` and the button bitmap is `btns`, so nothing shadows.
   `test_ui_core.cpp` tests the functions over every combination (including a held left button not being the route word) and lints that the
   hooks use them and declare no `mask`. The proxy and host tests now compile with `-Wshadow` (`tools/build.sh`). Commit: see `git log`
   (one commit with the fix, tests and flag). Not compiled on the builder's PC (no compiler); CI is the compiler. If `-Wshadow` flags older
   code, CI will say so on this branch.
2. **Should-fix, coverage beyond text presence.** Closed by the same pure function and its exhaustive test.
3. **Deviation 2, accepted.** No action.
4. **Later (B58 e).** Left in the backlog as the review says.
5. **Deviation 5, accepted.** No action.

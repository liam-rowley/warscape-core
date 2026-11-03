# W18: Headless display guard: show-time hook, scaled-DPI own moves, status after relocation

Model: Sonnet, reason: none needed (Sonnet is the default). Three contained changes to the headless guard, each with a pure, host-tested decision in
`display_guard.h` and a small Win32 change in `headless.cpp`; no engine site, no reverse engineering. Budget about 140 tool calls (about 70 for the code and
host tests, about 50 for the PC sitting, the rest for docs and the report). At the cap, stop, commit, and report what is left.

## Goal
Three items from napoleon-remastered J12 and its review (`docs/BACKLOG.md` B19, B22, B23; removed when this merges, B22 reworded if its PC proof stays open):
- **B19, a window a DLL shows after start-up is hidden at once.** Today the guard thread sweeps every top-level window every 62 polls (`kSweepPolls`, about 250 ms),
  so a third-party window can sit on a real monitor for up to a quarter second (napoleon run `20261031_j12pc` 1b: 109 ms, `harness/runs/20261031_j12pc/1b_winprobe.json`
  `longest_visible_on_real_ms`, in that repo). A WinEvent hook (`EVENT_OBJECT_SHOW`, out of context, pumped on the guard thread) hides it when it is shown.
- **B22, the guard's own move at a scaled target DPI.** `display_guard.h` `IsOwnMove` matches the armed rect in physical pixels only, so when the game window's thread
  is DPI-unaware and the target display is scaled, the guard's asynchronous move arrives in logical pixels, is taken for the engine's and dropped, and the window
  stays cloaked (the comment above `kOwnMoveMs` says so; J12 review). Recognise the logical rect too.
- **B23, `headless_status.json` after a relocation.** The status is written at `on_virtual` and never again, so after a display move `shot.sh` (which reads its
  `target.rect`) captures the old rect (napoleon J12 report, open question 3). Rewrite it after each verified relocation.

## Decisions already made (follow them; a deviation goes in the report with its reason)
1. **B19, the show hook.** On the guard thread, before its loop: `SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, nullptr, cb, GetCurrentProcessId(), 0,
   WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNTHREAD)`; failure is logged (`LOGW`) and the sweep stays the only path, never a refusal. The loop's `Sleep(4)` becomes
   `MsgWaitForMultipleObjects(0, nullptr, FALSE, 4, QS_ALLINPUT)` followed by a `PeekMessageW`/`DispatchMessageW` drain, **outside** `Lock`, so the callback
   (which takes `Lock` per window, as `SweepCb` does) never runs with the lock held by its own thread's loop body. The callback acts only for `idObject ==
   OBJID_WINDOW`, `idChild == CHILDID_SELF`, a top-level window (`GetAncestor(h, GA_ROOT) == h`) of this process, and applies the same rule as the sweep through a new
   pure function `ShowEventHides(isWindowObject, topLevel, sameProcess, visible, guarded, rect, targetKnown, target)` that wraps `SweepHides`. It logs
   `headless: unguarded window <h> shown at <rect>: hidden at show (winevent)` (rate-limited like the other per-call lines). The sweep stays as the backstop
   (windows shown before the hook, a missed event), unchanged in rate.
2. **B22, logical own moves.** `OwnMove` gains `Rect logical; bool haveLogical`. When `PlaceLocked` arms the main window's move, it also computes the rect the window's
   own thread will see: if `GetWindowDpiAwarenessContext(h)` is not per-monitor aware (resolve the functions with `GetProcAddress`, as `DpiFn` does; absent = skip),
   convert the physical corners with `PhysicalToLogicalPointForPerMonitorDPI(h, ...)` and arm `logical` when it differs from `want`. `IsOwnMove` accepts the
   physical rect exactly, or the logical one with each edge within 1 px (rounding), under the same time and flag rules. A position message inside the armed
   window that moves and sizes but matches neither is logged once per arming with both rects and the message's numbers (the evidence a scaled case needs);
   it is still dropped. No extra re-placement: `Decide` already re-queues a cloaked, unverified window.
3. **B23, the status after each verified relocation.** In the success branch of `RelocateLocked` (where it logs the relocation and sets `s_placed`), it also
   updates `s_st` (the target monitor, the window and client sizes, `detail` = `relocated to <device> <rect> at <uptime> s`) and calls `WriteStatus()`. `Status` gains `relocations` (count,
   0 until the first) written by `StatusJson` as `"relocations": <n>` before `written_utc`. `state` is **not** changed (an `on_virtual` stays `on_virtual`; the
   watcher's wait and heartbeat read it), and nothing is written at the cloak (out of scope). Readers parse JSON, so the added field is compatible (`harness/shot.sh`
   reads `target.rect`; the watcher reads `state`).
4. **No new config key.** The hook is always on with headless; a game would otherwise need a `config_keys` row for it. If the PC sitting shows a cost or a hang
   (kill criteria), it is a stop, not a switch.
5. **PC proofs reuse the J12 procedure and its test hooks** (`headless.test_dll_window_ms`, `headless.test_off_thread`; dev only, release 0; read napoleon's
   `jobs/J12/report.md` rows 1a and 1b and `harness/runs/20261031_j12pc/`). The only display change an agent may make is the virtual display's origin
   (`harness/vdisplay_probe.ps1 -Origin` / `-Restore`, its header says so). Changing a display's DPI scale is a Windows setting only Liam changes.

## Scope: files this job touches
- Changed: `proxy/src/display_guard.h` (`ShowEventHides`, `OwnMove`/`IsOwnMove`, `Status.relocations`, `StatusJson`, the comments above `kOwnMoveMs` and the
  sweep), `proxy/src/headless.cpp` (the hook and pump on the guard thread, the logical arm in `PlaceLocked`, the near-miss log, the status rewrite; its header
  comment's mechanism list), `proxy/tests/test_display_guard.cpp` (`TestOwnMove`, `TestSweep` or a new `TestShowEvent`, `TestStatus`, `TestLints`).
- Evidence: `jobs/W18/runs/<YYYYMMDD>_w18pc/` on the job branch: `README.md` (procedure, run ids, build id, results, every file it names present), the proxy log
  excerpts as `.txt` (`*.log` is git-ignored), the window probes' `winprobe.json`, the shots. Nothing from the PC sitting is committed to napoleon-remastered.
- Docs: `docs/CONSUMING.md` (one paragraph under "The proxy, the harness and the save tools": the show hook, the logical own move, `relocations` in the status),
  `docs/BACKLOG.md` (remove B19, B23; remove B22 or reword it to its open PC proof), `VERSION`. No game names in core files (`tests/test_moved_tools.py` `NoGameNames`).
- Not touched: `harness/` (the watcher, `shot.sh` and `ctl.py` already read the file as JSON), the null game, `proxy/tools/`.

## Steps
1. Read `proxy/src/display_guard.h` (all), `proxy/src/headless.cpp` (all), `proxy/tests/test_display_guard.cpp` (all), `proxy/tests/testkit.h`, and in
   napoleon-remastered (read-only): `jobs/J12/report.md` (rows 1a, 1b, "Evidence", open question 3), `jobs/J12/review.md` (the B22 finding),
   `harness/runs/20261031_j12pc/`, `proxy/README.md` "Headless" (the consumer's owner doc), `harness/README.md` (the watcher's headless launch).
   Check whether this session can build (`docker info` for `build.sh --docker`, or the native toolchain); else the C++ tests run in CI's `proxy` job.
2. **Failing tests first**, committed red, in `test_display_guard.cpp`: `ShowEventHides` (child object, child window, other process, invisible, guarded, helper
   size, inside the target, off the target, no target); `IsOwnMove` with a logical rect at 125 % and 150 % (exact, off by one on each edge accepted, off by two
   refused, physical still accepted, expired, `SWP_NOMOVE`/`SWP_NOSIZE` refused, not armed); `StatusJson` with `relocations` 0 and 3 and the field order; source
   lints on `headless.cpp`: `SetWinEventHook` with `WINEVENT_OUTOFCONTEXT` inside `GuardThread` before its loop, the message drain before `Lock l;` in the loop,
   `WriteStatus()` in the success branch of `RelocateLocked`, and `s_st.state` not assigned there.
3. Build decisions 1 to 3. Keep the J13 and J12 tests green unchanged.
4. CI green (`gates`, `proxy`: null game `build.sh all`, `repro`, `smoke`; `harness-windows`) before the PC sitting.
5. **The PC sitting** (below). Then the evidence folder, docs, backlog, `VERSION`; `python3 wsc.py gates` (full) and
   `python3 wsc.py policy --branch job/W18 --base origin/main`.

## The PC sitting (needs_pc; the PC slot is shared with napoleon jobs)
The game is the first consumer's (Napoleon on Liam's PC). Its rules hold here exactly as in a napoleon job (napoleon `CLAUDE.md` "Where agents run" and
"While you work"; `harness/README.md`):
- **One PC job at a time.** Before anything: `core/harness/job.sh status` (from the napoleon checkout) and napoleon's `python3 core/wsc.py jobs view`: if the game
  lock is held, or a napoleon `needs_pc` job is being built or fixed, wait for it; never take over a live lock and never `unlock --force` another owner's. Take
  the lock for the whole sitting: `core/harness/job.sh lock w18 <your session id> "W18 headless guard proof"`, `touch` it during long steps, `unlock w18` at the end.
- **The game is launched, killed and profiled only through the watcher** (`core/harness/job.sh w18 - <<< 'launch ...'` and the `kill`, `status` jobs), never by
  starting the exe. Experiments live in `job.sh scratch w18`. Never run git in a game folder. Files reach the game folder only through `pc_deploy.py` (sha-checked).
- **The DLL under test.** Build it from a scratch napoleon tree that is never committed or pushed: `git -C /c/Users/liamr/repos/napoleon-remastered worktree add
  --detach /c/Users/liamr/repos/nap-W18pc origin/main`, `git submodule update --init`, then check `core/` out at this branch's head (fetch it from your
  warscape-core clone). If a napoleon branch already pins a core at or past this branch's base (`git ls-tree origin/job/<id> core`), start from it instead. Napoleon
  pins v0.9.0, so its adapter may need the pin-bump edits of 0.10.0 onward (`docs/CONSUMING.md`, e.g. the `gesture` member of `GameAdapter`, 0.13.0): make only
  those, in the scratch tree. Build with `core/proxy/tools/build.sh --docker all`, kit and install with `core/proxy/tools/pc_deploy.py` (`kit`, `send`, `install`),
  set keys with `pc_deploy.py set`. Record `pc_deploy.py status` before you install.
- **Proofs** (each a separate launch; `headless.enabled=1`, the watcher's window probe on as in every launch):
  - **a. B19:** `headless.test_dll_window_ms=15000`. Pass: the log's `hidden at show (winevent)` line is at most 15 ms after the `TEST HOOK ... shown` line, and the
    probe's `longest_visible_on_real_ms` for that window is at most 25 ms (two samples; J12 measured 109 ms with the sweep alone). The game window itself 0 ms.
  - **b. B23 and the 100 % own move:** `headless.test_off_thread=1` (the guard thread places a window it does not own, so the move is asynchronous: J12's 1a). With
    the game at the front end, run `vdisplay_probe.ps1 -Origin 2560,0 -SaveTo <scratch json>` as a watcher ps1 job, wait for the relocation success line in the log,
    then read `headless_status.json` (a read-only job) and run `core/harness/shot.sh`: the status names the new rect with `"relocations": 1` and the shot is that
    rect. Then `-Restore` the saved json: the status names the restored rect with `"relocations": 2`. The window uncloaks after the settle both times, and the probe
    shows 0 ms on a real monitor.
  - **c. B22 (only if Liam opts in):** needs the virtual display at a scaled DPI (125 % or 150 %), a Windows display setting only Liam changes; every napoleon run
    so far had the virtual display at 96 DPI (its `proxy.log` monitor lines: `adapter='Virtual Display Driver' ... dpi=96`). Ask in the report's open questions
    whether he wants it; do not change the scale yourself. Without it, B22 ships host-tested and its backlog line is reworded to the open PC proof.
  - **d. No regression:** one plain headless launch (no test hooks) to the front end: `on_virtual` as before, probe 0 ms on a real monitor, no new warning lines.
- **Put the PC back.** Uninstall the scratch DLL with `pc_deploy.py uninstall` and reinstall what `status` showed before (its kit is under `<state>\kits\`), so the
  game folder's `pc_deploy.py status` matches the one recorded before the sitting (same kit id, exe sha vanilla); the next napoleon job must not find a dev build.
  Release the lock; remove the scratch worktree (`git worktree remove`), and the scratch folder's large files stay out of both repos.

## Tests and acceptance
- The step 2 cases red first, then green, with every existing proxy host test; CI's `proxy` job green (the wine smoke runs without headless, so the hook must
  not change it).
- PC proofs a, b and d pass and their evidence is in `jobs/W18/runs/<run id>/`, each claim with its run id and date; c is run only if Liam opts in.
- `git diff --stat origin/main` touches only the files in Scope and the evidence folder.

## VERSION
A minor bump: the DLL's behaviour and the status file's fields change (consumer-visible, pre-1.0; the DLL inputs change). Take the next free minor at merge
time: `origin/main` says 0.15.0 when this brief was written, `job/W7` claims 0.16.0, and other W rows (W7 to W21) may claim minors first. Re-read
`origin/main` `VERSION` and the open `job/*` branches before the last commit; the second to merge takes the next free number and merges `main` (never rebase).
Say in the report which number you took. Tags are Liam's.

## What consumers must do after the tag (napoleon-remastered; also goes into `docs/CONSUMING.md`)
- **Rule 79:** `proxy/src` changes, so the pin bump that crosses this tag needs 20 consecutive acceptance passes on the new build id
  (`python3 core/harness/acceptance.py run`); one 20-pass run covers every tag the bump crosses.
- `proxy/README.md` "Headless" (its owner doc): the show-time hook beside the sweep, the logical own-move rect and its near-miss log line, and
  `headless_status.json` rewritten after each verified relocation with `relocations`. Its own readers of the status (if any outside the core's `shot.sh`, `ctl.py`
  and the watcher) parse JSON, so nothing else changes. No adapter or `config_keys` change (no new key).
- Napoleon pins v0.9.0 today: the commit that crosses this tag also follows each earlier version's notes in this file (0.10.0 onward).

## Kill criteria
- The game lock is held by another owner, or a napoleon PC job is in flight, when the sitting should start: wait; if it is still busy after you have finished
  everything else, stop with the code and host tests pushed and the PC proofs listed as not run (the reviewer cannot merge a `needs_pc` job without them, so
  say exactly what remains).
- The scratch napoleon tree does not build against this branch's core within about 20 calls of adapter edits: stop the PC part and report the errors; do not
  change the core to suit the consumer's old adapter.
- Any window of the game process is seen on a real monitor for longer than before (probe), or the guard thread's pump hangs or deadlocks the game (watcher
  hang watchdog, a launch that never reaches `on_virtual`): stop, kill through the watcher, put the PC back, and report the log.
- B22 cannot be expressed without the guard moving a window it does not own synchronously, or without accepting a move that matches no armed rect: stop that
  part after about 15 calls and ship B19 and B23.
- Core CI red after three fix attempts for a cause in this change: stop and report.
- Version collision handled as in VERSION above; never rebase a pushed branch.

## Open questions (with recommendations; the brief follows the recommendation unless Liam says otherwise)
1. **B22's PC proof at a scaled virtual display?** Recommended: not in this sitting unless Liam opts in (decision 5, proof c). The virtual display has always run at
   96 DPI, so the case is latent; the host tests cover the rect logic, and the near-miss log line gives the evidence the first time a scaled target occurs.
   Alternative: Liam sets the virtual display to 125 % for one launch and back afterwards.
2. **Keep the 250 ms sweep once the hook is in?** Recommended: yes, as the backstop (a window shown before the hook went in, an event lost under load); it costs one
   `EnumWindows` four times a second.
3. **A key to switch the hook off?** Recommended: no (decision 4): a key needs a `config_keys` row in every game, and a hook that misbehaves is a kill criterion,
   not a setting.
4. **Write the status at the cloak as well (a `relocating` detail)?** Recommended: no: the watcher reads `state` and the heartbeat, and a status that flips while
   cloaked would need a new state value every reader learns. Only verified relocations are written.
5. **Where the PC evidence lives.** Recommended: in this job's folder on the core branch (`jobs/W18/runs/`), since the core job owns the claim; earlier core jobs
   (W2) cited the consumer's run folder instead because the consumer's job ran the sitting. If W12's run-README gate (B13) lands first, the README's paths must exist.
6. **File overlap with the other core rows (W7 to W21)**, for whoever merges second (merge `main`, never rebase):
   - **W9** (acceptance and scene launches, including the hist_nile relaunch that gets no `on_virtual` within 180 s, B60; needs a brief, needs_pc): if its cause is in
     the proxy it touches `headless.cpp`'s status writes; the PC slot is shared too, so W9 and W18 never sit at the same time.
   - **W20** (UI host and gesture hardening): `ui_host.cpp` subclasses the same main window as `GuardProc`; no shared file, but a window-message change on either side
     is worth a look at the other.
   - **W12** (guards, stale moved paths, B24): `headless.cpp`'s header points at `proxy/README.md`, which is the consumer's file, not the core's; if W12's lint
     flags it, say "the consumer's proxy/README.md" or point at `docs/CONSUMING.md`. W18 does not need to fix it unless W12 merged first.
   - **W16** (null game build and tests), **W17** (dev channel), **W19** (capture): `proxy/` but not `display_guard.h`, `headless.cpp` or `test_display_guard.cpp`.
   - All rows: `docs/BACKLOG.md`, `docs/CONSUMING.md` and `VERSION`.

## Finish
Report in `jobs/W18/report.md` (what was built, the tests red then green, the PC proofs with their run ids and the evidence folder, whether proof c ran, the
version taken, deviations, open questions, what napoleon must do), then `wsc reg set jobs W18 status=review report=jobs/W18/report.md` (`python3 wsc.py`).
Push `job/W18`, open the draft pull request, and stop: an independent reviewer merges (C18); Liam tags.

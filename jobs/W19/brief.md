# W19: Capture: timeout path, render thread only, state blocks

Model: Opus, reason: thread ownership across the ctl and render threads, a lock-free arm/abandon handshake, and new vtable hooks on
`IDirect3DStateBlock9` inside the D3D9 detours, where a mistake is a race, a stuck capture or a crash in the game, and none of it can be run on a real
device in CI. Budget about 110 tool calls (the C++ host tests may only run in CI if the session has no g++/MinGW: allow for CI round trips). At the cap,
stop, commit, and report what is left.

## Goal
Three items from napoleon-remastered J8's review round 1 (`jobs/J8/review.md` on that repo's `main`, "Later" and finding 2), the core's `docs/BACKLOG.md`
B32, B33 and B34 (all three removed when this merges):
- **B32, the timeout path.** `capture.cpp` `CaptureRun` (lines 423-436 on `main`): when the second 30 s wait times out it still returns ok with a partial
  frame, sets `kIdle` while the render thread still has `s_rec` set and `frame.txt` open, and the next capture reopens over it. There is a second race the
  review did not name: on the first timeout the ctl thread swaps `kArmed` to `kIdle`, but the render thread may already have read `kArmed` in
  `CapturePresent` and goes on to open the file and set `kRecording` with nobody waiting; it then ends in `kDone` forever, and every later capture is
  refused ("a capture is running") until the game restarts. Both are fixed by one state machine with compare-and-swap transitions on both sides.
- **B33, the render thread only.** `s_depth`, `s_buf`, `Line()` and the describe sets are unsynchronised globals; a device call or a `D3DPERF` event from a
  second thread during a recording races them. The recording keeps only the thread that armed it (the Present thread) and counts the others.
- **B34, state blocks.** `CreateStateBlock` (device slot 59) and `IDirect3DStateBlock9::Capture`/`Apply` are not hooked. D3DX effects save and restore
  state through state blocks unless created with `D3DXFX_DONOTSAVESTATE`, so an `Apply` changes render, sampler and texture state unseen and the per-draw
  state the summaries derive after an effect's `End` can be stale (J8 finding 2; targets, depth surfaces and shader binds were not affected).

## What exists (read before building)
- `proxy/src/capture.cpp` (the driver: 36 device-slot hooks, `WriteState`, `CapturePresent`, `CaptureRun`, `CaptureEvent`), `proxy/src/capture.h` (pure:
  the shader hash, the name and frame rules, the `Append*` record formatting), `proxy/tests/test_capture.cpp` (hash vectors, grammar, source lints: key
  off hooks nothing, every hook forwards at least twice, at least 30 hooks, no `Adapter()`), `proxy/src/dev.cpp` (`hk_Present` calls `CapturePresent`
  before the real Present; `Execute`'s `capture` branch calls `CaptureRun` with the ctl timeout, default 40 s), `proxy/src/backend.cpp` lines 147-149
  (the `D3DPERF_*` exports call `CaptureEvent` on whatever thread the game uses), `proxy/src/hooks.cpp` `VtableHook` (per-slot chain record, idempotent).
- The record format is documented only in the consumer's `proxy/README.md` "Frame capture" (napoleon-remastered); `capture.cpp` line 15 points there.
- The offline reader is the core's `discovery/shader_catalog.py` `summarize()`: it dispatches on the first word of each line and ignores tags it does not
  know; a `STATE` ... `ENDSTATE` block sets state without breaking a pass (`in_state`).
- `build.sh smoke` creates no device (the stand-in exe calls `Direct3DCreate9` only), so no CI step can run a capture. The proof here is pure code and
  source lints; the live proof is the consumer's (below).

## Decisions already made (follow them; a deviation goes in the report with its reason)
### The state machine (B32), pure, in `capture.h`
1. States: `Idle`, `Armed`, `Recording`, `Done`, `Abandoned`. Every transition is a compare-and-swap on one `LONG` (`InterlockedCompareExchange` in
   `capture.cpp`; the host test uses `std::atomic<long>` on the same pure functions):
   - ctl: `Idle -> Armed` (arm; refuse with "a capture is running" or, for `Abandoned`, "the previous capture is still closing: it ends at the next Present").
   - render, at a Present: `Armed -> Recording` **first**, then open `frame.txt`, write the header and the STATE block, set `s_rec`; a failed CAS (the ctl
     thread withdrew) does nothing at all. A failed file open goes `Recording -> Done` with the error.
   - render, last frame: write `PRESENT`, clear `s_rec`, close, then `Recording -> Done` and set the event.
   - ctl, first wait timed out: `Armed -> Idle` ("no Present within the timeout: nothing recorded", failed). If that CAS fails, the render thread owns it: wait
     the second (bounded, 30 s) wait.
   - ctl, second wait timed out: `Recording -> Abandoned`, return **failed** ("recording did not finish within <t> s: abandoned; the render thread closes
     frame.txt at its next Present"), and read none of the render thread's counters. If that CAS fails because the state is `Done`, the capture finished just
     in time: report it normally.
   - render, at a Present in `Abandoned`: write `ABANDONED frame <n> of <m>`, clear `s_rec`, close, then `Abandoned -> Idle` (nobody waits). A capture name
     is never reused, so an abandoned folder stays as evidence.
   - ctl, after reading a `Done` result: `Done -> Idle`.
2. Put the decisions in pure functions in `capture.h` (for example `CapArmFromCtl`, `CapOnPresent(state, frame, frames) -> action`,
   `CapOnTimeout(state, which) -> {next, result}`) so a host test drives them with two real threads; `capture.cpp` keeps the Windows calls (events, files) and
   uses only these transitions. No mutex in the hot path: the idle hooks stay one load and a branch.
3. The result of a failed capture names the state it ended in (`"state": "abandoned"` or `"nothing recorded"`); the ctl status is `failed`, as today for a
   capture error (`dev.cpp` unchanged unless the result needs a member).

### The render thread only (B33)
4. At arm (`CapturePresent`, `Armed -> Recording`) store `GetCurrentThreadId()` in `s_tid` **before** `s_rec` is set. While recording, a hook called on another
   thread forwards to the original and increments `s_otherCalls` (`InterlockedIncrement`); it never touches `s_depth`, `s_buf` or the describe sets. Put the
   thread test inside the `Depth` guard (after the existing `if (!s_rec)` fast path, so the idle cost does not change): `Depth::on` is false and `s_depth`
   is not touched on another thread. `CaptureEvent` takes the same test. `CapturePresent` on another thread while recording counts and returns.
5. The count is reported: a result member `other_thread_calls`, and one `OTHERTHREAD <n>` line before each frame's `PRESENT` when that frame's count is not 0.
   A game that draws on a thread other than its Present thread records nothing and says so (`draws` 0, `other_thread_calls` large): that is the honest
   answer, not a bug to work around.

### State blocks (B34)
6. Hook device slot 59 `CreateStateBlock` (record `SBCREATE <type> <ptr>`) and, on the state-block class, slot 4 `Capture` (`SBCAPTURE <ptr>`) and slot 5
   `Apply` (`SBAPPLY <ptr>`); `IDirect3DStateBlock9`: 0-2 IUnknown, 3 GetDevice, 4 Capture, 5 Apply. Keep the existing `SBBEGIN`/`SBEND`.
7. **Where the state-block vtable comes from:** at `CaptureInstall` (key on only), create one throwaway `D3DSBT_ALL` block through the original
   `CreateStateBlock` (before the slot-59 hook goes in, so it is never recorded), hook its vtable's slots 4 and 5 with `VtableHook` (first original kept, as
   the device slots), release it. If that create fails, log a warning, leave the device hooks as they are, and report `"state_block_hooks": false` in every
   result. The install log line names both counts (`capture: 37 of 37 device slots, 2 of 2 state-block slots hooked`).
8. **After an `Apply` while recording**, on the recording thread: `SBAPPLY <ptr>` and then a readback of the state the block may have changed, as a
   `STATE` ... `ENDSTATE` block written by the same code as the arm-time block **without** `BACKBUFFER`, `RT` and `DS` (a state block holds no render
   target or depth surface): render states, samplers and their textures, texture-stage states (add these to the readback: `GetTextureStageState`, slot 66,
   stages 0-7, the types `capture.cpp` already records), viewport, scissor, declaration, streams, indices, shaders, constants. The existing reader then
   applies it unchanged (`in_state` keeps the pass). The readback calls `Get*` only (not hooked); the `Depth` guard held by the `Apply` hook keeps any
   runtime-internal `Set*` it triggers from being recorded twice. Device for the readback: `IDirect3DStateBlock9::GetDevice` (slot 3), released after.
9. Result members `state_blocks_created`, `state_blocks_captured`, `state_blocks_applied` (this capture's counts). No new config key.

### The record format gets a core owner
10. Write `docs/PROXY_CAPTURE.md` (new, short): the `dev.capture` keys, the ctl verb and its result members, the threads and the state machine above, and the
    full `frame.txt` line list (today's list from the consumer's README plus `SBCREATE`, `SBCAPTURE`, `SBAPPLY` with its STATE readback, `OTHERTHREAD`,
    `ABANDONED`). `capture.cpp` line 15 and `capture.h` line 6 point at it; `docs/CONSUMING.md` "The proxy, the harness and the save tools" names it with the
    other contract docs. The consumer then replaces its README paragraph with a pointer.

## Scope: files this job touches
`proxy/src/capture.h` (the pure state machine), `proxy/src/capture.cpp` (states, thread test, three hooks, readback, results), `proxy/tests/test_capture.cpp`,
`docs/PROXY_CAPTURE.md` (new), `docs/CONSUMING.md`, `docs/BACKLOG.md` (remove B32, B33, B34), `VERSION`; `discovery/tests/` only for the reader test in
"Tests" (no change to `discovery/shader_catalog.py`: its output on an old capture must stay byte-identical, C20). `dev.cpp`, `dev.h` and `backend.cpp`
only if a signature must change (say why). No game names in core files (`tests/test_moved_tools.py` `NoGameNames`).

## Steps
1. Read "What exists". Check whether this session can build the host tests (`proxy/tools/build.sh tests` needs g++, plus `g++-mingw-w64-i686` for the DLL,
   or Docker); if not, push early and read CI's `proxy` job log.
2. **Failing tests first**, committed red, in `test_capture.cpp`: the state machine (every transition in decision 1, including the two races: the ctl
   withdraws while the render side has read `Armed`; `Done` against `Abandoned`), then a two-thread stress case (a "render" thread stepping Presents and a
   "ctl" thread arming and timing out at random, a few thousand rounds, seeded): it must never end with a state no one leaves, never record with no waiter
   and no `Abandoned`, and never let two captures overlap.
3. Build B32 (decisions 1-3), then B33 (4-5), then B34 (6-9), each its own commit.
4. Source lints in `test_capture.cpp` (update the existing ones that quote exact text, never weaken them): every `hk_` body takes `Depth` after the `s_rec`
   fast path; `Depth` and `CaptureEvent` test `s_tid`; `CapturePresent` arms with a compare-and-swap, never a plain exchange from `Armed`; `CaptureRun` sets
   `Idle` only from `Done` or by CAS from `Armed`; the hook count rises by three; key off still hooks nothing (the throwaway state block is created only
   inside `CaptureInstall` after its key check).
5. Reader test (`discovery/tests/`, or `tests/` if that is where `shader_catalog` is tested): a small `frame.txt` with `SBCREATE`, `SBAPPLY` and its STATE
   readback that changes a render state between two draws: `summarize()` attributes the second draw to the applied state; and an existing-format frame gives
   the same summary as before.
6. Docs (decision 10), backlog, `VERSION`; `python3 wsc.py gates` (full), CI's `proxy` job green, `python3 wsc.py policy --branch job/W19 --base origin/main`.

## Tests and acceptance
- The new `test_capture.cpp` cases red first, then green, with every existing proxy host test; the null game's `build.sh all`, `repro` and `smoke` green in
  CI (the smoke cannot capture: no device).
- The DLL builds with no new import (`build.sh` checks the import list).
- `python3 wsc.py gates` green; `policy` ok.
- No PC: the live proof is the consumer's first capture after the pin bump (below). Say so in the report; do not claim a capture you did not run.

## VERSION
A minor bump (new record lines, result members and hooks; the DLL inputs change). Take the next free minor at merge time: `origin/main` says 0.15.0 when
this brief was written, W7 (in review) expects 0.16.0, and other W rows may claim minors first. Re-read `origin/main` `VERSION` and the open `job/*`
branches before the last commit; the second to merge takes the next free number and merges `main` (never rebase). Say in the report which number you took.
Tags are Liam's.

## What consumers must do after the tag (napoleon-remastered)
- **Rule 79:** `proxy/src` is a DLL input, so the pin bump that crosses this tag gives a new build id and needs 20 consecutive acceptance passes on it. If the
  same bump also crosses W20 (UI host and gesture hardening) or W17 (stale ctl requests and peek), one 20-pass run on the final build id covers them all:
  bump across them together rather than one at a time.
- `proxy/README.md` "Frame capture": replace the line list with a pointer to `core/docs/PROXY_CAPTURE.md` and say "37 device slots and 2 state-block
  slots" instead of 36.
- Optional, a napoleon row of its own: one `land_small` capture with the new build to see whether `SBAPPLY` occurs at all in the game's frames; if it does,
  re-check the per-draw state claims of `discovery/napoleon/frame_anatomy.md` (J8 finding 2). Facts that rest on targets, depth surfaces and shader binds stand.

## Kill criteria
- The state machine cannot be made lock-free without a mutex on the idle hook path (the idle cost must stay one load and a branch): stop and report the
  design; do not add a lock to every hook.
- The throwaway state block cannot be created at install on the null game's code path, and hooking lazily at the game's first `CreateStateBlock` would put a
  `VtableHook` call in the game's hot path: stop B34 after about 20 calls, ship B32 and B33, keep B34 in the backlog with what was found.
- The STATE readback after `Apply` would need a hook on a `Get*` method, or records a `Set*` twice: stop that part, ship `SBAPPLY` lines and counts only
  (the backlog's minimum), and say so.
- Any change that makes the existing `test_capture.cpp` hash vectors or grammar cases change: stop and fix before anything else.
- Core CI red (the `proxy` job included) after three fix attempts for a cause in this change: stop and report.
- Version collision handled as in VERSION above; never rebase a pushed branch.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **The STATE readback after every `Apply`, or `SBAPPLY` lines only?** Recommended: the readback (decision 8). Lines alone tell a reader the state may be
   stale but not what it became, so the per-draw summaries stay wrong; the readback makes the existing reader right with no reader change. Cost: about 25 KB
   of text per `Apply` (constants dominate); a frame with hundreds of applies writes megabytes, which `Flush` already handles (4 MB chunks), and a capture is
   1-8 frames of a dev tool. If the first consumer capture shows files too large to use, a later row can diff against a shadow copy.
2. **Hook the state-block vtable at install (throwaway block) or at the first `CreateStateBlock`?** Recommended: at install (decision 7): deterministic,
   logged with the other slots, nothing added to the game's path. Every block the game makes passes the slot-59 or slot-61 hook either way.
3. **A key to turn the readback off?** Recommended: no; `dev.capture` is already dev-only and off in release.
4. **Abandon at the next Present, or let the recording finish its frames?** Recommended: at the next Present (decision 1): nobody reads the result, and a
   bounded file is better evidence than one that keeps growing after the driver gave up.
5. **File overlap with the other core rows**, for whoever merges second (merge `main`, never rebase):
   - **W17** (dev channel: stale requests, `peek`) touches `proxy/src/dev.cpp` and `devcore.h`; this job leaves both alone unless a signature must change.
   - **W20** (UI host and gesture hardening) touches `ui_host.cpp`, `gesture.cpp` and the gesture preview's state block; with this job a capture records the
     UI's and the preview's `CreateStateBlock`/`Apply` too (they go through the device vtable), which is correct and needs no change there.
   - **W7** (engine-site patch values) touches `patch_driver.cpp`, `patch_engine.h`, `config.h`: no overlap with capture code.
   - **W21** (core CI) changes `ci/gates.yml.in` and the fetchers' CI path; **W16** (the null game on its own) touches `build.sh`: none of these files here.
   - All rows: `docs/BACKLOG.md`, `docs/CONSUMING.md` and `VERSION`.

## Finish
Report in `jobs/W19/report.md` (what was built, the transitions and the stress test, the tests red then green and where they ran, the lints, the version
taken, deviations, open questions, what napoleon must do), then `wsc reg set jobs W19 status=review report=jobs/W19/report.md` (`python3 wsc.py`). Push
`job/W19`, open the draft pull request, and stop: an independent reviewer merges (C18); Liam tags.

# W19 report: Capture: timeout path, render thread only, state blocks

W19 fixes the frame capture's timeout path with one lock-free state machine (B32), records only the thread whose Present took the arm (B33), and hooks `CreateStateBlock` and `IDirect3DStateBlock9::Capture`/`Apply` with a STATE readback after each `Apply` (B34). The record format now has a core owner, `docs/PROXY_CAPTURE.md`. VERSION 0.21.0; branch `job/W19`. No capture was run: there is no PC and the null game creates no device, so the live proof is the consumer's first capture after the pin bump.

## What was built
- **B32, the state machine** (`proxy/src/capture.h`, pure):
  - One word, five states: Idle, Armed, Recording, Done, Abandoned. Every transition is a compare-and-swap through a `Cell` (`Load()`, and `Cas(expected, desired)` that returns the value it found). In `capture.cpp` the Cell is `StateCell`, wrapping `InterlockedCompareExchange` on `volatile LONG s_state`; in the host test it is `std::atomic<long>`. The host test runs the same transition code as the DLL.
  - The functions:
    - `CapArmFromCtl`: ctl, Idle -> Armed. Otherwise refused, with `running` or `closing`.
    - `CapOnPresent(cell, frame, frames)`: returns none, start, next_frame, finish or close_abandoned. From Armed it CASes to Recording first; a lost CAS does nothing at all.
    - `CapFinish`: render, Recording -> Done. If the ctl abandoned first, it does Abandoned -> Idle instead.
    - `CapClosed`: render, Abandoned -> Idle.
    - `CapOnTimeout(cell, second)`: first wait: Armed -> Idle (`nothing`), else `wait_more`, or `done` if already Done. Second wait: Recording -> Abandoned, or `done` if already Done.
    - `CapRelease`: ctl, Done -> Idle.
    - `CapRefusal` and `CapStateName`: the refusal and state texts.
  - Only the ctl leaves Idle and Done; only the render thread leaves Recording for Done and Abandoned for Idle.
- **B32, the driver** (`capture.cpp`):
  - `CapturePresent` acts on the action `CapOnPresent` returns. Abandoned is closed at the recording thread's next Present with `ABANDONED frame n of m`; `frame.txt` stays as evidence.
  - `CaptureRun`:
    - Refuses with a load before it writes anything the render thread reads, so nothing is written while an abandoned capture is still closing.
    - Arms by CAS. Waits the ctl timeout, then a second bounded 30 s if the render thread owns the capture.
    - Returns failed, with `"state": "nothing recorded"` or `"abandoned"` and only ctl-owned members (`dir`, `wait_s`, plus `file` when abandoned, and `state_block_hooks`). It reads none of the render thread's counters in that case.
    - `WaitDone` uses the event only to wake; the state decides. This closes a race the brief did not name: a late `SetEvent` from an earlier capture, after its ctl had seen Done just in time, could otherwise end the next capture's wait early.
  - No `InterlockedExchange` is left on the state.
- **B33, the recording thread only:**
  - `s_tid` is set at start, before `s_rec`.
  - `Depth` checks the thread after each hook's `if (!s_rec)` fast path, so the idle cost is unchanged. On another thread it increments `s_otherCalls` and never touches `s_depth`, `s_buf` or the describe sets.
  - `CaptureEvent` and `CapturePresent` make the same check.
  - Each frame's `PRESENT` (or `ABANDONED`) is preceded by `OTHERTHREAD n` when that frame's count is not 0. The result member is `other_thread_calls`.
- **B34, state blocks:**
  - Hooked: device slot 59 `CreateStateBlock` (`SBCREATE type ptr`), and on the state-block class slot 4 `Capture` (`SBCAPTURE ptr`) and slot 5 `Apply` (`SBAPPLY ptr`).
  - The state-block vtable comes from a throwaway `D3DSBT_ALL` block made in `CaptureInstall` after the key check, through the original `CreateStateBlock` before the slot-59 hook goes in, and released at once.
  - If that create fails: a warning is logged, the device hooks stay, and every result says `"state_block_hooks": false`.
  - The log line reads `capture: 37 of 37 device slots, 2 of 2 state-block slots hooked`.
  - After an `Apply` on the recording thread, `WriteState(dev, false)` writes a STATE block without `BACKBUFFER`, `RT` or `DS`. The device comes from `GetDevice` (slot 3) and is released after. The reads are `Get*` only (none hooked), and the held `Depth` keeps any runtime-internal `Set*` unrecorded.
  - `GetTextureStageState` (slot 66, stages 0-7, every defined D3DTSS value) was added to the shared STATE code.
  - Result members: `state_blocks_created`, `state_blocks_captured`, `state_blocks_applied`, `state_block_hooks`.
- **Docs:**
  - `docs/PROXY_CAPTURE.md` (new) covers the keys, the ctl verb and every result member, the threads, the transition table, and the full `frame.txt` line list (the consumer's list plus the W19 lines).
  - `capture.cpp` and `capture.h` point at it.
  - `docs/CONSUMING.md` names it with the other proxy contract docs.
  - B32, B33 and B34 are removed from `docs/BACKLOG.md`.
- **Unchanged:** `dev.cpp`, `dev.h`, `devcore.h`, `backend.cpp` and `discovery/shader_catalog.py`. No new DLL import: the import list is advapi32, dbghelp, kernel32, msvcrt and user32.

## Tests, red then green
- **Red first:** commit d533211 (the state-machine tests only) does not compile without the new functions. Locally in an ubuntu:24.04 container: 122 error lines. In CI: run 41720388641, proxy job failed.
- **Green** (`proxy/tests/test_capture.cpp`):
  - Every transition, one case each.
  - Race 1: the render side read Armed, then the ctl withdrew. A `StaleCell` gives the stale load; the result is none, still Idle.
  - Race 2, both orders: Done before the ctl's timeout is reported normally; Abandoned before the render's finish leaves the render to close and go Idle.
  - Arming while Abandoned gives `closing`.
  - The refusal and state texts.
- **Stress:** a render thread steps Presents with random yields, including occasional long pauses; a ctl thread arms and times out at random. 4 seeds x 1500 captures.
  - It checks: a recording starts only with a waiter and never over an open file; the result the ctl reads is its own capture's (id check); the end state is Idle with no file open; and a ctl that is refused forever counts as an error, so a state no one leaves fails the test instead of hanging.
  - Typical run: 6000 captures, about 950 done, 4300 nothing recorded, 750 abandoned. Every path is taken; this is checked.
  - Mutation check (local, not committed): a plain store on the first timeout gave 848 errors; a plain store from Armed at a Present ended in Done forever (final state 3, the bug the brief describes). Both were caught.
- **Source lints** (existing exact-text lints unchanged; `hooks >= 30` tightened to exactly 39):
  - Each of the 39 `hk_` functions starts with its `if (!s_rec) return o_<name>(` fast path, with `Depth g;` after it.
  - 39 install-table rows, including slot 59 and state-block slots 4 and 5.
  - `InterlockedExchange(` occurs 0 times and `InterlockedCompareExchange(` once (`StateCell`); `s_state =` only at its definition.
  - `CapturePresent` uses `CapOnPresent(s_cell, ...`; `CaptureRun` uses `CapArmFromCtl`, both `CapOnTimeout` calls and `CapRelease`.
  - `s_tid` is set before `s_rec = true;`; `Depth` and `OnRecordingThread` text checks; in `CaptureEvent` the thread test comes before `s_depth`, which comes before `Line(`; the Present other-thread check.
  - The throwaway block is made inside `CaptureInstall` after the key check and before the hook loop, and only once.
  - `hk_SBApply` calls `WriteState(d, false)`.
- **Reader test** (`discovery/tests/test_shader_catalog.py`, new):
  - A frame in the old format matches a summary written down from the unchanged reader.
  - The new tags `SBCREATE`, `SBCAPTURE`, `OTHERTHREAD` and `ABANDONED` change nothing.
  - An `SBAPPLY` with its STATE readback turning alpha blending on between two draws keeps one pass with 2 draws; the second draw is attributed `blend1`.
- **Where they ran:**
  - Full `build.sh all` on the null game in an ubuntu:24.04 container (the DLL with -Werror, imports and exports checked, every C++ host test green).
  - `python3 wsc.py gates` full on Windows: 13 ok, 1 warn (environment skips).
  - CI run 41722124488 on f4daf43: gates on ubuntu and windows, harness-windows, and proxy (build, repro, wine smoke) all green. Attempt 1 of the proxy job was cancelled at the 30-minute limit during a slow apt download of wine and re-run.

## Version
0.21.0. `origin/main` was 0.17.0 (W14 merged into this branch); the open branches claimed 0.17.1 (W11), 0.18.0 (W17), 0.19.0 (W8) and 0.20.0 (W13). Whoever merges after another of these merges `main` (never rebase) and takes the next free number.

## Deviations
1. The pure functions take a Cell (`Load`/`Cas`) instead of a state value (`CapOnPresent(cell, frame, frames)` and so on). This puts the CAS itself in the shared code, so the two-thread test runs the DLL's exact transitions. The brief's signatures were examples. Added `CapFinish`, `CapClosed`, `CapRelease`, `CapRefusal` and `CapStateName`.
2. `CaptureRun` refuses with a plain load before arming by CAS. Only the single ctl thread leaves Idle, so an Idle it reads stays Idle until its own arm. This keeps it from writing `s_dir`, `s_frames` or `s_err` while the render thread is still closing an abandoned capture. The arm itself is still `CapArmFromCtl`.
3. `WaitDone` lets the event only wake the ctl; the state decides (the late `SetEvent` race above, not named in the brief).
4. If the ctl abandons between the render thread's decision to finish and its Recording -> Done, the file is already complete and closed with `PRESENT` but no `ABANDONED` line. The render thread then goes Abandoned -> Idle and the ctl reports `abandoned`.
5. Texture-stage states were added to the shared STATE code, so the arm-time block now carries `TSS` lines too (decision 8 asks for one shared writer). The reader ignores `TSS`.
6. In the abandoned message, `<t>` is the seconds since arm (the ctl timeout plus up to 30).
7. A failed `frame.txt` open now reports this capture's zeroed counters; before, it reported the previous capture's (it already did so before W19).
8. On a second device of the same class, the throwaway block uses the kept original `CreateStateBlock` when slot 59 is already hooked, so it is never recorded.
9. `README.md`'s layout table was not changed (not in the brief's file list; it already omits `PROXY_UI` and `PROXY_GESTURES`).
10. Report and row: the build ran as a subagent, which cannot write report files, so the orchestrator wrote this report from the builder's text and set the row to review (same Claude-Session as the build).

## Open questions
- Is one state-block class enough? The D3D9 runtime (and DXVK) use one class for every block, but a device of another class, or a wrapper with several block classes, would leave some `Apply` calls unseen. The consumer's install log line and `state_blocks_*` counts will show it.
- On a pure device (`D3DCREATE_PUREDEVICE`), `Get*` may fail, so both the arm-time block and the `Apply` readback would be thin. This was already true of the arm-time STATE block.
- If the recording thread stops presenting while a capture is Abandoned, every later capture is refused as "still closing" until the game restarts. This follows decision 4 (close at the next Present).
- Readback size is about 25 KB per `Apply`. If the first consumer capture is too large to use, a later row can diff against a shadow copy (brief open question 1).

## What napoleon must do
- **Rule 79:** the pin bump that crosses v0.21.0 gives a new build id (`proxy/src` changed) and needs 20 consecutive acceptance passes on it. If the same bump also crosses W17 (0.18.0) or W20, one 20-pass run on the final build id covers them all.
- `proxy/README.md` "Frame capture": replace the line list with a pointer to `core/docs/PROXY_CAPTURE.md` and say "37 device slots and 2 state-block slots" instead of 36.
- A timed-out capture is now `failed` with `"state": "abandoned"` or `"nothing recorded"` (before, it returned ok with a partial frame).
- Optional, a row of its own: one `land_small` capture with the new build, to see whether `SBAPPLY` occurs. If it does, re-check the per-draw state claims of `discovery/napoleon/frame_anatomy.md` (J8 finding 2). Facts that rest on targets, depth surfaces and shader binds stand.

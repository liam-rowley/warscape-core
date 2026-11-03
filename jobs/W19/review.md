# W19 review

## Round 1 (2026-11-03, branch job/W19 at 8c74089)

**Verdict: merge.**

Reviewer: a fresh session (Claude-Session 60a12cbd-1c0b-4676-b0d2-32a045f88082; the builder's was a3c823fa-f176-4a15-ac97-f5c8704325bb).

### Machines
- `python3 wsc.py gates` (full, Windows): 12 ok, 2 warn (`hooks` not wired in this worktree; 5 environment skips in `tests`), 0 failed.
- `discovery/tests/test_shader_catalog.py`: 3 tests OK locally.
- No g++ or Docker on this machine: the C++ host tests and the DLL ran in CI. The report's evidence holds: run 41720388641 at d533211 (the tests only)
  is red on `proxy` and green elsewhere; run 41722124488 at f4daf43 is green on every job. CI on 8c74089 (this review's fix plus the `main` merge) is the
  merge gate.
- `policy --branch job/W19 --base origin/main`: ok after this review and the row.

### Against the brief
Every deliverable is there: the pure state machine in `capture.h` (every transition a CAS through a `Cell`, the same code in the DLL and the host test),
the five states and their owners as decision 1 says, the two named races and the late-`SetEvent` race (deviation 3) handled, the recording-thread test
inside `Depth` after each `if (!s_rec)` fast path (idle cost unchanged), `OTHERTHREAD` and `other_thread_calls`, slot 59 plus state-block slots 4 and 5
from a throwaway `D3DSBT_ALL` block made after the key check through the original `CreateStateBlock`, the `Apply` readback without targets (TSS added to
the shared writer), the `state_blocks_*` and `state_block_hooks` members, `docs/PROXY_CAPTURE.md`, the `CONSUMING.md` pointer, B32-B34 out of the
backlog, `dev.cpp`/`backend.cpp` and `shader_catalog.py` unchanged. The ten deviations are named with reasons and none widens scope. VERSION 0.21.0 is
still free (`main` 0.18.0; open claims 0.19.0 W8, 0.20.0 W13, 0.22.0 W21).

### Risk-first reading
Picked `CapturePresent` and `CaptureRun` (two threads on one file handle and buffer inside the game's Present; a mistake is a crash or a stuck capture),
then `CaptureInstall`'s throwaway block and `hk_SBApply` (code on the game's device at create time and in every effect's `End`). The install path and the
readback are sound (GetDevice's reference released; the readback runs under the `Apply` hook's `Depth`; a second device uses the kept original).

### Findings
1. **should-fix, fixed in this review (85fa7a7):** `proxy/src/capture.cpp` `CapturePresent` (line 460 at ab35035). The other-thread test ran only with
   `s_rec` set. Between the recording thread's `Armed -> Recording` CAS and its `s_rec = true` (file open, header, a full STATE block: the widest window),
   and again between its `s_rec = false` and `CapFinish`/`CapClosed`, a `Present` on a second thread (a second swap chain or device presented elsewhere)
   read Recording or Abandoned with `s_rec` clear and ran `next_frame`, `finish` or `close_abandoned`: `Line()` on `s_buf` and `Close()` on `s_file`
   concurrently with the recording thread, or a `finish` that set Done before a single frame was written. B33's goal (only the recording thread writes)
   did not hold for `Present` itself. How to see it: two threads presenting while a capture arms; the pure stress case cannot show it because the gate
   is in driver code with one Present thread. Fix: `s_rec` is read once into `rec` (before `s_tid`), and with it clear only `start` (or `none`) acts;
   a lint in `test_capture.cpp` pins the order (read, guard, switch).
2. **later, B63 added to `docs/BACKLOG.md` on this branch:** move that gate into `capture.h` (`CapOnPresent` taking `rec`) and give the stress case a
   second Present thread, so the rule is tested, not linted; and a way out for an Abandoned capture whose recording thread never presents again (the
   report's own open question 3: every later capture is refused until the game restarts).

### Merge of main
`main` moved to 0.18.0 (W11, W17) and `VERSION` conflicted; merged `origin/main` into the branch (never rebase) keeping 0.21.0 (8c74089). No other
conflict; `proxy/src/dev.cpp` changes from W17 do not touch the capture calls.

### For the consumer
As the report says: rule 79 (new build id, 20 passes; one run across W17 and W19 together), the README pointer and "37 device slots and 2 state-block
slots", a timed-out capture is now `failed`. No live capture was run by anyone: the first consumer capture is the live proof.

# W18 report: Headless display guard (built, host-tested; PC proofs a, b, d passed 2026-11-06; c not run)

Built the three headless-guard changes (B19 show-time WinEvent hook, B22 logical own-move rect, B23 status rewritten after each verified relocation) with host tests red first, then green; the PC proofs a, b and d ran in a second sitting on 2026-11-06 (after Liam moved the stray `napoleon_remastered.ini` aside) and all pass; evidence in `jobs/W18/runs/20261106_w18pc/`.

## What was built
- `proxy/src/display_guard.h`: `ShowEventHides` (wraps `SweepHides`; window object, top level, same process); `OwnMove` gains `logical`/`haveLogical`; `IsOwnMove` accepts the physical rect exactly or the logical one within 1 px per edge (`NearRect`, `OwnMoveArmed`); `Status.relocations` written by `StatusJson` before `written_utc`.
- `proxy/src/headless.cpp`: `SetWinEventHook(EVENT_OBJECT_SHOW, ... OUTOFCONTEXT | SKIPOWNTHREAD)` on the guard thread before its loop (failure: `LOGW`, sweep only); the loop's `Sleep(4)` is `MsgWaitForMultipleObjects` plus a `PeekMessageW` drain outside `Lock`; `ShowEventCb` logs `... hidden at show (winevent)` (budgeted). `PlaceLocked` arms the logical rect for a window whose DPI context is not per-monitor (`LogicalRect`, functions by `GetProcAddress`); `OwnLocked` logs a once-per-arming near-miss line with both rects and the message numbers. `RelocateLocked`'s success branch updates `s_st` (sizes, `detail`), increments `relocations` and calls `WriteStatus()`; `state` is untouched; nothing is written at the cloak.
- The sweep is unchanged (backstop). No new config key.
- Docs: `docs/PROXY_HARNESS.md` ("The headless guard", where the proxy section of CONSUMING.md moved; CONSUMING.md is at the 30 KB cap), `docs/UPGRADING.md` (consumer steps). Row: `semver=minor`; `VERSION` not edited (jobs no longer do).

## Tests, red then green
Commit ce1860b/the next one: the new cases in `test_display_guard.cpp` (`ShowEventHides` all nine cases plus an equivalence loop against `SweepHides`; `IsOwnMove` logical at 125 % and 150 %: exact, one pixel off per edge accepted, two refused, physical accepted, expired, NOMOVE/NOSIZE, unarmed, no logical armed; `StatusJson` `relocations` 0 and 3 and field order; source lints for the hook before the loop, the drain before `Lock l;`, `WriteStatus()` and `++s_st.relocations` in the success branch and no `s_st.state` there) failed to compile (missing symbols). After the change: `test_display_guard` 328 passed, 0 failed; all 17 core host tests and the null game test pass; the DLL compiles under mingw. CI (`gates`, `proxy`, `harness-windows`) was not seen by this session; check the draft PR.

## PC proofs (evidence: `jobs/W18/runs/20261106_w18pc/`, README there; host-only record in `20261106_w18host/`)
Sitting 2026-11-06, run id 20261106_w18pc: lock `w18`, DLL build `a005f6cccc17-dirty` sha256 `a588edd7...` from a scratch napoleon tree (main 95e72d6a, pin 0.30.0 plus the two `config_keys` rows), installed watcher 1.4.0 (did not stop any proof), core merged with origin/main (82cdce4, VERSION 0.46.1).
- **a (B19) pass:** the `hidden at show (winevent)` line (13:38:46.091) precedes the `TEST HOOK ... shown` line (.143): the hide happens before the test thread logs, so 0 ms after the show (limit 15). Probe: that window `visible_on_real_ms` 0, `longest_visible_on_real_ms` 0 (limit 25; J12's sweep-only run 109), game window 0.
- **b (B23, 100 % own move) pass:** `-Origin 3840,0` (the new layout has no 2560,0 slot): relocated, verified 2026-11-06 run 20261106_w18pc, uncloaked at 37.1 s; status `relocations` 1, `target.rect` 3840,0,7680,2160, `state` unchanged `on_virtual`; `shot.sh` shot "at 3840,0". `-Restore`: `relocations` 2, rect 3839,2160,..., shot "at 3839,2160". Probe 0 ms on a real monitor, cloaked 1304 ms in all, no near-miss line.
- **d (no regression) pass:** plain launch `on_virtual` at 1.3 s, probe 0 ms, no new warning (the one WARN is the existing crash-filter line), `relocations` 0.
- Uninstall: game folder identical to the pre-install snapshot (1564 files), exe vanilla, lock released, no `vdisplay_restore.json`. The virtual display ended at its starting origin.
- **c (B22 at a scaled display): not run** (needs Liam's scale change; open question 2).

## Deviations and limits
- `LogicalRect` asks `PhysicalToLogicalPointForPerMonitorDPI(h, ...)` before the move, while the window may still be on another monitor, so the logical rect is only as good as that call; the near-miss line is the evidence if a scaled target shows a rect that matches neither. This is the brief's design, flagged because only a scaled display can prove it.
- The simulation in the tests still models only the sweep; the hook is covered by `ShowEventHides` and the lints, the real timing by proof a.

## Backlog rows (BACKLOG.md is gone)
B19, B22, B23 are the `later` rows **W51, W52, W53**. A job branch may not edit them, so a `plan/` follow-up should: set W51 and W53 to `done` (or superseded by W18) when W18 merges after proof a and b; leave W52 `later` (reworded to "PC proof at a scaled display") until proof c, or set it done if Liam accepts host tests alone. Not done here.

## Open questions
1. ~~Move the stray `napoleon_remastered.ini`?~~ **Answered 2026-11-06:** Liam moved it aside himself; the sitting ran without `--move-stray` and the proofs a, b, d passed.
2. Proof c at 125 % or 150 % virtual display? Recommended: not unless he wants it (the host tests cover the rect logic; the near-miss line gives the evidence the first time a scaled target occurs). Without it W52 stays `later`.
3. Version: take the next free minor at merge (`origin/main` VERSION is 0.46.1 today; the release workflow tags).

## What napoleon must do after the tag
See `docs/UPGRADING.md` "DLL changes: the headless guard (core W18)": rule 79 (20 acceptance passes on the new build id), its Headless doc names the hook, the logical rect and the status rewrite; no adapter or key change. Its pin (0.30.0) also needs the earlier sections' `config_keys` rows (`proxy.file_rules`, `proxy.dxvk_wndproc_fix`).

## Fix round 1
Round 1 verdict: merge after fixes. All three findings are addressed. B22 now arms, but it has not been proven with the game on a scaled target (see Limits).

**1. Blocker, B22 inert: fixed by the review's option (a).** Commits 77e10f4 (red tests, the probe) and c67d801 (the fix).
- `LogicalRect` no longer asks the window. It reads the target monitor in the window's DPI context (`DpiScope d(ctx)`, `GetMonitorInfoW(s_t.hmon, ...)`) and maps `want` through the new pure `LogicalOnMonitor(phys, physMon, logMon, out)` in `display_guard.h`. **This deviates from brief decision 2**, which prescribed the point conversion; that call refuses any point outside the window (run 20261106_w18review).
- The review had not proven that the message carries this mapping, so I measured it first (verified 2026-11-06, run 20261106_w18fix): a window in each DPI context, hidden and shown-cloaked, moved with `PlaceLocked`'s flags across all three monitors. The message matches within 1 px on every edge, and exactly for a whole monitor, the main window's only move. No display setting changed.
- One thing the review's sketch did not have: an unaware context keeps a monitor's origin and scales its size, a system-aware one scales the origin too. So the map reads both monitor rects and derives no scale from a DPI.
- Tests: `TestLogicalOnMonitor` uses the measured rows (125 % and 150 %, non-zero origins, both contexts, rects inside a monitor), feeds each real message to `IsOwnMove`, and covers an unchanged monitor and an empty one. A lint refuses the old call in `headless.cpp` and pins the order scope, then monitor query, then map. Red: failed to compile (`LogicalOnMonitor` not declared). Green: `test_display_guard` 369 passed, 0 failed; 17 core host tests and the null game test pass; the DLL builds. CI at c67d801, run 42232966335: green.
- Docs and comments corrected: `docs/PROXY_HARNESS.md`, `docs/UPGRADING.md`, the comment above `kOwnMoveMs`, `headless.cpp`'s header. Both docs now say the map is measured with a probe window, not with a game.

**2. Should-fix, proof b's first status was quoted: fixed.** 71210f1 commits `b_headless_status_after1.json` (`"relocations": 1`, rect 3840,0,7680,2160, `state` `on_virtual`) and the `shot.sh` output as text.

**3. Should-fix, the proofs must name the DLL that merges: fixed.** 71210f1, run 20261106_w18pc2, verified 2026-11-06: a, b and d pass on sha256 `5d646e47...` from core c67d801, each log's `self_hash` line carrying it. Commits after c67d801 change no `proxy/` file. The PC is back as it was: status identical to the record before, folder identical to the snapshot (1564 files), exe vanilla, lock released, scratch clone removed.

**Later, proof a's wording: done on the re-run.** The new README calls the log order a bound and the probe the measurement: first seen already cloaked, `visible_ms` 11 = `cloaked_ms` 11, 0 ms on a real monitor. W51 to W53 are untouched: they are for the round that merges.

### Limits and what went wrong
- **B22 is not proven with the game.** The proofs ran at 96 DPI, where nothing is armed (no `own move armed` line in any log), so they show no regression, not the logical arm. It rests on the host tests and the probe, which is a Python window, not Napoleon. Proof c stays Liam's opt-in; W52 should stay `later` as "PC proof at a scaled display" unless he accepts this.
- **The build id cannot tell these DLLs apart.** The logs say `a005f6cccc17-dirty`, the same as the first sitting's different DLL, because `build_id.py` hashes the inputs at the superproject's gitlink and a scratch tree's newer core only adds `-dirty`. By design, but anyone reading the id alone would think nothing changed: the sha256 and core commit name the DLL. The real id comes with the pin bump, whose rule 79 run is on that id.
- **One b launch was discarded.** It moved the origin 5.2 s after start, during loading, because a wait of mine was refused and the next call ran at once. It is kept, labelled, in the run folder; the counted launch moved at 61.9 s.
- **Local full `wsc gates`:** 15 ok, 1 warn, 0 failed in 695.6 s. The warn is `tests`: 1383 host tests passed, 5 skipped here (a POSIX hook test, four that need capstone). A first run was cut off by my own 560 s limit and gave no result. `wsc policy` refuses only for the missing merge verdict and the `done` row, as expected.
- J99: the user said it was on the PC, but the watcher showed the lock free, the game not running and an empty queue at each check, so the sitting went ahead on that rule. The lock was released between launches, so another job could have taken it; none did.

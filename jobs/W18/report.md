# W18 report: Headless display guard (built and host-tested; the PC proofs did not run)

Built the three headless-guard changes (B19 show-time WinEvent hook, B22 logical own-move rect, B23 status rewritten after each verified relocation) with host tests red first, then green; the PC proofs a, b and d are **not run** because `pc_deploy install` refuses while Liam's stray `napoleon_remastered.ini` is in the napoleon game folder. A `needs_pc` job: the reviewer cannot merge it until those proofs exist.

## What was built
- `proxy/src/display_guard.h`: `ShowEventHides` (wraps `SweepHides`; window object, top level, same process); `OwnMove` gains `logical`/`haveLogical`; `IsOwnMove` accepts the physical rect exactly or the logical one within 1 px per edge (`NearRect`, `OwnMoveArmed`); `Status.relocations` written by `StatusJson` before `written_utc`.
- `proxy/src/headless.cpp`: `SetWinEventHook(EVENT_OBJECT_SHOW, ... OUTOFCONTEXT | SKIPOWNTHREAD)` on the guard thread before its loop (failure: `LOGW`, sweep only); the loop's `Sleep(4)` is `MsgWaitForMultipleObjects` plus a `PeekMessageW` drain outside `Lock`; `ShowEventCb` logs `... hidden at show (winevent)` (budgeted). `PlaceLocked` arms the logical rect for a window whose DPI context is not per-monitor (`LogicalRect`, functions by `GetProcAddress`); `OwnLocked` logs a once-per-arming near-miss line with both rects and the message numbers. `RelocateLocked`'s success branch updates `s_st` (sizes, `detail`), increments `relocations` and calls `WriteStatus()`; `state` is untouched; nothing is written at the cloak.
- The sweep is unchanged (backstop). No new config key.
- Docs: `docs/PROXY_HARNESS.md` ("The headless guard", where the proxy section of CONSUMING.md moved; CONSUMING.md is at the 30 KB cap), `docs/UPGRADING.md` (consumer steps). Row: `semver=minor`; `VERSION` not edited (jobs no longer do).

## Tests, red then green
Commit ce1860b/the next one: the new cases in `test_display_guard.cpp` (`ShowEventHides` all nine cases plus an equivalence loop against `SweepHides`; `IsOwnMove` logical at 125 % and 150 %: exact, one pixel off per edge accepted, two refused, physical accepted, expired, NOMOVE/NOSIZE, unarmed, no logical armed; `StatusJson` `relocations` 0 and 3 and field order; source lints for the hook before the loop, the drain before `Lock l;`, `WriteStatus()` and `++s_st.relocations` in the success branch and no `s_st.state` there) failed to compile (missing symbols). After the change: `test_display_guard` 328 passed, 0 failed; all 17 core host tests and the null game test pass; the DLL compiles under mingw. CI (`gates`, `proxy`, `harness-windows`) was not seen by this session; check the draft PR.

## PC proofs (evidence: `jobs/W18/runs/20261106_w18host/`)
- a (B19, 15 ms / 25 ms), b (B23 and the 100 % own move), d (plain launch): **not run.** `pc_deploy status` (2026-11-06) shows nothing installed and a stray `napoleon_remastered.ini` (10957 bytes) that waits on Liam; `install` refuses a stray unless `--move-stray`, which moves the file. Told to leave it, I stopped. No lock taken, no launch, game folder and watcher untouched. The watcher on the PC is 1.4.0 (core has 1.5.0); this job does not need the update.
- The DLL does build against napoleon: a scratch tree at main (pin 0.30.0, not 0.9.0 as the brief said) needed only two `config_keys` rows (`proxy.file_rules`, `proxy.dxvk_wndproc_fix`) and `gen_tables.py`; build a005f6cccc17, sha256 a588edd7..., all host tests pass. Scratch tree removed.
- c (B22 at a scaled display): not run, needs Liam's opt-in (open question 2).

## Deviations and limits
- `LogicalRect` asks `PhysicalToLogicalPointForPerMonitorDPI(h, ...)` before the move, while the window may still be on another monitor, so the logical rect is only as good as that call; the near-miss line is the evidence if a scaled target shows a rect that matches neither. This is the brief's design, flagged because only a scaled display can prove it.
- The simulation in the tests still models only the sweep; the hook is covered by `ShowEventHides` and the lints, the real timing by proof a.

## Backlog rows (BACKLOG.md is gone)
B19, B22, B23 are the `later` rows **W51, W52, W53**. A job branch may not edit them, so a `plan/` follow-up should: set W51 and W53 to `done` (or superseded by W18) when W18 merges after proof a and b; leave W52 `later` (reworded to "PC proof at a scaled display") until proof c, or set it done if Liam accepts host tests alone. Not done here.

## Open questions
1. Move the stray `napoleon_remastered.ini` (to `_to_delete`, never deleted) or tell me to continue another way? Recommended: Liam decides what that file is; then rerun the sitting (lock, install the DLL from build a005f6cccc17, proofs a, b, d, uninstall, reinstall nothing since nothing was installed).
2. Proof c at 125 % or 150 % virtual display? Recommended: not unless he wants it.
3. Version: take the next free minor at merge (`origin/main` VERSION is 0.45.0 today; the release workflow tags).

## What napoleon must do after the tag
See `docs/UPGRADING.md` "DLL changes: the headless guard (core W18)": rule 79 (20 acceptance passes on the new build id), its Headless doc names the hook, the logical rect and the status rewrite; no adapter or key change. Its pin (0.30.0) also needs the earlier sections' `config_keys` rows (`proxy.file_rules`, `proxy.dxvk_wndproc_fix`).

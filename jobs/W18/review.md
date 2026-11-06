# W18 review

## Round 1 (2026-11-06, branch job/W18 at 92c5414)

**Verdict: merge after fixes.**

B19 and B23 are built and proven: proofs a, b and d hold against their logs and probes. B22 is not delivered. The logical rect is never armed for a real relocation, because the Windows call the brief chose refuses a point outside the window, and the docs say it works. No file outside the job folder was changed in this round.

### Blocker

**1. B22 is inert: `LogicalRect` cannot convert a target the window is not already on.** `proxy/src/headless.cpp:110`, called at `:270`.
- **What fails:** `PlaceLocked` calls `LogicalRect` before `SetWindowPos`, so it asks `PhysicalToLogicalPointForPerMonitorDPI(h, ...)` for the target's corners while the window is still at its old rect. That call refuses a point outside the window. Two same-sized rects have both corners of one inside the other only when they are identical, so for a main window moving to a new target `LogicalRect` returns false, `haveLogical` stays false and `IsOwnMove` is physical-only, as before this job. A DPI-unaware window at a scaled target still has the guard's move dropped and stays cloaked, which is the bug B22 was raised for. The near-miss line is the only change it would see.
- **How to see it fail:** `jobs/W18/runs/20261106_w18review/` (verified 2026-11-06, run 20261106_w18review): a never-shown DPI-unaware window on DISPLAY1 (dpi 144), physical rect 150,150 450,450. Inside and on the edge `ok=1`; (500,500) and (7000,3000) `ok=0`, point unchanged. Proof b would have the same shape: window at 3839,2160, target 3840,0.
- **Why nothing caught it:** the host tests exercise `IsOwnMove` with a logical rect handed to them; nothing tests `LogicalRect`, and it needs Win32. Proofs a, b and d ran at 96 DPI, where the call's result does not matter. The report's first deviation flagged this call as unproven, and brief decision 2 prescribed it, so this is a fault in the brief's design that the builder followed and named.
- **False claims it leaves:** `docs/PROXY_HARNESS.md:81`, `docs/UPGRADING.md:122` ("recognised at a scaled target DPI"), the comments in `display_guard.h` above `kOwnMoveMs` and in `headless.cpp`'s header.
- **Fix, either of:**
  - **(a) Compute the rect without that call.** Take the target monitor's rect as the window's DPI context sees it (`SetThreadDpiAwarenessContext(GetWindowDpiAwarenessContext(h))`, `GetMonitorInfoW(s_t.hmon)`, restore) and map `want` through a pure function in `display_guard.h` from physical monitor rect to logical monitor rect, host-tested at 125 % and 150 % with a non-zero origin. Add a lint that `PhysicalToLogicalPoint` is not used for the arming. This reviewer has not proven that a DPI-unaware window's `WM_WINDOWPOSCHANGING` carries exactly that mapping. DISPLAY1 (144) and DISPLAY2 (120) are already scaled, so a never-shown probe window can test it with no display setting changed; proof c stays Liam's opt-in. This is a deviation from decision 2: name it in the report.
  - **(b) Take the brief's kill criterion** (stop B22, ship B19 and B23): remove the arming, keep the near-miss line as the evidence, correct the docs and comments, and say so in the report, so that W52 stays open with its real state.

### Should-fix

**2. Proof b's first status is quoted, not evidence.** `jobs/W18/runs/20261106_w18pc/README.md` "b." The brief's pass needs `"relocations": 1` and the new rect in the status, but only the status after the restore is committed (`b_headless_status_after2.json`). The `shot.sh` lines ("at 3840,0") are quoted too, and the two 1280x720 JPEGs show the game's front end but carry no rect. The log (`b_proxy.log.txt:191`, `:201`) and a final count of 2 make the claim very likely, so this is a gap, not a doubt.

**3. The proofs must name the DLL that merges.** Either fix changes `proxy/src`, so build id `a005f6cccc17-dirty` stops being what ships. Re-run a, b and d on the new build in a new run folder, and commit `b_headless_status_after1.json` and the `shot.sh` output as text, which closes finding 2. The PC rules in the brief apply again, including the lock and putting the PC back.

### Later (no action on this branch unless a re-run touches the file)

- **Proof a's "0 ms after the show" is a bound, not a measurement.** The `TEST HOOK` line is written after `CreateWindowExW` returns (`headless.cpp:417`, the window is created `WS_VISIBLE`), 52 ms after the hide line, so the brief's 15 ms limit passes trivially. The real evidence is the probe: first seen at 17336 ms, already cloaked (`visible_ms` 54 = `cloaked_ms` 54, `visible_on_real_ms` 0), at about 10.8 ms a sample. Proof a stands; word it that way on a re-run.
- **Rows W51, W52, W53.** They stay `later` until this merges. The round that merges should send the `plan/` follow-up: W51 and W53 done; W52 by what the fix chose.

### What was checked

- **Proofs against the brief, run 20261106_w18pc:**
  - **Build:** all three logs load `a005f6cccc17-dirty`, sha256 `a588edd7...`. `proxy/src` and `proxy/tests` are unchanged from 45e5fe6 to 92c5414, so that DLL is the head's source. The build was made from a scratch tree whose core was 45e5fe6 in the host record and 82cdce4 in the PC README; the same sha fits, since only `proxy/tools/pc_deploy.py` and `harness/` differ under the tools the merge brought.
  - **a:** hide line 13:38:46.091, test line .143; window `1980018` on real 0 ms, limit 25; game window 0.
  - **b:** two relocations verified and uncloaked (37.095 s, 75.340 s); `state` still `on_virtual`; `relocations` 2 at the end; probe 0 ms; no near-miss line. `-Origin 3840,0` instead of 2560,0 is a named deviation with a reason (layout changed 2026-11-05).
  - **d:** `relocations` 0, probe 0 ms, one WARN (the existing crash-filter line), no `winevent` line.
  - **Stray ini:** the report says Liam moved it himself. Liam says it was moved through a watcher job at his word; this changes nothing here.
  - **PC put back:** at review time the game folder has no `d3d9.dll` and no `napoleon_remastered.ini`.
- **Risk-first reading:** the guard thread's pump and `ShowEventCb`, because a hang there stops the game. `Lock` is a recursive `CRITICAL_SECTION`, the drain is outside it, and `ShowEventCb` follows `SweepCb`'s order. Windows the gate creates are created without `WS_VISIBLE` and enter `s_wins` before any show, so the hook cannot race a guarded window. Also read: `RelocateLocked`'s status write (`WriteStatus` fills the target from `s_t`, `state` is not assigned, `s_cs` is held).
- **The brief:** decisions 1 and 3 followed; decision 4, no key; 2 followed, and it is what fails. Named deviations: `docs/PROXY_HARNESS.md` for `CONSUMING.md` (at its cap), `semver` for `VERSION`, W rows for `BACKLOG.md` (now gone). Scope otherwise holds.
- **CI at 92c5414, run 42228125507, finished before this round was pushed:** `gates (ubuntu-latest)`, `gates (windows-latest)` and `proxy` success; `harness-windows` skipped; `policy` skipped (draft).
  - **Where the code ran:** the C++ runs only in `proxy` (ubuntu-24.04): the mingw DLL, host tests with `test_display_guard` 328 passed 0 failed and the source lints, `repro`, and the wine smoke, whose log has no `headless` line. `gates (windows-latest)` runs the Python gates and compiles no C++. So the hook and pump compile in CI but run on Windows only in the PC proofs, as the brief expected.
  - **`harness-windows` skipped, correctly:** no file in the branch's diff from its merge base matches `[ci.inputs] harness`.
- **Latest origin/main (dd98dce, fetched before this verdict):** the branch is 2 commits behind, both W132 paperwork (`jobs/W132/brief.md`, its row). It merges cleanly, and the ruleset is not strict, so being behind would not have blocked a merge.
- **Local:** `wsc policy` refused only for the missing review and row, as expected before a verdict. `wsc gates --fast` with this round in place: 14 ok, 0 failed, 1 warn (the worktree's absolute `core.hooksPath`). A local full `wsc gates` was stopped unfinished after more than 10 minutes on a busy PC: the full set is the CI result above, on the same head.

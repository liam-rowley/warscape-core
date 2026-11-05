## Round 1 (2026-11-05, branch job/W34 at 994178b)
**Verdict: merge.**

No blocker and no should-fix. Five later items, filed as B88 to B92 on `plan/W34-review-later`. This round changes nothing outside the job folder and the row.

**One decision for Liam, not a defect:** the ctl folder's ACE names the game's user SID, not `OW` as decision 15 said. The report names it and I agree with it (below), but it replaces a stated decision, and C36 records the new form.

### Machines
- `wsc gates` (full, 2026-11-05, this worktree at 994178b): 15 ok, 1 warn, 0 failed; 984 host tests, 5 skipped (the POSIX hook test, four capstone tests).
- `wsc policy --branch job/W34 --base origin/main`: before this round it refused only for the missing review and the row. `wsc jobs review`: all 9 checks on 994178b passed or were skipped.
- `proxy` and `harness-windows` were **skipped** on the head (run 41936694118), because 2ec5d15..994178b changes only the report and the row (checked with `git diff --stat`). Their real run is 41934314012, job 126938865987, at 2ec5d15: `host tests passed (16 core, 1 game)` and `passed (12 launches under wine, 3 dumps; ...)` for both null games.
- The branch's merge base is `origin/main` at 2390136, so nothing has moved under it.

### Claims against evidence
Repeated or opened independently, 2026-11-05:
- **Launch 12:** the report's log block matches CI's log line for line, on both null games: `3 sites: 3 ok, 0 bad, 1 to write`, `wrote null.smoke_patch at 00401183`, `protections restored on 1 page(s): 0x00001000=0x20`, `smoke: page 0x00001000 protect 0x20 before 0x20`, `patched code returned 2`, peeks `02 00 00 00` and `55 8b ec 83`.
- **`--exe` on a real exe, which the job never ran:** this branch's `gen_tables.py --adapter proxy/napoleon --exe` on a staged copy of Napoleon.exe, against napoleon-remastered's working copy: rc 0, `64 of 64 sites match`, no identity line. So the identity compare and the section rule hold on the real image and not only on the synthetic PE.
- **ACL on NTFS, for which the report has no artifact:** I repeated the calls on this PC with the trailing backslash `CtlThread` passes, which the report does not mention. Both `SetFileSecurityW` calls returned 1; `icacls` shows one ACE on the folder, `(OI)(CI)(F)` for the user; a new file inherits it and a rename works; a file made before the restrict keeps its old ACL, as the report says.
- **`LuaPathAllowed`:** the real header, compiled with g++ in the toolchain image, on napoleon's roots (`napoleon_remastered\lua\`, `C:\napoleon_remastered_pc\ctl`) and the Steam game folder: 43 cases of my own, 0 wrong. They include the `_scratch` path the report warns about (refused), `..`, `.. `, `...`, ADS, `\\.\`, `\\?\UNC`, `\\?\GLOBALROOT`, `\??\`, `C:x`, device names, a sibling `ctl2`, and the roots themselves.
- **The two red runs:** 41930770967 fails on `ctl/peek1.tmp: Permission denied`; 41934314012 fails on `2.0608623027801514 not greater than or equal to 2.5` in `test_job_sh`. Both are as the report says.
- **Hook row dropped:** `SiteAddress(` is called from `camera.cpp`, `console.cpp`, `orders.cpp` and `patch_driver.cpp`, and in `dev.cpp` only by `peek` (line 361). Kill criterion 3 applies.
- **Taken from the report, not repeated:** the three mutation checks (a no-op `Reprotect`, `OW` back, a field inserted mid-struct). Run 41930770967 independently shows the `OW` one. Also the napoleon `_scratch` search: the report says it read the working copy, so the pin-bump job re-checks `origin/main`.

### The brief
Decisions A to F are present, and each deviation is named with a reason. I checked these three:
- **`OW` replaced by the user's SID.** The kill criterion covers a failure on plain NTFS or a weakening to "everyone"; this is neither, since it is still one protected ACE and advapi32 only. `OW` has a real Windows failure as well as the wine one: a non-elevated game is not the owner of a folder an elevated process made. An elevated driver keeps access, because the user SID is the same.
- **All three rows in the stand-in.** This is forced: `MakePatchPlan` is all-or-nothing and `patch_engine.h` is out of scope.
- **Null adapters stay positional.** This is the brief's own branch below C++20, though see Later 4.

B80 not built is right: napoleon's `gfx.*` keys carry job owners. The moved `pc_deploy` paragraph is in `docs/UPGRADING.md` whole. No new DLL import.

### Risk-first reading
I picked what can lose the channel, run the wrong file or corrupt state on the PC, and read it in depth: `LuaPathNormal`/`LuaPathAllowed`, `CtlRestrictFolder`, `CtlRotate` and the id rules in `HandleRequest`, the `WndProc` route, and `file_section`/`site_line` (a false `MATCH` is the costly failure). I skimmed the rest.
- `file_section` is `pe.h` `FileBackedSize`/`SectionOfRva` line for line; the anchor and stock layout is `patch_engine.h`'s (`valueRva = rva + anchorLen`).
- `CtlRotate` runs on the ctl thread between requests, so it cannot race `_ids.txt` or a running request. `HandleRequest` still refuses an id with a `.done`, so what `PROXY_CTL.md` says about reuse is true.
- The early return in `WndProc` drops `GestureMessage`'s result. That is safe: only its probe message is swallowed, and keys always pass. `WM_CHAR` and plain keys are untouched.
- F10 arrives as `WM_SYSKEYDOWN`, so RmlUi no longer sees it. That follows the brief's per-message rule; nothing in the core binds it.

Not provable here, as the brief says: Alt+F4 in a real window. Napoleon's pin-bump job records it.

### Findings
No blocker, no should-fix.

**Later** (B88 to B92 on `plan/W34-review-later`):
1. **No CI run installs a hook yet.** C5's hook half stays open (`proxy/tests/null_game/registries/engine_sites.jsonl`: the plan checks `null.dummy_hook`, nothing detours it). The brief's open question 5 expects a follow-up row and none existed. B88.
2. **The flaky test went red on this branch.** `tests/test_job_sh.py` `test_lock_wait_takes_a_lock_released_meanwhile_and_times_out_with_124`; `harness/job.sh:204` sets its deadline from whole seconds, so `--wait 3` can end after about 2.06 s. See run 41934314012. B89.
3. **`--exe` can say `MATCH` where the DLL refuses.** `proxy/tools/gen_tables.py` `site_line` does not read `.reloc`, so a patch value over a relocated dword reads `MATCH` and fails as `RELOCATED VALUE` on the PC. Documented in `docs/UPGRADING.md`, but it could be a check. B90.
4. **The core's own text disagrees on designated initialisers.** `proxy/tests/null_game/proxy/null/adapter.cpp:27` says "the designated form is C++20"; `docs/CONSUMING.md:296` says it compiles under the DLL's `-std=c++17`, and napoleon's `adapter.cpp:60` already does it for `DevAdapter`. The `static_assert` message tells people to use a form the core's adapters do not show. B91.
5. **Two smoke gaps.** The every-500 rotation (`proxy/src/dev.cpp:576`) is a source lint, never run, as the report says. And `--docker smoke` now runs non-root but `proxy/tools/build.sh:407` still copies into `$OUT`: fine on the PC's bind mount, and by reading it would fail on a Linux host where `--docker all` left `$OUT` root-owned (not run). B92.

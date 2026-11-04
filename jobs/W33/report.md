# W33 report: Patch engine page protections and dev threads off DllMain

The patch writer now makes each code page writable once, keeps that page's own old protection, restores it once and reads it back. Before, a page with two sites (and a site's second page) was left RWX: audit C3, shown red at run time on a mock that behaves like VirtualProtect. No proxy thread starts in DllMain any more. `StartThread` refuses while `Rt().inDllMain` is set. The dev threads start at the first `Direct3DCreate9`, and only for the keys that need them (`DevThreadsFor`). A new release key, `proxy.file_rules`, lets a release ship its data rules with every `dev.*` key off (audit C4 and G2's root). Decision C28, version 0.33.0. Host tests, both DLL builds and the 10-launch wine smoke pass in the pinned image.

## What was built
### Page protections (decisions 1-6)
- `patch_engine.h`:
  - `WritePages(pl, sites, pageSize)` gives the sorted, unique RVAs of the pages that written value bytes touch.
  - `WritePlanAtomic` works page by page. It calls `Unprotect` once per page in ascending order and records that page's own old protection. If one call fails, it restores the pages already changed, each with its own value, and writes nothing. Otherwise it writes, calls `Reprotect` once per page, `Flush` per written site and `Query` per page.
  - `MemOps` gains `PageSize()` (default 0x1000) and `Query()` (default unknown). A page size that is not a power of two is refused before any call.
  - `WriteResult` gains `failedPage` and `pages` (`{rva, recorded, after, known}`). `failedSite` is now the first written site with a byte on the failed page. `reprotectFailures` counts pages.
  - The pure `ProtectionRestored(recorded, after)` accepts an equal value and the two copy-on-write pairs (0x08 to 0x04, 0x80 to 0x40).
- `patch_driver.cpp`'s `WinMem`:
  - `PageSize` = `GetSystemInfo().dwPageSize`; `Query` = `VirtualQuery().Protect`.
  - The refusal line names the page and the site.
  - The warning now counts pages: `%d page(s) left writable`.
  - New lines: `patch_engine: protections restored on <n> page(s): 0x...=0x.. ...` (or `(no readback)`), and one `... reads 0x.. after the restore, recorded 0x..: left changed` LOGW per bad page.
- `tk::PageMem` (testkit.h) replaces both FakeMems. It keeps one protection per page from the section characteristics. Unprotect follows VirtualProtect's first-page semantics. It can fail a chosen call, and it can leave a page changed for the readback test. It provides `Restored()` and `NoneTwice()`.
- `MakePatchPlan`, `ApplyPlanToBuffer`, the site checks and the value rows are unchanged. The written bytes still equal `ApplyPlanToBuffer`'s, and every test checks this.

### No thread in DllMain (decisions 7-10)
- `StartThread(fn, name)`:
  - It is declared in `runtime.h` and defined in `dllmain.cpp`.
  - It refuses with one LOGE while `Rt().inDllMain` is set. `DllMain` sets that flag around PROCESS_ATTACH (`wsp::Init`) and PROCESS_DETACH.
  - Otherwise it calls `CreateThread(..., CREATE_SUSPENDED)`, logs `thread: <name> started (tid N)`, then calls `ResumeThread` and `CloseHandle`.
- `DevThreadsFor(stateJson, timeline, ctl, autostart)` (devcore.h): state = `state_json || timeline`, ctl = `ctl || autostart`.
- `DevInit` decides which threads start, and the `dev:` line adds `threads at the first Direct3DCreate9: state=<0|1> ctl=<0|1>`.
  - The `s_ctlWake` event, the key reads, `FilesInit` and the `*Init` calls stay in DllMain.
  - The dev-side body moved into a `static DevSideInit` so that the release key can share DevInit's gate.
- `DevOnDirect3DCreate`:
  - It starts `dev.state` and `dev.ctl` after the installs and the CreateDevice hook, on the first call only (`InterlockedCompareExchange`).
  - It now runs `FilesOnDirect3DCreate()` before `if (!s_active) return;`.
- The dev.cpp header comment is corrected: the autostart is on the ctl thread, and no thread starts in DllMain.

### `proxy.file_rules` (decisions 11-14)
- It is read in `DevInit`. The early return is now `if (!k.Any() && releaseRules.empty()) return;`. The plan gate is the same. In pass-through, one warning names the key.
- No dev adapter is needed. With only this key set, `s_active` stays false: there is no timeline, no thread and no frame hook. Only `FilesInit` runs, and only if the file gave rules.
- The rules come after the dev rules, with origin `proxy.file_rules line N`. The log line is `redirect: <n> rules from <path> (proxy.file_rules)`.
- `DevKeys::Any()` does not see the key.
- The row (the brief's text) is in both null games' `config_keys.jsonl`. Their `tables.h` and `nullgame.ini` were regenerated.
- `test_config` lists the key, and names the fix if the row is missing. `test_guard` scans `dev.cpp` for `proxy.*` keys.

### Lints (test_dev.cpp)
- `inDllMain = true` comes before `wsp::Init(inst)`, and `= false` after it.
- `StartThread` reads the flag before `CreateThread(`.
- `CreateThread(` appears once in dllmain.cpp, twice in headless.cpp and nowhere else in `proxy/src`. A new one fails with "start threads through StartThread (it refuses inside DllMain)".
- DevInit (with DevSideInit) has no `StartThread(` and no `CreateThread(`.
- In `DevOnDirect3DCreate`, `OrdersInstall();` comes before the once flag, and the once flag before both starts.
- `FilesOnDirect3DCreate();` comes before `if (!s_active) return;`.
- `Any()` does not mention the release key.
- The early-return lint now checks the new condition.

### Docs, decision, backlog (decisions 15-19)
- `DECISIONS.md`: C28. The brief said C24, but C24 to C27 are taken on `main`.
- `PROXY_SITES.md`: the write-time sentences, rewritten.
- `PROXY_CTL.md`: the ctl thread's start point, and why a request written before it is not stale.
- `CONSUMING.md`: "DLL changes in 0.33.0 (W33, C28)", at 29.9 KB, under the cap.
- `BACKLOG.md`: B66 removed (built since 0.5.0).

## Tests, red then green
All of these ran in the pinned ubuntu image (`toolchain.py image`) with the pinned mingw-w64 packages, g++ and wine, in a local Docker container, on 2026-11-04.
- **Red at run time** (commit 1df13fc): PageMem was added to both tests against today's writer, and both tests failed:
  - `test_patch_engine` (211 passed, 10 failed):
    - B41 (two sites on page 0x1000): `page 0x01000 is 0x40, was 0x20`, made writable 2 times.
    - The straddle: `page 0x02000 is 0x40` and `page 0x03000 is 0x40`, with 0x02000 made writable 2 times.
  - `test_patch_value` (188 passed, 8 failed): page 0x01000 left 0x40, made writable 4 times.

  The full output is in the commit message.
- **Red at compile time** (commit eeda2eb): tests for `WritePages`, `ProtectionRestored`, `pages`, `failedPage`, `PageSize` and `Query`, none of which the old writer had. It was committed without compiling, as its red is by construction (it names absent members).
- **Green** (69651b0, 34ed5da, dfffd11 and the final state):
  - `build.sh all`: the DLL builds. Its imports are still advapi32, dbghelp, kernel32, msvcrt and user32.
  - Every host test passes: test_patch_engine 370, test_patch_value 196, test_dev 360, test_config 130, test_guard 93, and the others unchanged.
  - `python3 wsc.py gates` (full): 13 ok, 2 warnings (the existing `ci_render` note, skipped tests), 0 failed.
- **Smoke** (`build.sh smoke`): `passed (10 launches under wine, 2 dumps)`.
  - **Launch 8** adds `state_json=1`. In line-number order: `Direct3DCreate9(sdk=32)`, then `thread: dev.state started`, then `thread: dev.ctl started`, then `ctl: watching`. The `dev:` line has `state=1 ctl=1`.
  - **Launch 9** sets only `[proxy] file_rules=rules.txt`. The log has `redirect: 1 rules from ... (proxy.file_rules)` and `(proxy.file_rules line 1)`, no `dev: timeline=` line, no `thread:` line, and `process detach`.
  - **The `open` mode** ran in launch 9. Wine routes the exe's own import table through the hook, and the host printed `smoke: open data\smoke_in.txt: redirected by proxy.file_rules`, so the redirect is proved end to end.
  - **Launch 10** (`[dev] skip_intro=1 file_rules=rules.txt`): `state=0 ctl=0`, no `thread:` line, and `process detach (FreeLibrary)`.
- The no-gesture null game (`WSP_GAME_ROOT=proxy/tests/null_game_no_gesture`): `build.sh dll` and `build.sh smoke` pass, `passed (10 launches under wine, 2 dumps)`.
- CI's `proxy` job on the pushed branch: see the pull request checks.

## Version
0.33.0, a minor bump. When this was pushed, `origin/main` was at 0.30.1 (W38, merged into this branch). The open branches had already taken versions: W15 0.31.0 with C28, and W25 0.32.0 with C29. `wsc policy` wants the next decision number on `main`, so this branch uses C28, the same number W15 uses. Whichever of them merges second merges `main` and takes the next number, for the decision row and for `VERSION`. Never rebase. Tags are Liam's.

## Deviations from the brief and why
- **Decision number C28, not C24.** C24 to C27 are on `main`. `wsc policy` asks for the next number on `main`, so W15's C28 collides with this one, and the second to merge renumbers.
- **`StartThread` creates the thread suspended**, logs, then resumes. The brief's sequence was `CreateThread`, `CloseHandle`, then `LOGI`. That order lets the new ctl thread log `ctl: watching` before the creator logs `thread: dev.ctl started`, which would make step 6's line-order check race. `ResumeThread` is the only added call. It never runs in DllMain, because the starter refuses there.
- **`DevSideInit`**: DevInit's dev-only body moved into a static function in the same file, so that the release key shares DevInit's gate without a second copy of it. The gate lint still finds the plan gate before `s_active = true;`.
- **`FilesInit` with only the release key** runs only when the rule file gave rules. A missing or empty file installs no hooks and logs the warning.
- **`GetSystemInfo` under the loader lock.** The kill criterion lists VirtualProtect, VirtualQuery and FlushInstructionCache as the only calls. Decision 2 itself prescribes `GetSystemInfo` for the page size. It is a plain kernel32 query, takes no lock and loads nothing, and the driver's header comment now names it.
- **The row is in `null_game_no_gesture` too**, not just `null_game`. CI builds and smokes that game's DLL, which now reads the key. It gets the same row and regenerated files.
- **Step 3's compile-time red was not compiled.** It was committed as-is, because it references members the old header lacks.

## Open questions
- **The consumer's PC run (napoleon J78)** is the only check of the real pages and of `init_heap_corruption`. The four checks are under "What napoleon must do (J78)" below. Brief open question 4's residual stands: if start-up deaths remain after `Direct3DCreate9` in dev launches only, a later row moves the start to the first Present.
- **W34's stand-in exe with a patch site** is the place to see the `protections restored` line in CI. This job's smoke cannot see it, because the stand-in refuses every site.
- **A behaviour change in dev configs:** with ctl on and timeline and state_json both off, `scene:` lines come when something asks, not on a 500 ms clock. The harness profiles set both keys.

## What napoleon must do (J78)
From the brief, unchanged:
- **Key row:** add the `proxy.file_rules` row (decision 14) to `registries/config_keys` and run `gen_tables.py`. No `adapter.cpp` change.
- **Release:**
  - The `ui_scale_2x` component's `ini_set` becomes `{"proxy.file_rules": "napoleon_remastered\\ui\\ui_scale_2x.rules"}`.
  - Delete the `allowed_dev_keys` entry for `dev.file_rules` and the "until a DLL job gives it a player key" sentences.
  - Add a D line that supersedes D46's exception.
- **Other places:** move the same switch in `upscale/pc/play.py`, its tests and the READMEs. The harness's own `dev.file_rules` stays.
- **The build id changes:** rule 79 needs 20 passes on the new id, in one run with W24's changes.
- **Record with the run id:**
  1. `protections restored on <n> page(s)` and no `left changed` line.
  2. `thread: dev.state` and `thread: dev.ctl` after `Direct3DCreate9(`.
  3. A release-ini launch with no `dev:` line and no `thread:` line, with `redirect: 1 rules from ... (proxy.file_rules)` and the 2x UI.
  4. The count of start-up deaths before the first `Direct3DCreate9`, against run 20261103_j30acc2. Update the fact either way.

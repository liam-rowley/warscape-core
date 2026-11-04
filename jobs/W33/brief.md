# W33: Patch engine page protections and dev threads off DllMain

Model: Opus, reason: DLL work. It changes how the proxy writes and re-protects the game's code pages under the loader lock, where threads start in the game process,
and which keys a shipped DLL reads; a mistake shows only in the consumer's 20-pass acceptance run (napoleon rule 79), not in CI. Budget about 140 tool calls (the
optional smoke `open` mode in step 6 has its own cap of about 15). At the cap, stop, commit, push and report what is left.

## Goal
Audit 2026-11-03 (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`, read-only) findings C3 and C4, and the root cause of G2:
- **C3, RWX pages.** `WritePlanAtomic` records one old protection per site and restores in forward order (`proxy/src/patch_engine.h:182-186`). The second site on a
  page records the RWX the first one set, so the page ends RWX. The audit counts six such page groups in the consumer's table, two with sites on in release. The mock
  (`proxy/tests/test_patch_engine.cpp:36-41`) answers `old = 0x20` for every call and models no pages, so the bug passes. The B41 case already puts two written
  sites on page 0x1000 (0x1103 and 0x1206, `test_patch_engine.cpp:146-174`) and stays green.
- **C4, threads from DllMain.** `DevInit` runs inside `DllMain` (`dllmain.cpp:105`, called from `:118`) and starts `StateThread` and `CtlThread`
  (`dev.cpp:668`, `:673`). Empire hit this trap first: it starts single-threaded with a `HEAP_NO_SERIALIZE` process heap until its scheduler starts
  (empire-remastered `docs/learnings/LEARNINGS_ENGINE.md:473` at `b67a4f4`). Napoleon's player ini sets `dev.file_rules` (its D46 exception). That makes
  `DevKeys::Any()` true (`dev.h:18`), so the shipped DLL starts `StateThread` from DllMain. Napoleon's fact `napoleon.proxy.init_heap_corruption` is open: a
  0xc0000374 about 150 ms after start, before the first d3d9 call (J44, J45, J50, J30). The causal link is unverified. This job does not claim to fix that
  fact; it removes the suspect, and napoleon J78 re-checks the fact.
- **G2's root.** A release can ship the UI-scale rule file only through a `dev.*` key. The fix is a player key outside `dev.*`, so a release ships with every
  dev key off.

## What exists (read before building)
- `docs/PROXY_SITES.md` (patch engine contract), `docs/PROXY_CTL.md` (control channel), `docs/CONSUMING.md`, `docs/DECISIONS.md`, `jobs/W17/report.md` (the
  stale-request rule and `peek` in `dev.cpp`), `jobs/W19/report.md` (capture; no `dev.cpp` change), `jobs/W24/report.md` once W24 merges. W24 changes the build
  id and `dllmain.cpp`'s init (a DLL self-hash line) just before this job.
- **Patch writer:** `proxy/src/patch_engine.h` has `MemOps` (151-156), `WriteResult` (157-162) and `WritePlanAtomic` (166-189). Its failure path (173-178)
  already restores in reverse. `proxy/src/patch_driver.cpp:60-84` holds `WinMem` (VirtualProtect to RWX and back, FlushInstructionCache) and the log lines.
  There are two mocks: `test_patch_engine.cpp:36-41` and `test_patch_value.cpp:24-28`. The fixture image is `tk::GameLike()` (`proxy/tests/testkit.h:127`):
  `.text` 0x1000-0x3fff (exec+read), `.rdata`, `.data` 0x5000 (read+write), 4 KiB pages, mapped so that offset = RVA.
- **Dev side:** `proxy/src/dev.cpp`:
  - `DevInit` (614-675): the key reads, then `if (!k.Any()) return;` (633), then the plan gate (634). It gathers the file rules (652-664), calls `FilesInit`
    (665) and starts both threads (668, 669-674).
  - `CtlThread` (491-525) does heap work at once (`_ids.txt` into a `std::set`, a log line) and runs the config autostart (499-509; the header comment at
    6-7 wrongly gives it to the state thread). `StateThread` (527-535) sleeps 500 ms, then `UpdateSceneLocked` and, with `dev.state_json`, `state.json`.
  - `SceneNow` (87) computes the scene on demand. `DevOnDirect3DCreate` (677-685) returns at `if (!s_active)` before `FilesOnDirect3DCreate`.
  - `DevKeys`: `proxy/src/dev.h:13-19`. Pump freshness: `devcore.h` `SceneTracker` (`kPumpFresh`, 106-166).
- **Start-up order:** `proxy/src/dllmain.cpp`. The `DllMain` that runs `Init` is at 115-126. The `Direct3DCreate9` export is `proxy/src/backend.cpp:126-135`:
  it calls the headless side, `DevOnDirect3DCreate` and the UI host, with the object the backend returned, null included. `Direct3DCreate9Ex` (137-145)
  calls only the headless side.
- **How headless already avoids DllMain threads:** `proxy/src/headless.cpp:5-11`. `HeadlessInit` installs only IAT hooks. `Ensure` (391-407) starts the
  guard thread through a once flag (`StartGuardThread`, 371-376). `Ensure` is reached from `HeadlessOnDirect3DCreate` (716-718) or the first game window
  (`hk_CreateWindowExW`, 410-412). These are the only other `CreateThread` calls in `proxy/src`.
- **File rules:** `proxy/src/filerules.h:1-14` (the grammar; the first matching rule wins, `MatchRule` 104-111). `proxy/src/files.cpp`: `FilesInit`
  (392-413), `InstallHooks` (358-389) and `FilesOnDirect3DCreate` (421-425, the deferred IAT pass). `files.cpp` reaches the dev side only through
  `TlMark`, `DevReport` and `DevFrontendMovie`, which all return while `s_active` is false.
- **Keys and lints:**
  - `proxy/tests/test_dev.cpp:276-283` lints that DevInit returns before the plan gate. Lines 298-317 lint that every `dev.*` key `dev.cpp` reads is
    registered and the reverse.
  - `test_config.cpp:77-79` lists the keys the core reads by name. `test_guard.cpp:104-121` scans five driver files for `"proxy.*"` keys.
  - The null game's keys are `proxy/tests/null_game/registries/config_keys.jsonl` (`dev.file_rules` at line 10). Its generated files are
    `proxy/tests/null_game/proxy/null/generated/tables.h` and `nullgame.ini`; regenerate them with
    `WSP_GAME_ROOT=proxy/tests/null_game python3 proxy/tools/gen_tables.py`.
- **Smoke:** `proxy/tools/build.sh` smoke (185-243), 8 launches; only launch 8 (228-242, `dev.ctl`) has a dev key and waits for `ctl: watching`. The
  stand-in `proxy/tests/smoke_host.cpp` calls `LoadLibrary`, `D3DPERF_*`, `Direct3DCreate9` (null under wine), then `wait <file>` or `FreeLibrary`.

## Evidence from the first consumer (read-only; it stays out of core files)
- napoleon `docs/DECISIONS.md:53` (D46): the player ini omits the dev keys, except `dev.file_rules` for the UI-scale stop-gap, "until a DLL job gives it a
  player key".
- `release/napoleon/components.json:27`: the component sets `"ini_set": {"dev.file_rules": "napoleon_remastered\\ui\\ui_scale_2x.rules"}`. Its rule text is
  one `redirect` line.
- `release/napoleon/release.json:19`, `"_note"`.
- napoleon `jobs/J74/brief.md:50,66`: `allowed_dev_keys` lists `dev.file_rules` until W33, then J78 deletes the entry.
- `registries/engine_facts/napoleon.proxy.init_heap_corruption.json`: open, 2026-10-31. A launch can die about 150 ms after start with a first-chance
  0xc0000374 "right after the proxy init and before the first d3d9 call". It appeared in J44, J45, J50 and J30. In run 20261103_j30acc2, 10 start-up exits
  were retried in passes 1-16. Harness launches set `dev.ctl` and `dev.state_json` (`harness/napoleon/adapter.json:42`), so the ctl thread runs proxy heap
  code from the first moment. The state thread is asleep for its first 500 ms.

## Decisions already made (follow them; a deviation goes in the report with its reason)
### A. Page protections (C3)
1. **Once per page, not reverse order.** A pure helper `WritePages(pl, sites, pageSize)` returns the sorted, de-duplicated RVAs of every page that a
   written site's value bytes touch: from the page of `valueRva` to the page of `valueRva + len - 1`. `WritePlanAtomic` then works page by page:
   - It calls `Unprotect(base + page, pageSize, old)` once per page, in ascending order, and keeps that page's own old protection.
   - If one call fails, it restores the pages already changed, each with its own recorded value, and writes nothing.
   - Otherwise it writes every site's bytes, calls `Reprotect` once per page with that page's recorded value, then `Flush` per written site range, as today.

   **Why not reverse order:** VirtualProtect reports the old protection of the first page in the range only. So a per-site record is wrong in two ways: for
   the second site on a page, and for a site's second page. Reverse order fixes only the first. Example: site A lies on P1 and site B spans P1-P2. A records
   P1 = RX. B records P1's current RWX and makes P2 RWX. In reverse, B restores P1 and P2 to RWX, then A restores P1 to RX, and P2 stays RWX. A per-page
   record has no order to get wrong, and the failure path is the same loop. What is made writable does not change: VirtualProtect already rounds a range out
   to whole pages. Only what is recorded and restored changes.
2. **Page size from `MemOps`.** `virtual uint32_t PageSize() const { return 0x1000; }`. `WinMem` returns `GetSystemInfo` `dwPageSize`. A size that is not a
   power of two refuses the write: `ok = false`, no call, nothing written.
3. **`WriteResult` changes:**
   - `failedSite` becomes the first written site, in plan order, with a byte on the failed page. A new `failedPage` holds that page's RVA (-1 if none).
   - `reprotectFailures` counts pages.
   - New: `pages`, a list of `{rva, recorded, after, known}`.
   - `written` keeps its meaning: 0 or `pl.nWrite`.
   - The driver's write-time refusal names the site and the page. Its "left writable" warning counts pages.
4. **A readback after the restore.** `virtual bool Query(uint8_t* page, uint32_t& prot) { return false; }` (false means unknown). `WinMem` implements it with
   VirtualQuery, which is safe under the loader lock (patch_driver.cpp:4).
   - A pure `ProtectionRestored(recorded, after)` decides each page. It is true when the two are equal. It is also true when `recorded` is a copy-on-write
     form and `after` is its written form: 0x08 to 0x04, or 0x80 to 0x40. An image page that was written is private and reads back that way.
   - The driver logs one line, `patch_engine: protections restored on <n> page(s): <rva>=<prot> ...`. That line becomes `(no readback)` when Query is
     unknown.
   - Each page that fails the check gets a LOGW: `patch_engine: page <addr> (RVA 0x..) reads 0x.. after the restore, recorded 0x..: left changed`.
   - The readback never refuses and never undoes anything, because the bytes are already written.
   - **Why:** each VirtualProtect call returned TRUE in C3, yet the end state was wrong. Only a readback shows the end state, and it is the only way the
     consumer's PC run and W34's stand-in exe can see C3 fixed.
5. **The mock gets page semantics.** `tk::PageMem` in `proxy/tests/testkit.h` replaces both FakeMems, and both tests use it.
   - It holds one protection per page of the mapped test image, taken from the section characteristics: headers 0x02, exec+read 0x20, exec+read+write
     0x40, read+write 0x04, read 0x02.
   - `Unprotect` has VirtualProtect's semantics: `old` is the protection of the first page of the range, and every page of the range becomes 0x40.
   - `Reprotect` sets every page of the range. `Query` returns the page's protection.
   - It can fail on a chosen `Unprotect` or `Reprotect` call. It counts calls per page and flushes.
   - **The invariant every test checks:** after any `WritePlanAtomic`, every page equals its initial protection and no page was unprotected twice.
6. Nothing else in the patch engine changes: not `MakePatchPlan`, not `ApplyPlanToBuffer`, not the site checks, not the value rows.

### B. No thread starts in DllMain (C4)
7. **One starter that refuses inside DllMain.** `bool StartThread(LPTHREAD_START_ROUTINE fn, const char* name)` is declared in `runtime.h` and defined in
   `dllmain.cpp` beside `Rt()`.
   - It refuses while `Rt().inDllMain` is true, with one LOGE naming the thread. `DllMain` sets that flag around its work for PROCESS_ATTACH and
     PROCESS_DETACH.
   - Otherwise it calls `CreateThread`, `CloseHandle` and `LOGI("thread: %s started (tid %lu)")`. It returns false with a LOGE when `CreateThread` fails.
   - `dev.cpp` starts both its threads through it.
   - A source lint: `CreateThread(` appears in `proxy/src` only in `StartThread` and in `headless.cpp`'s two existing starts, which already run off DllMain
     through `Ensure`. A new raw `CreateThread` fails with "start threads through StartThread (it refuses inside DllMain)".
   - `headless.cpp` is not changed (B19, B22, B23, B65 wait for a job that changes its logic). **Why:** "a learning becomes code first" (CLAUDE.md).
8. **Where they start: the first `Direct3DCreate9`.** At the end of `DevOnDirect3DCreate`, on its first call only. The game recreates its d3d9 object on a
   resolution change, so use an `InterlockedCompareExchange` once flag.
   - The threads start after the file pass, the `d3d_create` mark, the console, camera and orders installs and the CreateDevice hook. A ctl verb therefore
     never meets a half-installed feature.
   - They start whatever object the backend returned, null included, as today.
   - **Why:** the export is the game's own call from its running code, so it is never under the loader lock. It comes before every device, every Present and
     every frame a ctl verb waits for. Headless starts its guard at the same point. The wine smoke reaches it.
   - **Not the first Present:** that needs a device, which the smoke has none of, and a game that hangs before its first frame would have no ctl channel.
   - **Not `Direct3DCreate9Ex`:** the dev side is not wired to that export at all (backend.cpp:137-145). That is out of scope.
9. **Only when a dev feature needs a thread.** A pure `DevThreadsFor(stateJson, timeline, ctl, autostart)` in `devcore.h`, host-tested on all 16
   combinations:
   - **State thread** if and only if `dev.state_json` or `dev.timeline` is on. These are the two outputs it clocks: state.json twice a second, and the
     timeline's `loading_started` and `scene_ready` marks. A scene leaves a context only when its pumps stop (`kPumpFresh`), so only a clocked
     `UpdateSceneLocked` sees that.
   - **Ctl thread** if and only if `dev.ctl` is on or `dev.autostart` is set, as today. The autostart runs on it.
   - **Every other dev key starts no thread:**
     - `skip_intro`, `log_files`, `lua_bridge` and `file_rules` are hooks only.
     - `console`, `camera`, `orders`, `perf` and `capture` are reached through ctl, and their scene reads call `SceneNow`.
   - DevInit's `dev:` line adds `threads at the first Direct3DCreate9: state=<0|1> ctl=<0|1>`.
   - One behaviour change in dev configs: with ctl on and timeline and state_json off, `scene:` log lines appear when something asks rather than on a
     500 ms clock. The harness profiles set both keys, so nothing they read changes.
10. **Everything else stays in DllMain:** the key reads, `InitializeCriticalSection`, the timeline's process start, the `*Init` calls, `FilesInit`, and the
    `s_ctlWake` event (a kernel object, not a thread). Fix the header comment at dev.cpp:6-7, and say there that no thread starts in DllMain.

### C. The release file-rules key (C4, G2's root)
11. **`proxy.file_rules`** is a rule file in the `filerules.h` grammar, with all five verbs, relative to the game folder or absolute. It is read once in
    DllMain, like `dev.file_rules`.
    - It is not a dev key: `DevKeys::Any()` does not see it. A config with only this key, and every `dev.*` key off, leaves the dev side off: no `s_active`,
      no timeline, no thread, no frame hook. Only `FilesInit` runs, with these rules.
    - **Why `proxy.`:** that section holds the switches a release sets, and a game's player ini lists it while it omits `dev.*`.
12. **Order:** the dev rules come first (`skip_intro`'s movies, the adapter's Lua rules, `dev.file_rules`), then `proxy.file_rules`. The first match wins, so a
    dev rule overrides a shipped rule for the same path in a dev launch. Each rule's `origin` names its source (`proxy.file_rules line N`). The log line is
    `redirect: <n> rules from <path> (proxy.file_rules)`.
13. **Conditions:**
    - The same plan gate as the dev side applies (`engineHooks && d3dHooks`). In pass-through there are no rules, and one warning names the key.
    - No dev adapter is needed: `Adapter().dev` may be null.
    - `DevOnDirect3DCreate` calls `FilesOnDirect3DCreate` before its `if (!s_active) return;`, so the deferred IAT slots also go in without the dev side.
    - The early return in DevInit becomes "no dev key and no `proxy.file_rules`". Update the test_dev.cpp:283 lint with it.
14. **Registry row** (every game's `config_keys`, and the null game's):
    `{"id": "proxy.file_rules", "description": "release file rules (W33): a rule file, relative to the game folder or absolute, in the grammar of proxy/src/filerules.h (redirect, fail, add, movie-fail, movie-redirect), applied after the dev rules (a dev rule on the same path wins); turns no dev feature on and starts no thread; empty = none", "default": "", "release_value": "", "owner": "proxy"}`.
    - The core reads it by name. Add it to the list in `test_config.cpp:77-79`, and add `dev.cpp` to the file scan in `test_guard.cpp`. A game that bumps the
      pin without the row then fails its own host tests with the key named, instead of silently reading "".
    - The value belongs to the release component that ships the rule file (an `ini_set`), not to the row: `release_value` stays "".

### D. Docs, decision, backlog
15. **`docs/DECISIONS.md`:** one line at the next free C number (C24 when written), "proposed (Claude, core W33)". It covers three things: protections are
    restored once per page and read back; no proxy thread starts in DllMain (`StartThread` refuses), and the dev threads start at the first
    `Direct3DCreate9` only for the keys in decision 9; `proxy.file_rules` is the release file-rules key, and a release needs no dev key for shipped data
    rules.
16. **`docs/PROXY_SITES.md`:** rewrite the write-time sentences at lines 21-22 (once per page, the readback line).
17. **`docs/PROXY_CTL.md`:** the protocol paragraph adds two things. The ctl thread starts at the first `Direct3DCreate9`, never in DllMain. A request written
    between process start and then waits and is not stale: it was written after the process was created.
18. **`docs/CONSUMING.md`:** a section "DLL changes in <version> (W33, C24)" with the key row, the migration below and the new log lines. Keep the file under
    30 KB.
19. **`docs/BACKLOG.md`:** it is at 29.5 KB of 30. Remove B66: it is already built, because dev.cpp:331 deletes the console chunk on every path since
    `e7893fe` (0.5.0). Add no row without removing one.

## Scope: files this job touches
- **Patch engine:** `proxy/src/patch_engine.h`, `patch_driver.cpp`.
- **Threads and the key:** `runtime.h`, `dllmain.cpp` (the flag and `StartThread`; nothing else in `Init`), `dev.cpp`, `dev.h`, `devcore.h`.
- **Tests:** `proxy/tests/testkit.h`, `test_patch_engine.cpp`, `test_patch_value.cpp`, `test_dev.cpp`, `test_config.cpp`, `test_guard.cpp`.
- **Null game:** `proxy/tests/null_game/registries/config_keys.jsonl` and its regenerated `generated/tables.h` and `nullgame.ini`.
- **Smoke:** `proxy/tests/smoke_host.cpp` (the `open` mode only) and `proxy/tools/build.sh` (smoke only).
- **Docs and version:** the docs in D, `VERSION`.

No change to `headless.cpp`, `files.cpp`, `filerules.h`, `backend.cpp`, any `adapter.cpp` or `GameAdapter`. No game names in core files.

## Steps
1. Read "What exists". Check whether this session can build and run the host tests and the smoke (`proxy/tools/build.sh --docker all`, then `--docker smoke`).
   If it cannot, push early and read CI's `proxy` job.
2. **Red at run time first.** Commit `tk::PageMem` with today's `MemOps` interface (Unprotect, Reprotect, Flush), and switch both tests to it. Add two
   cases:
   - **Two sites, one page:** the B41 fixture, with page 0x1000 written twice.
   - **A straddling site:** one site whose value bytes cross a page boundary inside `.text`, plus one site on the first of those pages. Pick RVAs clear of
     `fn.tick` at 0x2000, for example near 0x2ffe.

   Assert the invariant from decision 5. These cases compile against today's writer and fail: page 0x1000 is left 0x40. Commit them red, with the failing
   output in the commit message.
3. **Red at compile time:**
   - `WritePages`: one page, two sites on one page, a straddle, sites in `.text` and `.data`.
   - `ProtectionRestored`: equal, the two copy-on-write pairs, a different value, a guard bit.
   - The `.data` page (0x04) and the `.text` page (0x20) each restored to their own value.
   - A failure at each page index: nothing written, every page initial, `failedSite` and `failedPage` right.
   - A restore failure, counted per page.
   - A refused plan: no call at all.
   - A non-power-of-two page size: refused.
   - The readback: a page the mock leaves changed is reported.
   - `DevThreadsFor`, on all 16 combinations.
4. **Build A** (decisions 1-6). Keep the existing equality checks: the bytes written equal `ApplyPlanToBuffer`'s (`test_patch_engine.cpp:190`,
   `test_patch_value.cpp:108-110`). Green.
5. **Build B** (7-10), then **C** (11-14). The null game gets the row; regenerate its files. Add the lints:
   - `DllMain` sets `inDllMain` before `wsp::Init` and clears it after.
   - `StartThread` checks the flag before `CreateThread(`.
   - The `CreateThread(` count from decision 7.
   - `DevInit`'s body has no `StartThread(` or `CreateThread(`.
   - `DevOnDirect3DCreate` calls the starter after `OrdersInstall();`.
   - `FilesOnDirect3DCreate();` comes before `if (!s_active) return;`.
   - `Any()` does not mention the release key.
6. **Smoke** (build.sh):
   - **Launch 8** adds `state_json=1`. Check that `thread: dev.state started` and `thread: dev.ctl started` both come after the `Direct3DCreate9(sdk=32)`
     line (compare `grep -n` line numbers), and that `ctl: watching` comes after `thread: dev.ctl`.
   - **New launch 9:** `[proxy] backend=system exe_guard=0 file_rules=rules.txt`, with a one-line `redirect data\smoke_in.txt -> <mod>\smoke_out.txt`.
     Check `redirect: 1 rules from`, `(proxy.file_rules)` and `process detach`. Check that the log has no `dev: timeline=` line and no `thread:` line.
   - **New launch 10:** `[dev] skip_intro=1 file_rules=rules.txt`. Check `state=0 ctl=0`, no `thread:` line, and `process detach` (FreeLibrary with no
     proxy thread inside the DLL).
   - **Optional, capped at about 15 calls:** an `open <path>` mode in `smoke_host.cpp` (CreateFileW through its own IAT, print the bytes). Launch 9 then
     checks that the redirect served `smoke_out.txt`'s text. If wine does not route it, drop the mode and say why.
   - The final line becomes "passed (10 launches under wine, 2 dumps)".
7. Docs, decision, backlog (D), and `VERSION`. Then `python3 wsc.py gates` (full), CI's `proxy` job green, and
   `python3 wsc.py policy --branch job/W33 --base origin/main`.

## Tests and acceptance: what each layer can prove
- **Host tests (CI, every push):**
  - The writer's page arithmetic and its end state on a mock with VirtualProtect's page semantics: two sites on one page, a straddle, mixed sections,
    failure and restore paths. The run-time red of step 2 against today's writer is the proof that C3 was real.
  - The thread rule and the key wiring, by `DevThreadsFor` and the lints.
  - Every existing proxy host test still passes on the null game's regenerated table.
- **Wine smoke (CI):**
  - The dev threads start only after the first `Direct3DCreate9`, and only for their keys (launches 8 and 10).
  - `proxy.file_rules` loads with the dev side off (launch 9; with the `open` mode, end to end).
  - The existing launches 1-8 still pass.
  - It cannot show a patch write: the stand-in exe refuses every site. W34 adds a stand-in with a patch site and checks this job's `protections restored`
    line.
- **Only the consumer's PC run** (napoleon J78's four checks, below): the real pages, the release config with no dev key, and `init_heap_corruption`.
- No new DLL import; the import list stays advapi32, dbghelp, kernel32, msvcrt and user32 (plus whatever W24 adds). Every written byte stays identical.

## VERSION
A minor bump (a new key, new log lines, new thread start times; DLL inputs). Take the next free minor against `origin/main` at merge time (0.24.0 when
written; W24, W20, W22, W23 and W30 may bump first): re-read it and the open `job/*` branches before the last commit; if one merges first, merge `main` (never
rebase) and take the next number. Say which. Tags are Liam's.

## What consumers must do after the tag (napoleon-remastered J78, the pin bump of audit train 1)
- **Build id:** the generated table, the ini and `proxy/src` change, so every consumer's build id changes. Rule 79 needs 20 consecutive passes on the new id,
  in one run with W24's changes.
- **Key row:** add the `proxy.file_rules` row (decision 14) to `registries/config_keys`, then run `python3 core/proxy/tools/gen_tables.py`.
  `proxy/napoleon/generated/tables.h` and `napoleon_remastered.ini` gain the key. No `adapter.cpp` change. Without the row, the host tests fail and name it.
- **Release:**
  - `release/napoleon/components.json`: the `ui_scale_2x` row's `ini_set` becomes `{"proxy.file_rules": "napoleon_remastered\\ui\\ui_scale_2x.rules"}`. The
    rules text is unchanged.
  - `release.json`: delete the `allowed_dev_keys` entry for `dev.file_rules` (J74) and the "until a DLL job gives it a player key" sentences in both
    `_note`s.
  - A D line that supersedes D46's exception: the player ini sets no dev key.
- **Same switch elsewhere:** `upscale/pc/play.py` `--scale 2`, `tests/test_play.py:169`, `tests/test_release.py:92-94`, `uiscale/README.md:16`,
  `upscale/README.md` and `proxy/README.md:149` move to `proxy.file_rules`. The harness's dev launch key `dev.file_rules` (the fixed-sky rules) stays: it is a
  dev rule, and it wins over a shipped rule on the same path.
- **J78's checks**, recorded with the run id:
  1. Every pass's `proxy.log` has `patch_engine: protections restored on <n> page(s)` and no `left changed` warning. That is C3 on the real pages.
  2. In the dev profile, the `thread: dev.state` and `thread: dev.ctl` lines come after `Direct3DCreate9(`.
  3. One launch with the release player ini has no `dev:` start line and no `thread:` line, has `redirect: 1 rules from ... (proxy.file_rules)` with the
     `uied.templates` redirect hit, and shows the 2x UI of fact `napoleon.ui.scale_2x_packs`.
  4. `init_heap_corruption`: count start-up deaths before the first `Direct3DCreate9` across the run (retries, 0xc0000374 dumps) against run
     20261103_j30acc2. After W33 no dev thread exists in that window. In a headless launch the guard thread can still start at the first game window
     (headless.cpp:410-412), so a reproduction rules out the dev threads but not the guard thread. Update the fact either way.

## Kill criteria
- The page-wise writer would write a byte `ApplyPlanToBuffer` does not, or would need any call but VirtualProtect, VirtualQuery and FlushInstructionCache
  under the loader lock: stop and report.
- A dev feature or a core driver turns out to need the state or ctl thread before the first `Direct3DCreate9`, for example something that waits for
  `state.json` or a ctl answer earlier: stop and report. Never put a thread start back into DllMain, and never add a timer or a second start point to work
  around it.
- Serving `proxy.file_rules` would need the dev side (`s_active`, the dev lock, the dev adapter or a thread): stop and report.
- Launch 8 does not reach `ctl: watching` under wine with the thread started at the first `Direct3DCreate9` after about 15 calls: stop and report what the
  log shows. Do not start the ctl thread anywhere else.
- The optional `open` mode over about 15 calls: drop it and keep launch 9's log checks.
- Core CI red after three fix attempts for a cause in this change: stop and report. For a version collision, follow VERSION; never rebase a pushed branch.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **The key's name.** `proxy.file_rules` (recommended), a new section (`files.rules`), or a UI-specific key. Recommended: `proxy.file_rules`. The core stays
   game-agnostic: the mechanism has no UI in it. It sits with the release switches, and the consumer's player ini lists it without a change to its omit list.
2. **The grammar of the release key.** All five verbs (recommended), or `redirect` and `add` only. Recommended: all five. It is one parser and one hook set,
   the release builder writes the file, and a narrower grammar would need a second code path plus a new job the first time a release wants a movie rule.
3. **The state thread's condition.** `state_json || timeline` (recommended), or any dev key except the file and movie keys, which keeps `scene:` log lines on a
   500 ms clock in a ctl-only config. Recommended: the former. It is the narrowest rule that keeps every clocked output, and the harness profiles set both
   keys.
4. **The start point.** The first `Direct3DCreate9` (recommended), or the first Present. Recommended: the first `Direct3DCreate9`. It is never under the loader
   lock, it comes before every ctl use, the smoke covers it, and it takes every dev thread out of the window in which the fact's crash happens.
   - Residual: if the game's heap is still unserialised at that point, as Empire's is until its scheduler starts, dev-config threads could still race the
     engine. The release has no thread after the migration.
   - If J78 sees start-up deaths after `Direct3DCreate9` in dev launches only, a later row moves the start to the first Present.

## Finish
Write the report in `jobs/W33/report.md`. Cover:
- what was built, per decision;
- the tests, red (step 2's run-time output) then green, and where they ran;
- the smoke launches, and whether the `open` mode ran;
- the version taken, deviations, open questions, and what napoleon must do.

Then run `wsc reg set jobs W33 status=review report=jobs/W33/report.md` (`python3 wsc.py`). Push `job/W33`, open the draft pull request, and stop: an
independent reviewer merges (C18), and Liam tags.

# W39 report: DXVK window-proc guard into the core (napoleon J16 port)

The core now carries napoleon J16's fix for the crash at every in-game resolution change under DXVK: `d3d9_dxvk.dll`'s own four `Get/SetWindowLong` import slots go through a guard, so a foreign window proc above DXVK's is dropped at a fullscreen re-entry and cannot form the cycle that overflowed the stack. It runs behind `proxy.dxvk_wndproc_fix` (on by default). All three re-entry paths from the A/B run are modelled, unguarded and guarded, and none needed a policy change. The real guard ran once against the real pinned DXVK under wine and patched 4 slots. **The fix itself is not proven: only napoleon's J16 fix arm on the PC can show that, after a tag and a pin bump.** Version 0.38.0.

## What was built, per decision
1. **Where each piece lands.** As the brief says: `proxy/src/wndprocpolicy.h` and `proxy/src/dxvk_wndproc.cpp` (code as at `95f5a1e`), the `runtime.h` line, the hook-up in `backend.cpp`, `proxy/tests/test_wndproc.cpp`, `proxy/tools/dump_read.py`.
2. **The `else if` bug.** Fixed. The unknown-backend warning stays on the `want` chain, and the guard keys on the loaded DLL (`s_real` and `s_name`). W33 did not touch `backend.cpp`. Its `StartThread` runs in `DevOnDirect3DCreate`, after `BackendEnsure`, so the guard inside `LoadOnce` comes first with no reordering.
3. **The key.** Read with `rt.cfg.Bool("proxy.dxvk_wndproc_fix")`. Off logs J16's warning and patches nothing. The row is in both null games, regenerated. `test_config` names the key, and `test_guard`'s key scan and game-name scan now cover the new files. `docs/CONSUMING.md` has the line.
4. **Host tests.** Items 1-7 are in `test_wndproc.cpp` (results below).
5. **The dump reader.** `--exe NAME`, default the dump's own main module, read from cdb's `|` line. Header and `tools` row added. `wsc find dump` found no reader on `main`, only dump writers (`wer_localdumps.ps1`, `harness/dump.ps1`).
6. **No new import or thread.** The build still imports `advapi32 dbghelp kernel32 msvcrt user32`. W33's thread and `inDllMain` lints stay green, and `test_wndproc` also refuses `CreateThread(` and `StartThread(` in the guard.
7. **No game names.** `NoGameNames` passes. See deviation 4 for the vendor comments and open question 3 for the watch list.

## Tests, red then green, and where they ran
Host tests ran with g++ in the pinned image on 2026-11-04 unless a line says otherwise.

| step | result |
|---|---|
| Step 2, port as is | `test_wndproc`: 19 passed, 0 failed |
| Step 3, decision 4 items 1-6 | 244 passed, 0 failed, first run: no policy gap |
| Step 3, mutation check (scratch copies) | 5 mutants of `OnGet`, `OnSet` and `OnDestroy`, all red (1 to 124 failures each) |
| Step 4, red, J16's shape (commit "step 4 (red)") | 264 passed, 2 failed: exactly the two else-if lints (`test_wndproc.cpp:217`, `:218`) |
| Step 4, green | 266 passed, 0 failed |
| `build.sh --docker all`, build `5a3a2bb0f813` | DLL builds; 17 core tests and 1 game test pass |
| `build.sh --docker smoke` | passed, 10 launches under wine, 2 dumps |
| CI run 41925828895 on `c0ef327` | every job green, `proxy` included (host tests, repro, smoke, no-gesture build) |
| `python3 wsc.py gates` (full), this checkout | exit 0: 15 ok, 1 warn, 0 failed; the warn is 5 skipped tests (no POSIX sh for one hook test, capstone not installed for four) |
| `python3 wsc.py policy --branch job/W39 --base origin/main` | **exit 1, REFUSED,** for two reasons only: no `jobs/W39/review.md` verdict, and the row is not `done` |

`policy` has no builder stage: it judges a branch as ready to merge, so both refusals stay until the reviewer's round. A builder may not clear either (C18). It raised nothing about the changed files, `VERSION`, other rows or trailers.

**Did any re-entry path need a policy change? No.** `WndProcBook` is as ported, apart from one comment word.

**The model changed once.** `Reset` now erases DXVK's record, as `g_windowProcMap.erase` does. The ported model kept it, which hid the windowed half of the fault. `Cyclic` now tells a cycle from an orphan.

**One run beyond the brief: the real guard on the real DLL.** The host tests only lint `dxvk_wndproc.cpp` as text and the smoke has no DXVK, so nothing else executes the patch. I ran the built proxy with the sha-pinned `d3d9_dxvk.dll` (3.1.1, `265888c31ca7`) under wine, in a throwaway container, using the smoke's stand-in exe:
- Key on: `backend: wndproc guard on DXVK's imports: 4 slots`, then `backend: dxvk ready`, then the first `Direct3DCreate9`.
- Key off: the J16 warning, no guard line.
- Both arms then exit 3: the container has no Vulkan, so DXVK throws at instance creation, after the guard has run.

This shows the import walk finds all four slots in the shipped DLL and that the order holds. It does not exercise `Hk_*` at run time: no window, no subclass, no switch. Those lines have never executed anywhere. It is a one-off, not in CI.

**`dump_read.py`** read a real 32-bit `ping.exe` dump (cdb from WinDbg 1.2610.1001.0, 2026-11-04): `loaded: PING` with no name given, `--exe Other.exe` overrides it. `tests/test_dump_read.py`: 9 pass.

## Version and W33
`VERSION` is 0.38.0, the next free minor: `origin/main` said 0.37.0 at the last check, and of the open job branches only W35 is unmerged. W39 is below `semver_from = 40`, so it bumps by hand as its brief says. The row also carries `semver=minor`: not required, but `release.py` counts a row with no level as `patch`. W33 was on `origin/main` before this branch started, so no merge was needed. W35 (PR #94) is still open at 0.35.0, so whichever merges second takes the next number.

## Deviations
1. **`tests/test_dump_read.py` is new and not in the brief's scope list.** The `--exe` logic is new, and the frame fix below needs a regression test.
2. **`docs/UPGRADING.md` holds the pin-bump steps,** not `CONSUMING.md`: they moved there on 2026-11-04 for the 30 KB cap, and CONSUMING's proxy section is now a pointer. Its one key line is there.
3. **The key row uses JSON `true`, not `1`.** `gen_tables.py` accepts only a real bool for a bool key. It renders as `1` in the ini and in `kKeys`, so the brief's meaning holds. Napoleon's row needs `true` too.
4. **Small changes to "ported as is" files, for decision 7.** Comments in `wndprocpolicy.h` and `test_wndproc.cpp` no longer name NVIDIA or napoleon's `proxy/runs/` path. `dxvk_wndproc.cpp` is byte-identical to `95f5a1e`.
5. **Two `dump_read.py` fixes the brief did not list.** The `--sym-cache` default named a napoleon folder; it is now `_scratch/symcache`. cdb's echo of `@@STACK` counted as a frame, so every frame count was one high; **figures in napoleon's J16 reports (8,528 and 8,520 frames) are one too many.** The cycle period and repeat counts are unaffected.
6. **The step 2 test dropped its source lint** until step 4, because the files it read did not exist yet.

## Open questions
1. **Key-off logging:** kept, as recommended.
2. **`OnDestroy` has no caller:** left as recommended, policy test only. No test showed a problem.
3. **`WATCH` in `dump_read.py` keeps `nvoglv32`, `nvgpucomp32` and `amdvlk32`.** I read these as the module-name strings decision 7 allows, since they are matched against names in the dump. Say if you read it differently; a `--watch` option would move them out.
4. **What the guard cannot see,** pinned in `OutOfReach` so a change shows. It sees only DXVK's own reads and writes. Neither case is the dumps' path, and I do not know whether `opengl32` does either; the PC run will tell:
   - A module with one saved-proc slot that installs again above DXVK while already below it closes a cycle by itself.
   - A dropped module that later writes back its saved previous proc puts DXVK's orphan proc on top, and the game hears nothing. That would look like lost input. A fix would mean rewriting a proc DXVK did not set, which is a kill criterion, so a finding here is a new job.
5. **Arm e's lost mouse.** The corrected model shows unguarded windowed mode as `GL -> DXVK -> DefWindowProc`, so the game receives nothing. That fits "the same chain fault", but it is a model result. The oversized window is still open, and the fix arm decides.
6. **Every game needs the key row, not only one that ships DXVK.** `test_config`'s list is the same for all games. The CONSUMING line keeps the brief's wording; `UPGRADING.md` says this plainly.

## What napoleon must do for J16's fix arm
After the tag, in its pin-bump job:
1. Add the `proxy.dxvk_wndproc_fix` row (`"default": true, "release_value": true`, owner `proxy`) to `registries/config_keys`, and run `python3 core/proxy/tools/gen_tables.py`.
2. Retire its own `dump_read.py` row in favour of the core's. Keep `napoleon.dxvk.wndproc_cycle`, `napoleon.dxvk.rehook_paths`, `napoleon.pc.vulkan_icds` and the run reports `20261030_j16dumps` and `20261104_j16ab` as evidence.
3. The build id changes: 20 consecutive acceptance passes on the new id, one set covering W33 and W39.
4. Run the fix arm with Liam present: 4K to 1440p, 4K to 1080p and windowed to fullscreen, three round trips each way. Expect no crash, no dump, `4 slots` at start, and `wndproc guard: window ... above DXVK's proc` naming the dropped module per switch. Also check that the mouse reaches the game after a fullscreen to windowed switch and that the Steam overlay opens. Input lost with the guard on is a separate finding (open questions 4 and 5).

## Fix round 1
Answers `## Round 1` of `review.md` (2026-11-05). This section supersedes the version statements above: **the version is 0.40.0, not 0.38.0.** The review asked for "Version and W33" to be rewritten, but `wsc jobs fix` forbids touching earlier report sections, so that section and the first paragraph stand as written and this one corrects them.

**1. Version (blocker): fixed, at 0.40.0 and not the review's 0.39.0, `024c313`, `ea7942f` and `96c4d95`.** `git merge origin/main` at `3688fc2` (W35, W36, the B90-B94 rows), no conflicts, no rebase, then `VERSION` 0.39.0 as the review said. Before I pushed, the release workflow took that number too: it opened `release/v0.39.0` for W36 (PR #116, auto-merge), merged at `c915e02`, so 0.39.0 is W36's release without this code. Nothing at 0.39.0 was pushed. I merged `main` again and took 0.40.0: the UPGRADING heading and CONSUMING's list say 0.40.0, and the section sits after W35's. No open job branch is above 0.39.0 (W31 0.37.0, W34 and W40 0.38.0). W39 is a legacy row below `semver_from`, so `release.py`'s `plan` tags a hand-bumped `VERSION` as it is when only legacy rows are new since the tag.

**This can happen again before the merge, and the gates will not say so.** Any release between now and W39's merge takes 0.40.0 the same way: a job merged while this branch waits makes the workflow cut the next minor. **The reviewer should check `git ls-remote --tags origin` and `origin/main:VERSION` immediately before merging,** and if 0.40.0 is gone, send it back for the next number. This is the review's item 8 happening on a legacy row, not only from W40 on.

**2. Short guard (should-fix): fixed, `4ea1e61`.** `kDxvkWndProcSlots = 4` is in `runtime.h`, a `static_assert` ties it to the guard's table, and `backend.cpp` logs a warning when fewer are patched. That covers a DXVK with other imports and a failed `VirtualProtect`, which counts as a slot not patched. The lint in `test_wndproc.cpp` was red first (`267 passed, 3 failed`, the three new checks), then green (`270 passed, 0 failed`), `build.sh --docker tests` and `--docker all` on the merged tree, 2026-11-05: 17 core tests and 1 game test pass. The info line is unchanged, so the `4 slots` expectation below stands. This changes `dxvk_wndproc.cpp`, which is no longer byte-identical to `95f5a1e` (one added line).

**3. Claims with nothing to open (should-fix): the wine run is redone below; the other two cannot be reopened.**
- **Wine run, redone 2026-11-05 on `4ea1e61`'s sources.** The DLL is sha256 `7049bcb17bc7`, built by `WSP_GAME_ROOT=proxy/tests/null_game proxy/tools/build.sh --docker all`. DXVK is the pinned 3.1.1 (`python3 proxy/tools/fetch_dxvk.py`, sha256 `265888c31ca7`). The arms ran in the pinned image with wine installed: `smoke_host.cpp` as `Game.exe`, `nullgame\dxvk\d3d9_dxvk.dll` in place, the ini `[proxy] backend=dxvk, exe_guard=0, dxvk_wndproc_fix=<0|1>`, then `WINEDEBUG=-all WINEDLLOVERRIDES="d3d9=n,b;winedbg.exe=d" wine Game.exe`. The third arm's DLL is a mingw stub exporting only `Direct3DCreate9`, so it has no user32 import. Log lines as they came:
  ```
  === arm pinned-on (key=1): exit 3
  backend: dxvk d3d9 loaded from Z:\tmp\game\nullgame\dxvk\d3d9_dxvk.dll (7856142 bytes); ...
  backend: wndproc guard on DXVK's imports: 4 slots
  backend: dxvk ready (Direct3DCreate9=77be1530)
  === arm pinned-off (key=0): exit 3
  [WARN ] backend: proxy.dxvk_wndproc_fix=0: an in-game fullscreen re-entry can loop DXVK's and a foreign window proc (J16)
  backend: dxvk ready (Direct3DCreate9=77be1530)
  === arm no-user32 (key=1): exit 0
  backend: wndproc guard on DXVK's imports: 0 slots
  [WARN ] backend: wndproc guard patched 0 of 4 slots: this DXVK reaches user32 past the guard, an in-game fullscreen re-entry can still loop (J16)
  backend: dxvk ready (Direct3DCreate9=78c314d0)
  ```
  The third arm is the review's "to see it fail", now passing. As before, the exit 3 arms stop in the smoke host at `Direct3DCreate9`, after the guard ran, which the original report put down to the container having no Vulkan; I did not re-examine the cause. The run is still a one-off outside CI, and `Hk_*` still have not executed. The scripts lived in a git-ignored scratch folder, so the lines above are the record.
- **The five mutants: cannot be reopened.** No log or command survives from the build session. The review reproduced the result with its own four mutants, so that is the evidence to rely on.
- **The `ping.exe` dump run: cannot be reopened.** No log survives and `cdb` is not on this session's PATH, so I did not repeat it. `tests/test_dump_read.py` (9 tests) covers the parsing on canned output, not a live cdb.

**4. CONSUMING against UPGRADING (should-fix): fixed, `ea7942f`, `20d82ab` and `96c4d95`, differently from the review.** "Every game that builds the proxy" would not fit: `main` left CONSUMING 49 bytes under the 30 KB cap, and the corrected line failed `doc_size`. So the line is gone from CONSUMING, whose upgrade-notes list now names `0.40.0 (new key proxy.dxvk_wndproc_fix)` and links UPGRADING, which owns the key row and already said every game. CONSUMING is 30,714 of 30,720 bytes, so the next job to add to it must move something out. This departs from brief decision 3's "one line in the proxy section".

**Later (5 to 8): left in the review.** `wsc jobs fix` asks for blockers and should-fix items, and `docs/REVIEW.md` keeps a repo's own later items in the review. No code changed for them. For the PC run, item 5 changes how to read the log, so add this to step 4 of "What napoleon must do": **a `wndproc guard: DXVK hooked window` line whose `proc` equals its `previous` is the write-back case of open question 4, and one more fullscreen entry turns it into the same crash, not only lost input.**

**Gates and policy on `96c4d95`:** `python3 wsc.py gates` exit 0: 15 ok, 1 warn, 0 failed, 1008 host tests passed, 5 skipped (no POSIX sh for one hook test, capstone not installed for four). `python3 wsc.py policy --branch job/W39 --base origin/main` exit 1, REFUSED for the two expected reasons only: the verdict is not yet `merge`, and the row is not `done`. The first full gates run failed `doc_size` on CONSUMING, which is why finding 4 went the way it did.

**Not shown yet:** CI's `proxy` job on the merged code, which the review asks for. This session's Docker host tests and DLL build are green on it; the repro build and the wine smoke run only in CI on this push. This report commit touches no `proxy/` file, so check that job on the head that last changed `proxy/` if it is skipped on the newest one.

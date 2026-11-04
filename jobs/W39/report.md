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

# W39: DXVK window-proc guard into the core (napoleon J16 port)

Model: Opus, reason: DLL work on window procedures and import tables inside the loaded backend, where a mistake shows only on the consumer's PC (a hang or
a stack overflow at an in-game resolution change), not in CI. Budget about 90 tool calls. At the cap, stop, commit, push and report what is left.

## Goal
Napoleon J16 found and fixed (not yet run on the PC) the crash behind every in-game resolution change under DXVK. The fix was written before napoleon
J12 moved the proxy sources into the core, so it lives only in napoleon's branch history. Liam approved on 2026-11-04: ship it in a core tag, napoleon
picks it up in a pin bump (row W39, PR #82).

**Mechanism** (napoleon `origin/job/J16`, `proxy/runs/20261030_j16dumps/README.md`, WER dumps 11252 and 4556):
1. DXVK 3.1.1 `EnterFullscreenMode` subclasses the game window (`HookWindowProc`); it keeps the game's proc as its previous one.
2. Another module subclasses the window on top: `opengl32!wglWndProc` (NVIDIA's ICD).
3. On a fullscreen re-entry DXVK calls `ResetWindowProc`. It reads `GWLP_WNDPROC`, finds `wglWndProc` and not its own proc, so it does not unhook and
   only erases its record.
4. `HookWindowProc` subclasses again and saves `wglWndProc` as its previous proc, while `wglWndProc`'s previous proc is DXVK's. The two call each other
   until the 1 MB main stack is gone (period-8 cycle, about 1,060 repeats).

**The A/B run with Liam today** (`proxy/runs/20261104_j16ab/README.md` on the same branch, run `20261104`, DLL build `cb34c06baf42`, unguarded):
- Vanilla d3d9 (`proxy.enabled=0`) survives the switch both ways. The bug is DXVK's, so the fix stays in the proxy.
- Every fullscreen re-entry under DXVK crashes in the same cycle: **4K to 1440p, 4K to 1080p, windowed to fullscreen** (the revert after an
  unconfirmed windowed try). It is not a 4K problem.
- In windowed mode the mouse did not reach the game, so Liam could not confirm the change. It is open whether that is the same chain fault or the
  oversized window (the window came up larger than the screen). The fix arm tells which.

The guard: points only `d3d9_dxvk.dll`'s own `GetWindowLong/SetWindowLong` (W and A) import slots at a guard. On a window DXVK hooked, a `GWL_WNDPROC`
read by DXVK reports DXVK's own proc, so DXVK restores the game's proc, the foreign layer above it is dropped (its module is logged), and no cycle can
form.

## What exists (read before building)
- **Source commit:** napoleon-remastered `95f5a1e` (`git -C /c/Users/liamr/repos/napoleon-remastered fetch origin job/J16`; read with `git show
  95f5a1e:<path>`; read-only, never edit or commit there). Files: `proxy/core/dxvk_wndproc.cpp` (87 lines), `proxy/core/wndprocpolicy.h` (33),
  `proxy/core/backend.cpp` (the 8-line hook-up), `proxy/core/runtime.h` (one declaration), `proxy/tests/test_wndproc.cpp` (116),
  `proxy/tools/dump_read.py` (182). Its other files (`proxy/napoleon/...`, `registries/config_keys`) are game-side and stay there.
- The core's paths differ: `proxy/core/` there is `proxy/src/` here. Includes are by name (`#include "wndprocpolicy.h"`; the tests include
  `"wndprocpolicy.h"` through `-I proxy/src`, as `test_display_guard.cpp` includes `display_guard.h`).
- **Hook-up point:** `proxy/src/backend.cpp` `LoadOnce` (about line 86) runs `LoadDxvk` and then the system fallback. The DLL's build compiles every
  tracked top-level `proxy/src/*.cpp` (`build_id.py --sources`), so a new `.cpp` needs no list edit but must be `git add`ed.
- **Host tests:** `proxy/tools/build.sh` runs every `proxy/tests/test_*.cpp` through the glob (line 202); a new test needs no list edit. Config keys the
  core reads are checked by `proxy/tests/test_config.cpp` (77-79) and the null game's table; keys are declared by the game's adapter table, never in the
  core (the core registry has no `config_keys` rows). The null game's rows are `proxy/tests/null_game/registries/config_keys.jsonl`; regenerate its
  generated files with `WSP_GAME_ROOT=proxy/tests/null_game python3 proxy/tools/gen_tables.py`.
- `docs/CONSUMING.md` owns what a consumer must add after a tag. `jobs/W33/brief.md` is the sibling DLL job (see "W33 first").

## Decisions already made (follow them; a deviation goes in the report with its reason)
1. **Where each piece lands.**
   - `proxy/src/wndprocpolicy.h`: the pure `WndProcBook` policy, ported as is.
   - `proxy/src/dxvk_wndproc.cpp`: `DxvkWndProcGuard(HMODULE)`, the import-slot patch of the loaded backend DLL, ported as is. It declares and logs the
     same lines (`wndproc guard: ...` per dropped layer, `DXVK hooked/restored window` per set). No game names, no game paths.
   - `proxy/src/runtime.h`: the declaration `int DxvkWndProcGuard(HMODULE dxvk);` under the `backend.cpp` group.
   - `proxy/src/backend.cpp`: the hook-up after `LoadDxvk` (decision 2).
   - `proxy/tests/test_wndproc.cpp`: the host test (decision 4).
   - `proxy/tools/dump_read.py`: a core tool (decision 5).
2. **The `else if` binding bug.** In `95f5a1e` the guard block is `if (s_real && !strcmp(s_name, "dxvk")) { ... }` placed after the log line and
   **before** `else if (want != "system") LOGW("... unknown proxy.backend ...")`. That `else` now binds to the guard's `if`, so the unknown-backend
   warning fires for every non-DXVK backend, and never for an unknown name that fell back. Port it with the unknown-backend warning kept on the `want`
   chain, and guard on the loaded DLL, not on the config string:
   ```
   if (want == "dxvk") { s_real = LoadDxvk(); if (!s_real) LOGW(...fallback...); }
   else if (want != "system") LOGW(...unknown proxy.backend...);
   if (s_real && !strcmp(s_name, "dxvk")) { ...guard or the key-off warning... }
   if (!s_real) s_real = LoadSystem();
   ```
   The guard runs right after DXVK loaded and before the first `Direct3DCreate9` into it (it is already inside `LoadOnce`, called from the first export,
   never from DllMain). It holds in pass-through too: DXVK is the backend, not engine memory, so no `Rt().plan` gate applies and no engine site is
   touched. A test lints this order (decision 4, item 7).
3. **The config key, mechanism only.** The core declares nothing in a registry. The mechanism is `rt.cfg.Bool("proxy.dxvk_wndproc_fix")`:
   - bool, **default 1, release value 1 (on)**. Key off logs `backend: proxy.dxvk_wndproc_fix=0: ...` (the J16 warning text, kept) and patches nothing.
   - The null game gets a `proxy.dxvk_wndproc_fix` row in its `config_keys.jsonl` (default 1, release_value 1, owner `proxy`) and regenerated files, so
     every existing host test and the smoke run on a table that has the key. Without a row `cfg.Bool` of an unknown key is a lint failure in
     `test_guard.cpp`; check how it names the key and keep that scan covering `dxvk_wndproc.cpp`'s and `backend.cpp`'s reads.
   - `docs/CONSUMING.md`: one line in the proxy section (and the "after the tag" list of the release notes): "A game that ships DXVK adds the key row
     `proxy.dxvk_wndproc_fix` (bool, default 1, release value 1, owner `proxy`) to its `config_keys` and runs `gen_tables.py`; without the row the
     build's host tests fail and name it." Napoleon adds the row, the ini line and the generated `kKeys` entry in its own pin-bump job. The core does not.
4. **Host tests that model all three re-entry paths.** Port `test_wndproc.cpp` (116 lines: the DXVK `ResetWindowProc`/`HookWindowProc` model, a
   `Window` with a top proc and per-proc previous procs, `Reaches`) and extend it. Each case runs unguarded (the chain is cyclic: the J16 bug, proving
   the model reproduces the dump) and guarded (the chain ends at the game's proc):
   1. **Device recreate while fullscreen** (4K to 1440p, 4K to 1080p: the swapchain is rebuilt, `HookWindowProc` runs again over `wglWndProc`).
   2. **Windowed to fullscreen `Reset`** (arm e's revert: `ResetWindowProc` on leaving fullscreen with the foreign layer on top, then
      `HookWindowProc` on re-entry).
   3. **Fullscreen to windowed**, then the revert (windowed, then fullscreen again), twice in a row.
   4. **Three layers** (two foreign subclassers above DXVK, one of them an overlay) and a **foreign layer installed between two switches**.
   5. **Several switches** (10 round trips): the chain stays acyclic and ends at the game each time; `Foreign` is true only while a foreign layer is on top.
   6. **Never over-reach:** a window DXVK did not hook, or one DXVK already restored, is reported as it is; `OnGet` on an unknown hwnd returns `actual`;
      `OnDestroy` forgets a window (a recycled hwnd is not told a stale proc).
   7. **Lints** (the test reads sources through `--src`): `dxvk_wndproc.cpp` patches only a module's import table and never the exe image or a game
      module; `backend.cpp` calls `DxvkWndProcGuard` under `s_real` and the DXVK name, after `LoadDxvk` and before `Resolve<...>("Direct3DCreate9")`, and the
      unknown-backend `LOGW` is the `else if` of the `want == "dxvk"` test (this is the regression for decision 2); `DxvkWndProcGuard` is not called from
      `DllMain` or `Init`.
   Commit the red state first where a case compiles against the old code (the else-if lint fails on `95f5a1e`'s shape), then green.
5. **The dump reader as a core tool.** `proxy/tools/dump_read.py` ported, game-agnostic: the module watch list (`WATCH`) takes the game exe's name from an
   option (`--exe NAME`, default the dump's own main module) instead of the literal `Napoleon`; the dump folders in the header say
   `%LOCALAPPDATA%\CrashDumps\<mod>` generically. Header in its first 40 lines: `purpose:`, `usage:`, `when:`, `not-a-verb: wraps an external debugger on a
   local dump` (it is not a registry operation). Then `python3 wsc.py reg add tools proxy/tools/dump_read.py` and commit the file and
   `registries/tools.jsonl` together (the `tools` gate). Stdlib only. Search first (`wsc find dump`): extend an existing dump tool if one fits
   (`proxy/tools/wer` is a folder, check it), do not add a near-duplicate. Napoleon's `tools` row for its own copy is retired by napoleon in the bump.
6. **No new import, no new thread, no config parse change.** The DLL's import list stays as it is (it already imports `user32` and `kernel32`). The guard
   runs inline inside `LoadOnce`; no `CreateThread` (W33's lint counts them).
7. **No game names in core files**, no `Napoleon`, no AMD or NVIDIA literals beyond the module-name strings the guard logs from the process at run time.

## W33 first (merge order)
W33 (`jobs/W33`, in build) also edits the DLL: `runtime.h`, `dllmain.cpp` (a `StartThread` and an `inDllMain` flag, threads moved off DllMain),
`dev.cpp`, the null game's `config_keys.jsonl` and generated `tables.h`/ini, `test_config.cpp`, `test_guard.cpp`, docs and `VERSION`. Its brief says
`backend.cpp` is untouched, but the row says both change the DLL inputs and ship in one acceptance run, and W33's `Direct3DCreate9`-time thread start
sits in `backend.cpp`'s export (check with `git log origin/main -- proxy/src/backend.cpp`).
- **Start only when W33 is on `origin/main`** (`python3 wsc.py jobs next --id W39` says so). If W33 is not yet merged, do not build on `job/W33`.
- Branch from `origin/main` after W33. Read what W33 changed in `backend.cpp` and `runtime.h` first, and place the guard hook-up so that it stays inside
  `LoadOnce`, before any `StartThread` W33 added to the first `Direct3DCreate9` path; the guard must not introduce a thread or run in `DllMain`.
- If W33 merges while you build: `git merge origin/main` (never rebase a pushed branch). Do not hand-merge the generated null-game files: take W33's
  `config_keys.jsonl` rows, add yours, and regenerate `tables.h` and `nullgame.ini`. `VERSION`: take the next free minor against `origin/main` at the last
  commit, and say which. W33's lints that count `CreateThread(` and check `inDllMain` must stay green (they are the check that decision 6 holds).
- The consumer runs **one** acceptance pass set on a build with both (napoleon rule 79: 20 passes on the new build id).

## Scope: files this job touches
- `proxy/src/dxvk_wndproc.cpp`, `proxy/src/wndprocpolicy.h`, `proxy/src/runtime.h`, `proxy/src/backend.cpp`.
- `proxy/tests/test_wndproc.cpp`, and `test_guard.cpp`/`test_config.cpp` only if their key scans need the new reads named.
- `proxy/tests/null_game/registries/config_keys.jsonl` and its regenerated `generated/tables.h` and `nullgame.ini` (and the `null_game_no_gesture` copy
  that `gen_tables.py` also writes, if the repo keeps one).
- `proxy/tools/dump_read.py`, `registries/tools.jsonl`.
- `docs/CONSUMING.md` (the key line, the pin-bump steps), `VERSION`. If a doc lists the proxy files, one line there.
No change to `patch_engine.h`, `headless.cpp`, `dllmain.cpp` or any `adapter.cpp`. A change to `dllmain.cpp` is a kill criterion.

## Steps
1. Read "What exists" and W33's merged change to `backend.cpp`/`runtime.h`. Check this session can build and run the host tests
   (`proxy/tools/build.sh --docker tests`); if not, push early and read CI's `proxy` job.
2. Port `wndprocpolicy.h` and `test_wndproc.cpp` as they were at `95f5a1e`, with the include path changed. Run them: green (the model and policy are
   unchanged). Commit.
3. Write the extended cases of decision 4 (1-6) against the ported policy. Cases that expose a policy gap (a three-layer or revert path that the old
   test did not cover) go in red first, then fix `WndProcBook` and keep the old cases green. Say in the report whether any of the three re-entry paths
   needed a policy change.
4. Port `dxvk_wndproc.cpp` and the `runtime.h` line; add the hook-up in `backend.cpp` with the corrected `else if` (decision 2) and the lints
   (decision 4, item 7). Add the key row and regenerate the null game. Green.
5. Port `dump_read.py` with its header and the tools row (decision 5); `python3 wsc.py gates`.
6. `docs/CONSUMING.md` and `VERSION` (a minor bump: a DLL input, a new log set, a new key). `python3 wsc.py gates` (full), CI's `proxy` job green
   (host tests and the wine smoke), then `python3 wsc.py policy --branch job/W39 --base origin/main`.

## Tests and acceptance: what each layer can prove
- **Host tests (CI, every push):** the policy and the model of DXVK's hook code for all three re-entry paths the A/B run crashed on, the else-if
  regression, the lint that the patch touches only the loaded backend's imports, and every existing proxy host test on the regenerated null-game table.
- **Wine smoke (CI):** the DLL still loads, `backend: dxvk` launches still start. The stand-in has no DXVK window and no foreign subclass, so the smoke
  shows `backend: wndproc guard on DXVK's imports: <n> slots` at most (if wine's DXVK stand-in is present) and cannot prove the fix.
- **The PC proof is napoleon J16's fix arm, after a pin bump** (needs the tag, then napoleon's pin-bump job, then Liam present): launch with
  `proxy.dxvk_wndproc_fix=1` (the default) and, in-game, change the resolution **4K to 1440p, 4K to 1080p, and windowed to fullscreen**, three round
  trips each way. Expect no crash and no dump; `proxy.log` shows `wndproc guard: window ... above DXVK's proc` naming the dropped module
  (`opengl32.dll`) per switch. **Also check that the mouse reaches the game after a fullscreen to windowed switch** (arm e lost it): move and click in
  windowed mode, then confirm the change. If the mouse is still lost with the guard on, the cause is not the chain: report it as a separate finding
  (the oversized window, `3862x2216` on a `3840x2160` screen) for napoleon, do not widen this job. Also check the Steam overlay (Shift+Tab) still opens.
  Napoleon J16 records it; this job does not claim it.
- Build id: `proxy/src` changes, so the consumer re-runs its acceptance passes after the bump (rule 79).

## VERSION
A minor bump. Take the next free minor against `origin/main` at the last commit (re-read `VERSION` and the open `job/*` branches; W33 may bump first).
If one merges first, merge `main` (never rebase) and take the next number. Say which. Tags are Liam's.

## What consumers must do after the tag
- Napoleon (its pin-bump job, J16's fix arm follows): add the `proxy.dxvk_wndproc_fix` key row (bool, default 1, release value 1, owner `proxy`) to its
  `registries/config_keys`, run `python3 core/proxy/tools/gen_tables.py` (`proxy/napoleon/generated/tables.h` and the ini gain the key), retire its own `dump_read.py` row in favour of the core's,
  keep `napoleon.dxvk.wndproc_cycle`, `napoleon.dxvk.rehook_paths`, `napoleon.pc.vulkan_icds` and the run reports `20261030_j16dumps` and `20261104_j16ab`
  as napoleon evidence, then run J16's fix arm.
- Build id changes: 20 consecutive acceptance passes on the new id (with W33's changes in the same run).

## Kill criteria
- A re-entry path of decision 4 cannot be modelled without the guard rewriting a proc that DXVK did not set, or the guard would need any hook other
  than d3d9_dxvk.dll's four user32 import slots (an inline patch, the exe image, a system DLL): stop, commit and report.
- The hook-up would need a thread, `DllMain`, or `dllmain.cpp`: stop and report; never run the guard from `DllMain`.
- Core CI red after three fix attempts for a cause in this change, or more than about 90 tool calls: stop, commit, push and report what is left. For a
  version collision follow VERSION; never rebase a pushed branch.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **Key off logging.** Keep J16's `LOGW` on `proxy.dxvk_wndproc_fix=0` (recommended: the A/B arm a needs the warning in the log to be identifiable).
2. **Windows destroyed while hooked.** `WndProcBook::OnDestroy` exists but the port has no caller (the J16 source never hooked `DestroyWindow`).
   Recommended: leave it and test the policy only; a recycled hwnd keeps a stale record only until DXVK's next `SetWindowLong` on it, which overwrites it.
   Raise it in the report if a test shows otherwise.

## Finish
Write the report in `jobs/W39/report.md`: what was built, per decision; the tests, red then green, and where they ran; whether any re-entry path needed a
policy change; the version taken and how W33 was merged; deviations; open questions; what napoleon must do for J16's fix arm.

Then run `wsc reg set jobs W39 status=review report=jobs/W39/report.md` (`python3 wsc.py`). Push `job/W39`, open the draft pull request, and stop: an
independent reviewer merges (C18), and Liam tags.

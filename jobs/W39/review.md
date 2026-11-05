# W39 review

## Round 1 (2026-11-05, branch job/W39 at d59f80f)

**Verdict: merge after fixes.**

The port is sound: I found no defect in the guard, the policy or the hook-up. It cannot merge as it stands because `main` moved under it. `v0.38.0` is already tagged on W35, without this code, and the branch's docs tell consumers the guard ships in 0.38.0. No code outside the job folder and the row was changed in this round.

### Blocker

1. **The version is taken, and the docs name the wrong tag.** `VERSION:1`, `docs/UPGRADING.md:50`, `docs/CONSUMING.md:278`, `jobs/W39/report.md:45-46`.
   - W35 merged at 0.38.0 and `refs/tags/v0.38.0` is on origin at its commit `2390136`. `git merge-tree` is clean only because both sides wrote the same `VERSION`, so `policy` and the gates say nothing.
   - A consumer following "DLL changes in 0.38.0 (W39)" pins `v0.38.0`, adds the key row and runs J16's fix arm with Liam present, on a DLL with no guard.
   - The brief's VERSION section covers this: merge `main`, never rebase, take the next number, say which.
   - Fix: `git merge origin/main`, then `VERSION` 0.39.0 (`release.py`'s `plan` then tags it as it is, since W39 is a legacy row). Change `0.38.0` to `0.39.0` in the UPGRADING heading and the CONSUMING link. Move the UPGRADING section so it sits after W35's. Rewrite the report's "Version and W33": it says `main` is 0.37.0 and W35 is open.
   - To see it fail: `git ls-remote origin refs/tags/v0.38.0`, then `git merge-base --is-ancestor d59f80f v0.38.0` exits 1.
   - Check after the merge that CI's `proxy` job actually ran on the new head (see "Machines").

### Should-fix

2. **A guard that patches too few slots says so only at info level.** `proxy/src/backend.cpp:97`, `proxy/src/dxvk_wndproc.cpp:78`.
   - `0 slots` logs as a normal info line, and a failed `VirtualProtect` is a silent `continue`. After a DXVK pin bump that changes the imports, the crash returns with nothing in the log at warning level.
   - "the pinned DXVK imports 4" is prose in `docs/UPGRADING.md`, and the report says the real-DLL check is a one-off, not in CI. That is a rule left as prose (REVIEW step 5).
   - Fix: `LOGW` when the count is under 4, and a lint for that line in `test_wndproc.cpp`.
   - To see it fail: point the guard at a module with no user32 import. The log has no warning.
3. **Three report claims have nothing to open.** `jobs/W39/report.md:21`, `:36-41`, `:43`.
   - These are the five mutants, the wine run of the real guard, and the `ping.exe` dump. None cites a log, a command or a run id.
   - I reproduced the mutation result and confirmed the imports statically (see "Evidence checked"), so what is left is the wine run, the only time the guard's code has executed at all.
   - Fix: paste the commands and the log lines into the report, or say plainly that they cannot be reopened.
4. **The CONSUMING line contradicts UPGRADING.** `docs/CONSUMING.md:278` says "A game that ships DXVK adds the key row". `docs/UPGRADING.md:52` says every game that builds the proxy does, and `test_config.cpp:79` agrees. The builder kept the brief's words and raised it as open question 6: the brief's line is wrong, so correct it to "Every game that builds the proxy", as the same edit as finding 1.

### Later

5. **The write-back case in `OutOfReach` understates the outcome.** `proxy/tests/test_wndproc.cpp:172`, `jobs/W39/report.md` open question 4.
   - The report calls it lost input. One more fullscreen entry turns it into the same crash: with DXVK's orphan on top and no map record, `Hook` saves DXVK's proc as its own previous one. I added `r.d.Hook()` to that case on a scratch copy: `cyclic=1`, `prev(DXVK)==DXVK`.
   - It stays out of scope and is not the dumps' path. Pin that step in `OutOfReach`, and add to the fix-arm notes that a `DXVK hooked window` line whose `proc` equals its `previous` is this case.
6. **One lint proves nothing.** `proxy/tests/test_wndproc.cpp:221`: `be.find("LoadOnce", load + 1) != np` passes on any later mention. The real protection is `Count(be, "DxvkWndProcGuard(") == 1` plus the `dllmain.cpp` check; no other source file is scanned. Drop the line or scan every `proxy/src/*.cpp`.
7. **`dump_read.py` and W35's `wsc crash symbolise` now overlap in purpose.** W35 merged after the builder's `wsc find dump`, so the search was right at the time. They do different work (cdb's stack walk and cycle against a no-debugger map lookup), so this is not a duplicate. Each tool's `when:` should name the other.
8. **Version numbers in doc headings cannot survive C27.** From W40 on a job does not know its version when it writes its UPGRADING section, so finding 1 can recur without any `VERSION` edit. Decide how UPGRADING names a release that is not cut yet. This is a core item, recorded here as the repo's own.

### Machines

- `python3 wsc.py gates` on d59f80f: exit 0, 14 ok, 2 warn, 0 failed, 920 host tests passed and 5 skipped. The warnings are this worktree's absolute `core.hooksPath` and the skipped tests.
- `python3 wsc.py policy --branch job/W39 --base origin/main` on d59f80f: REFUSED, for the two expected reasons only (no verdict yet, row not `done`).
- `wsc jobs review`: all 9 checks on d59f80f passed or were skipped. CI's `proxy` job was **skipped** on d59f80f (run 41928582676); its last run is 41925828895 on `c0ef327`, success. The two later commits are the report, the row and `VERSION`, so that run covers the code.
- A throwaway merge of d59f80f with `origin/main` at `2390136`: no conflicts, `gates --fast` 15 ok. `build.sh --docker tests` could not finish there because lua.org refused the container's connection, so **the full proxy build on merged code is unproven**. W35 changed `build.sh`. CI on the fix head has to show it.

### Evidence checked

- **The model against DXVK:** `src/d3d9/d3d9_window.cpp` at tag v3.1.1 (GitHub API, 2026-11-05). `ResetWindowProc` (105-124) and `HookWindowProc` (127-144) match the test's `Dxvk` model, including the record erased on a foreign top and the `DefWindowProc` answer when there is no record. `WM_DESTROY` (line 60) also goes through `ResetWindowProc`, so a window closed while hooked clears the book's record: open question 2 holds.
- **The port:** `dxvk_wndproc.cpp` is byte-identical to napoleon `95f5a1e`. `wndprocpolicy.h` differs only in the two comment lines deviation 4 names.
- **The imports:** `fetch_dxvk.py` then `exe_info.py --imports user32.dll` on the pinned `d3d9_dxvk.dll` (sha256 `265888c31ca7`) lists all four of `Get/SetWindowLongW/A`. x86 has no `...Ptr` export to miss.
- **The tests:** `test_wndproc` compiled alone with build.sh's flags in Docker on the merged tree: 266 passed, 0 failed. My own mutants on a copy, all red: `OnGet` passes through (124 failed), a restore keeps the record (12), `OnDestroy` does nothing (4), the guard not keyed on the DXVK name (2).
- **Risk-first reading:** I chose `dxvk_wndproc.cpp` and the `LoadOnce` hook-up, because a mistake there shows only as a hang or crash on the PC. Checked: `LOGI` is a plain function call, so the guard runs at every log level. The `(ULONG)` casts keep addresses above 2 GB consistent. No log call is made under the book's lock. `DevOnDirect3DCreate` runs after `BackendEnsure` (`backend.cpp:137`, `:141`), so the guard is ahead of W33's threads. A charset thunk from `GetWindowLong` compares as foreign and takes the restore path, which is safe.
- **The brief:** every deliverable is present; `dllmain.cpp`, `patch_engine.h` and `headless.cpp` are untouched. The deviations are named with reasons and I accept them. `WATCH`'s vendor module names (open question 3) are fine: decision 5 changes only the game exe's entry.

**Not proven by anyone:** `Hk_*` have never run with a real window and a subclass. Only napoleon's J16 fix arm can show the fix works, as the report says.

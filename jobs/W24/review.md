# W24 review

## Round 1 (2026-11-04, branch job/W24 at 6f60278)

**Verdict: merge.**

Reviewer: a fresh session (37f2bffe-b8ef-4efd-8cd9-634c9cd06be4), which neither built nor fixed the branch.

### Machines
- `python3 wsc.py gates` (full, Windows PC, 2026-11-04): 13 ok, 2 warn, 0 failed; 644 host tests passed, 5 skipped (the POSIX hook test and capstone),
  as on `main`. The two warnings are the known W23 bootstrap `pull_request` trigger (W27) and the skips.
- `python3 wsc.py policy --branch job/W24 --base origin/main` before the review: refused only for the missing review and the row not `done`, as
  expected. It notes that the branch changes `warscape/ci_render.py`; the change is the `fetch_cache` block (decision 15), proven by `tests/test_ci.py`.
- CI: run 41808275796 at 05e1c74 is green in every job (gates on ubuntu and windows, changes, proxy, harness-windows). I read its log: the
  `toolchain: pinned: 7 packages ...` line for `all` and `repro`, the step summary echoed (`### proxy DLL: null`, id `nullgame-ci`, sha256
  `3a50d3fd...96ffa8cd`, 4408320 bytes, the toolchain line), `build.sh repro: identical from another path`, and `build.sh smoke: self_hash matches d3d9.dll
  (... hashed in 13 ms under wine)`. The head 6f60278 differs from 05e1c74 only in `jobs/W24/report.md` and the row (`git diff --stat`), so its run skips
  `proxy` and `harness-windows` on their pass markers; `gates (ubuntu-latest)` is green there and `gates (windows-latest)` was still running when
  `jobs review` listed it. It is a required check, so auto-merge waits for it.

### Claims against evidence
- The pinned set, the version lines, the smoke ms, the DLL size and the summary text all match run 41808275796's log (the probe run 41802947502 for the
  set). The 4.4 MB DLL is over the brief's "1 to 4 MB" estimate; the 13 to 24 ms is well inside the 100 ms cap.
- Without evidence I can open: the `--inputs` before and after (`60f7dfc714ec` to `ec2808bc5db8`), the local `--docker all` run (393 s, three
  `Connection refused` from lua.org cured by the retry), and the observed Python red at 409ef9c. Each is a PC-only measurement with no log in the
  repo. None of them changes the outcome: the id change is what the role list implies, and the CR bug that run found has a host test that fails without the fix.

### The brief
Every deliverable is present: decisions 1 to 17, the docs, C25, B62 and B69 removed, `VERSION` 0.27.0. The thirteen deviations are named and reasoned. I agree with all of them. Deviation 11
(the `self_hash` line must be log line 2 exactly) is stricter than the brief and matches decision 10. Nothing is outside scope: no `dev.cpp`, no thread,
no `-Wl,-Map`, no pass file, no CI `WSP_BUILD_ID` change, no adapter.

### Risk-first reading
I picked the code that runs in every consumer's launch or decides which bytes ship. I read it in depth:
- `proxy/src/dllmain.cpp` `LogSelfHash` and `guard_driver.cpp` `ReadChunks`: CreateFileW, ReadFile, CloseHandle and GetTickCount only, under the loader
  lock. The guard keeps its PE parse on the first chunk and its error texts ("cannot open the exe (error N)", "read error N"). The hash runs before the
  second-process and `proxy.enabled=0` branches, so every log has the line. Nothing leaks: the handle is closed on the read-error path.
- `proxy/src/sha256.h`: the constants, the schedule, the padding and the big-endian output are correct, and the FIPS vectors and split tests run in CI.
- `proxy/tools/build.sh`: `toolchain_check` runs before `build_dll`, which makes the first mingw compile (the Lua core, then `ui_objs mingw32`). Under
  `set -e` the `|| rc=$?` capture is right, and `-dirty` is appended once and reaches `-DWSP_BUILD_ID`. The `--docker` route checks the sources on the host and passes them in,
  and the container runs the same check. The source-name character guard and the CR strip are sound.
- `proxy/tools/toolchain.py` `check`: an unknown or not-installed package is reported (`db:Status-Abbrev`). A compiler resolved through `readlink -f`
  must be owned by a pinned package, so the posix-variant fallback `i686-w64-mingw32-g++` is refused, as intended.
- `fetch_ui.fetch_git`: a checkout that is not the pin, or not clean, is removed and fetched again. The checkouts are never patched (the FreeType options
  come from `ui_objs`' own headers), so a good cache is trusted. The sha and patch refusals stay outside `netfetch.retry`.
- `harness/ctl.py` `build_info`: `dll_sha256` comes from the same per-launch `proxy.log`, and is `None` for an old log.

### Findings
No blockers, and no should-fix items.

**Later** (filed as warscape-core `docs/BACKLOG.md` B86 on this branch):
1. `proxy/tools/build.sh:36`: `WSP_SOURCES` is honoured on any run, not only inside `--docker`. To see it: `WSP_SOURCES=dllmain.cpp build.sh dll` on a
   native build skips the tracked-source refusal and links one file. CI and `--docker` never set it by hand, so nothing bites today.
2. `proxy/tools/build.sh:71-85`: the `WSP_TOOLCHAIN=any` branch has no host test (report deviation 12). A stub `toolchain.py` that exits 2 would prove the
   `-dirty` id and the refusal without it.
3. `proxy/tools/build_id.py` `main` (`--sources`): the adapter folder honours `--root`, but the core sources folder comes from `layout.proxy_src()`'s
   default. It is harmless while build.sh never passes `--root`.

Notes, not findings:
- `docs/CONSUMING.md` is at 30,616 of 30,720 bytes. The `doc_size` gate stops the next addition, and the report's open question 4 says to split a section.
- The fetch_ui trust rule on a Docker Desktop bind mount, where a second `--docker` build reuses the checkout, is not shown by a second run. `git init` on
  such a mount sets `core.filemode=false`, so `_git_ok` should pass. If it does not, the cost is a refetch, never a wrong byte.

## Round 1 (2026-11-04, branch job/W25 at 686f258)

**Verdict: merge.**

Reviewed cold from the brief, the report and the diff. I merged `origin/main` (W38: watcher 1.4.1, 0.30.1) into the branch first; the only conflicts were `VERSION` and the watcher `$Version` line, resolved to 0.33.0 and 1.5.0. The C28 collision did not arise: main's newest decision is C27 and W15 has not merged, so C28 is free. Whichever of W15 and W25 merges second renumbers (policy refuses otherwise).

### Machines
- CI on the pre-merge head 1d44ccd: `gates (ubuntu)` and `gates (windows)` green. `proxy` and `harness-windows` were skipped on that head because it changed only docs and registries; the same code ran green on e17cb1c (run 41884383568: `harness-windows` unit 57/0, integration 34/0 including the rewritten `exe check (J18, W25)` case).
- Local `python3 wsc.py gates` (full) on the pre-merge head, 2026-11-04: 12 ok, 3 warn (hooks path, ci_render W23 note, 5 skips), 0 failed, 737 host tests.
- I did not run the integration suite, any game, `pc_deploy` or `job.sh` against real folders.

### Claims against evidence
Every claim I checked has a test or CI log behind it: the 11 failing fixtures are named with the test each turned red; the exe hash timing (27 to 36 ms) is dated and sized; the deviations are listed with reasons (retry count, case-insensitive `warn`, `set` refusing with no identity, a five-line CONSUMING section for the `doc_size` cap).

### Brief
All 15 decisions are present. Scope respected: `harness/job.sh` untouched, no game names, `stage_save.py` and `load_save.sh` left to napoleon (open question 4). No kill criterion hit.

### Risk-first reading
Read in depth: `game_lock`, `write_atomic`, `resolve_identity` (`proxy/tools/pc_deploy.py:71-217`), `safe_rel`/`plain_name`/`verify_kit` (483-520), and the watcher's reload rule, `Resolve-ExeCheck`, restart carry and `Exe-Check -Fresh`. Reason: they decide whether a game launches mid-write, whether an ini survives a crash, and whether the launch gate can be switched off.
- The lock never reimplements W10's protocol: `holds` is checked before `lock`, the caller's lock is left held, release is in `finally`, a refusal exits 2 with nothing written.
- `write_atomic` writes a same-folder temp, fsyncs, retries `PermissionError`, and removes only its own temp.
- The carry is written only for exit 3/4, read and removed at start, and ignored after 300 s; the reload refuses a weaker value and logs once.

### Findings
**Blocker:** none.

**Should-fix:** none.

**Later:**
1. A watcher crash or killed powershell (any exit but 3, 4, 10, 11) is relaunched by `watch.cmd` with no carry and reads the ini as written, so `exe_check=warn` can still be applied by killing the watcher. The builder documented this in C28 and recommends leaving it to the agent hook; a later job can keep a refreshed carry until exit 11.
2. `registries/jobs/W25.json` `description` still lists `stage_save.py` and `load_save.sh` (moved to napoleon J91). The row text is the owner's; left as is.
3. The `d3d9.dll`-by-sha stray rule applies at `install` only, not in `status` (reported as a deviation); acceptable, since `status` has no kit to compare against.

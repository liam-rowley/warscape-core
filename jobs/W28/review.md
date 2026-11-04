## Round 2 (2026-11-04, branch job/W28 at b181c20)

**Verdict: merge.**

All three round-1 should-fix items are answered in `## Fix round 1` of the report and hold up.
Checked: local `python3 wsc.py gates` at b181c20: 13 ok, 3 warn (hooks path, ci_render W23 bootstrap note, 5 platform skips), 0 failed; 762 host tests passed; `doc_paths` ok over 17 living docs.
CI on the branch head: `gates` on ubuntu and windows, `proxy` and `harness-windows` green. `origin/main` (60ba80e) is already merged in, so there is no conflict.
- should-fix 1 (`doc_paths` is an error): fixed. `gates.py` returns `error`; 14 `path_ignore` entries, mostly prefix globs, as predicted; stale lines edited; B87 closed.
- should-fix 2 (decision number): fixed. The row is C30, the next free number after main's C29; VERSION 0.35.0 follows main's 0.34.0.
- should-fix 3 (ignored paths reported): fixed. `../` tokens are dropped before `git check-ignore --stdin`, and any exit code other than 0 or 1 is now a gate error. A host test covers it.

### later
- Plan PR #87 also carries a C28 and renumbers when it lands. That is its own renumber, not this job's.
- Main's `doc_size` gate was red on `docs/CONSUMING.md`; this branch moved two sections to `CONSUMING_OPTIONS.md`. Whichever of this branch and the main fix lands second keeps only one move.

## Round 1 (2026-11-04, branch job/W28 at 3009a43)

**Verdict: merge after fixes.**

The six fixes are built, each with a failing-first test, and the work is sound. Two things must change before merge: the `doc_paths` severity (Liam's answer) and the decision number.
Checked: `wsc policy` refused only for the missing review and row (expected before this round); `python3 wsc.py gates --only doc_paths` run here (71 warnings); CI at 3009a43: `gates (ubuntu-latest)` green, windows still running at review time. I did not re-run the host tests: CI covers them.
Read in depth: `gates.skips`/`selected` (a skip can hide a gate, so its guard matters most) and `gate_doc_paths`. Both match the brief.

### should-fix (1): `doc_paths` must be an error, as Liam decided
`warscape/gates.py:308` returns `'warn'`. Liam's answer to the brief's open question 2 (2026-11-04, plan PR #87, decision C28 pending on main) is: the gate is an error.
The builder's deviation was legitimate under the brief's own kill criterion (more than about 15 `path_ignore` entries means ship a warn), but the owner has since overridden it. The criterion assumed one ignore entry per path. `path_ignore` takes globs, so the list is short.
I ran the gate here: 71 misses, 62 distinct tokens.
- 32 tokens are `discovery/core/*`, the old-path column of a move table: one entry (`discovery/core/*`) covers all of them, and `(was ...)` on the table rows would do the same.
- Game and empire paths by prefix: `harness/*`, `rml_mod/*`, `perf_mod/*`, `upscale/*`, `viewer/*`, `tools/*`, `shaders/*`, `docs/plans/*`. A game's tests named in `docs/CONSUMING.md` and `docs/BACKLOG.md` (`tests/test_repo_rules.py`, `test_build_id`, `test_jobs_hooks`, `test_registry_merge`, `test_usage_reader`, `test_proxy_host`, `test_viewer`, `gesture_test.cpp`) need either a line marker or a few entries.
- Truly stale or not paths: `registries/jobs.md` (CONSUMING.md:155; the view now lives under `_scratch/registries/`), `docs/CI_FAILURES.md` and `docs/LEARNINGS_HARNESS.md` (BACKLOG.md; check which repo owns them), `ctx.root/core/` (a code snippet; tighten the token rule or ignore it), `jobs/F1/report.md` and `jobs/F2/report.md`.
Roughly 15 to 20 entries in total, mostly prefix globs. Fix: make the gate return `error`, add the entries and line markers, edit the truly stale lines, run `python3 wsc.py gates` green, and update the gate docstring, README "Gates", the CONSUMING section, B87 (close it) and the report's deviation. If the entries truly cannot stay short, say so and ask Liam rather than relying on the kill criterion.

### should-fix (2): decision number
The `docs/DECISIONS.md` row C28 collides with Liam's C28 in plan PR #87 and with W15 and W25. Merge `origin/main` before the next round and take the next free number at that time (C29 if #87 lands first). Also keep VERSION in line with C27 if W29 has merged by then.

### should-fix (3): git-ignored paths are not skipped in this checkout
The report says a git-ignored path passes, but `CLAUDE.md:8` (`_scratch/registries/tools.md`), `CLAUDE.md:35` and `README.md:42` (`_scratch/registries/`) are reported here, in a linked worktree on Windows, although `git check-ignore -v _scratch/registries` matches `.gitignore:5`. The `check-ignore` call at `warscape/gates.py:302` fails or returns nothing in this setup (check `git_env()`, the `-C` root and the return code; a code other than 0 or 1 is silently treated as "nothing ignored"). Make a failure of that call loud, add a host test with an ignored path, or put `_scratch/*` in `path_ignore`.

### later
- Napoleon has 56 misses (report); it needs its pin-bump pass once the gate is an error. Add that to the pin-bump steps.

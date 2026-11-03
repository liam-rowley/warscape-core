# W13 review

## Round 1 (2026-11-03, branch job/W13 at f18b3e6)

**Verdict: merge.**

Reviewed by a fresh session (not the builder, not the orchestrator that wrote the report). Branch head as built: `fff21af`; `f18b3e6` is the reviewer's
merge of `main` (below).

### Machines
- `python3 wsc.py gates` (full) on `fff21af`: 13 ok, 1 warn (the five known skips: POSIX hook test, capstone), 0 failed; 370 host tests passed.
- After merging `main` (`f18b3e6`): the same full run, re-done on the merged tree: 13 ok, 1 warn, 0 failed (see the commit's push run for CI).
- `python3 wsc.py policy --branch job/W13 --base origin/main` before the merge: REFUSED, because `main` had gained C21 (W11) and the branch did not
  carry it (append-only check), plus the review and `done` row a review supplies. After the merge and this review: ok.
- CI on `fff21af`: `gates` green; `harness-windows` and `proxy` were still running at review start (this change does not touch `proxy/` or `harness/`).
- Acceptance grep (`call_hooks|hooks\.py|\[jobs\] hooks` in `*.py`, `*.md`): only the migration message, its test, the `gatemods` docstring and error, C18 and
  C22 (history) and `docs/CONSUMING.md`'s migration section. Meets the brief.

### Brief against the work
- Every deliverable is present: `warscape/gatemods.py` (one docstring owns the contract), `[gates] dirs`, `NAME`/`run`/`STAGES`/`FAST`, the four stages wired at
  their call sites, `Result.html`, `[jobs] hooks` refused with a message written for it (`repo.REMOVED`, checked before the generic merge), `hooks.py` deleted,
  the fixture game migrated (one module for `jobs`/`policy`/`view`, plus a `gates`-stage `no_todo`), `test_gatemods.py` (20 cases covering every case the brief
  lists), C22, the backlog edits (B1 and B46 gone, B50 reworded, B9 and B14 say B1 is built), VERSION, and the napoleon steps in `docs/CONSUMING.md`.
- Red-then-green: `d748204` adds the tests before `a728e67` adds the module.
- Fixture assertions unchanged apart from names (kill criterion respected).
- Deviations are all named with reasons in the report: C22 not C21 (W11 took it), 0.20.0 (0.17.x on main, 0.18 and 0.19 held by W17 and W8), the static
  `--only` help, the one-line `discovery/briefpaths.py` header, the small additions (warn lines, detail-less error counts as one problem, non-Result is an error).
  All are sound.

### Risk-first reading
I read in depth `warscape/gatemods.py` (it executes repo code on every `wsc gates`, `jobs check` and `policy` run in every consumer) and the `policy` and
`jobs` wiring (`policy.run_check`, `jobq.check`, `gates.selected`/`run`, `gate_jobs`), because they decide every pull request in napoleon. Findings: none
blocking. The loader keeps the old one's behaviour (load by path, no `__pycache__`, not in `sys.modules`), validates every attribute with a message naming the
file, and caches on (root, path, mtime, size). `policy` loads modules before any git read, so a broken module is exit 2, not a silent pass. A crash or a
non-Result is an `error`, never a pass. Old hook names fail loudly.

### Fixed by the reviewer
- **should-fix (done, `f18b3e6`):** the branch was two merges behind `main` (W14 0.17.0, W11 0.17.1) with conflicts in `VERSION`, `docs/DECISIONS.md` and
  `docs/BACKLOG.md`, and `policy` refused it for the missing C21 row. Merged `main` (never rebased): VERSION stays 0.20.0 (still the next free minor above the
  open branches' claims), C21 (W11) then C22, backlog keeps main's removals (B2, B3, B7, B11, B12) and this branch's (B1, B46) and its B9 rewording.

### Later (into this review; none needs a core backlog row)
- `warscape/jobq.py` `check`: a `jobs`-stage module's brief problems are now listed after all core problems, where the old `brief_problems` hook's were listed
  inside each job's block. Same messages, same count, different order when several jobs have problems; the report's "same order" was shown with one problem only.
  Harmless (nothing parses the order); mention it in napoleon's pin-bump job if its tests compare full output.
- The napoleon rehearsal's evidence lives only in the report (the scratch copy is deleted, no log committed). The brief asked for commands and a diff summary in the
  report, which is there, so this is not a finding against the job; napoleon's pin-bump job re-runs the same comparison for real (the report's open question 5:
  size it as its own job).
- `--only` help names only the core gates (no repo context in `add_arguments`); the unknown-name error lists the real set. Acceptable as reported.

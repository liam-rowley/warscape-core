# W44: wsc audit: the pipeline measured, findings as data

Phase 1 (the pipeline). Liam, 2026-11-05: "automate these kinds of audits and boil it down where I answer questions after it and it
automatically gets applied; a self improving system with my approvals" (C41). The two audits so far were done by hand: napoleon
`docs/audits/AUDIT_2026-11-03.md` (a 70 KB read, then its findings filed into rows by hand in its "Where each finding went" section), and a
2026-11-05 chat audit computed with ad hoc git one-liners. This job turns the measuring half into code: a `wsc audit` verb that computes
the metrics, compares them with `[audit]` thresholds, and writes findings with stable ids that W45's proposals and W47's audit session
build on. No model computes a number; a finding is a fact with its evidence.

Model: Opus, reason: the numbers every later proposal and Liam's answers rest on; a metric that is wrong in a plausible way steers the whole loop (D52: builds on Opus).
Budget about 130 tool calls: about 15 reading, 30 for the synthetic-repo fixtures and red tests, 50 to build the metrics, 15 to calibrate on the two repos, 20 for docs, gates and the report. Comparables: W26 (120, the autopilot), W31 (150; Usage 136).
Semver: minor
No DLL or harness input changes: a new library module, a new verb, `warscape/repo.py` defaults, tests and docs. A game's pin bump to this tag carries no acceptance run for it (napoleon rule 79, J58).
Subagents: none.

## Start
1. `git pull`; `python3 wsc.py jobs next --id W44` and follow its mechanics. If this session's model is not Opus, stop and say so.
2. `python3 wsc.py gates --fast` for a baseline; `python3 wsc.py find audit` and `python3 wsc.py find scan` (reuse before you write).
3. Read C41 in `docs/DECISIONS.md`, and the rows of W45, W46 and W47 (`registries/jobs/`): they consume this job's output, so the finding
   ids and the record's shape are their contract.
4. Read, read-only, napoleon's `docs/audits/AUDIT_2026-11-03.md` sections "Process evidence" and "Automation opportunities"
   (`git -C ../napoleon-remastered show origin/main:docs/audits/AUDIT_2026-11-03.md`): the metrics below come from it and from the
   2026-11-05 audit.

## Target facts (check each again before relying on it)
- Reuse, do not re-implement: `warscape/jobq.py` `lane` and `LANES` (the queue lanes `jobs view` shows), `review_rounds`,
  `remote_branches` and `remote_heads` (one-call branch fetch, napoleon J56), `rows_at`; `warscape/policy.py` `verdict`, `scan` (W40: the one
  existing history scan, the model for walking merged pull requests); `warscape/checks.py` `living_docs` and `oversize` (the `doc_size`
  gate); `warscape/ci.py` `gh` (the injectable runner) and `warscape/ci_settings.py` (the read-only `gh api` pattern, exit 2 when gh cannot
  be read); `warscape/repo.py` `git_env`, `matches`, `DEFAULTS`, `Ctx`.
- A verb is `warscape/verbs/<name>.py` with `NAME`, `HELP`, `add_arguments`, `run` (CLAUDE.md); `wsc --root <path>` runs it on another repo.
- Job merges on `main` are squash commits whose subject starts `<[jobs] id_prefix><n>:` (or `<id> `); briefs start `brief`, plans `plan`.
  Check this on both repos' `git log --first-parent origin/main` before relying on it, and say in the report how many subjects matched no
  kind.
- `[docs] records` and a dated file name exempt a doc from `doc_size` (`warscape/checks.py` `living_docs`): `docs/audits/AUDIT_<date>.*`
  is a dated record.

## Decisions already made for this job
1. **The verb:** `wsc audit [--since <YYYY-MM-DD|sha>] [--record] [--json PATH] [--offline] [--only <metric>,...]`. Default window: the
   last `[audit] window_days` days. Output: `_scratch/audits/AUDIT_<date>.json` and `.md`; with `--record`, `<[audit] dir>/AUDIT_<date>.json`
   and `.md` (a second record on one day gets `_2`). It prints the findings, one line each, and exits 0 (findings are not failures), 1 when
   a metric could not be computed and was not skipped on purpose, 2 when the repo cannot be read.
2. **The record** (JSON, `"version": 1`): `repo`, `date`, `main` (sha), `window` (`since`, `until`, job merges counted), `metrics`
   (`{id: {value, details}}`), `findings` (list of `{id, metric, subject, severity, value, threshold, direction, evidence}`; `evidence`
   is one sentence with the numbers), `skipped` (`[{metric, reason}]`). The Markdown is generated from the JSON (never edited). A finding
   id is `<rule>:<subject>` (`hot_file:docs/CONSUMING.md`, `chokepoint:J78`, `idle_queue`), stable across runs, because W45 suppresses and
   re-measures by id.
3. **The metrics and their rules** (every threshold an `[audit]` key in `DEFAULTS`, overridable in `wsc.toml`):
   - `hot_files`: job merges in the window, files each touched, excluding `<[jobs] dir>/**`, `<registries_dir>/jobs/**` and `[audit]
     hot_exempt`. Rule `hot_file:<path>` when the share of job merges touching it is at least `hot_file_share` (0.25) and the count at
     least `hot_file_min` (5). Severity high at 0.5.
   - `conflict_files`: merge commits with two parents reachable from the remote `job/*` and `brief/*` branches and not from `main`,
     dated in the window; per merge, the files changed on both sides (the names changed from each parent to the merge, intersected). Rule
     `conflict_file:<path>` at `both_sides_min` (3) or more. Record how many merges and branches were read; a clone without the branches
     says so in `skipped` unless online (fetch them the way `jobs` verbs do).
   - `job_lifetime`: per job merged in the window that has its branch: hours from its oldest commit not on `main` to its squash merge,
     merges from `main` inside it, files in the squash commit. Rules `long_job:<id>` over `max_job_hours` (24), `wide_job:<id>` over
     `max_job_files` (60), and `branch_exposure` when the share of jobs with a merge from `main` is at least 0.5. Details: median and p90.
   - `work_mix`: the phase of the last `window_jobs` (20) merged jobs, from their rows. Rule `overhead_share` when the phases in
     `overhead_phases` (default `[]`: off; a game names its pipeline phase) are over `max_overhead_share` (0.4).
   - `queue`: the lanes as `jobs view` computes them (reuse `lane`). Rules `idle_queue` (ready rows and nothing in progress, review or
     fix), `pc_serial` (ready rows at least 4 and at least 0.75 of them `needs_pc`), `chokepoint:<id>` (a row not done with at least
     `chokepoint_fanout` (4) not-done rows depending on it, directly or not; severity high when the row is `needs_brief`).
   - `review_loop`: over done jobs merged in the window, rounds per job and the share merged in round 1 (reuse `review_rounds` and
     `verdict`). Rule `review_churn` under `min_round1_merge` (0.5). Details: the count of "later" findings (lines with a bold `later`
     marker), reported, no rule (W32 owns them).
   - `brief_cost`: median brief and report bytes of the jobs in the window, and brief merges against job merges. Rule `brief_heavy` when
     the median brief is over `max_brief_ratio` (1.5) times the median report.
   - `startup_read`: bytes of `CLAUDE.md`, `README.md` and `[audit] startup_docs`. Rule `startup_heavy` over `max_startup_kb` (40).
   - `doc_caps`: living docs (reuse `living_docs`) at `doc_cap_share` (0.9) of `[docs] max_kb` or more. Rule `doc_cap:<path>`.
   - `pin_lag` (a game, `[ci] core` set): the `[core] version` against the newest `vX.Y.Z` tag in the submodule's object store. Rule
     `pin_lag` at `max_pin_lag` (5) or more minor versions behind.
   - `throughput`: job and brief merges per day in the window against the window before it. Rule `slowdown` under `slowdown_ratio` (0.5).
   - `ci_durations` (online only): per required check (`[ci] required_checks`), the median duration over the last `ci_runs` (20) runs on
     `main`, read with `gh api` through the injectable runner. Rule `slow_check:<name>` over `ci_check_minutes` (a table; default 10).
     Offline, or gh unreadable: `skipped` with the reason, exit 0.
4. **Injectable everything:** git and gh through a runner argument, the clock through `now=`, so every metric has a host test on a
   synthetic repository built in a temp folder (`git init`, commits with set dates, a `main`, branches with merges from `main`, a fake
   origin). No test reads the real repo's history.
5. **`DEFAULTS['audit']`** holds every key above with a one-line comment each, plus `dir = "docs/audits"`. `wsc.toml` here sets nothing
   new; say in the report which keys a game should set (napoleon: `overhead_phases = [1]`, `startup_docs` naming `docs/DECISIONS.md` and
   `docs/plans/PLAN.md`).
6. **The core's own queue is audited too:** `wsc audit` on the core works with `[ci] core` empty (no `pin_lag`).

## Deliverables
1. `warscape/audit.py` (library: one function per metric returning `(value, details, findings)`, a `record()` that assembles them) and
   `warscape/verbs/audit.py` (decision 1), with its header and a tools row (`python3 wsc.py reg add tools warscape/verbs/audit.py`).
2. `DEFAULTS['audit']` (decision 5).
3. Host tests in `tests/test_audit.py`, red first: each rule fires on a fixture built to trip it and stays quiet on one built not to; a
   finding id is the same across two runs; `--offline` puts `ci_durations` in `skipped` and exits 0; an unreadable repo exits 2; the
   Markdown is a pure function of the JSON.
4. **Calibration on the two real repos**, pasted in the report: `python3 wsc.py audit --since 2026-10-28` on the core, and
   `python3 wsc.py --root ../napoleon-remastered audit --since 2026-10-28 --offline` (read-only; if napoleon's older `wsc.toml` will not
   load in this core, say why and stop that half). The 2026-11-05 audit computed, with `git log --format=%s origin/main -- <file>` on the
   core at `f743242`: `docs/CONSUMING.md` in 32 of 38 job merges, `VERSION` 28, `docs/BACKLOG.md` 24, `registries/tools.jsonl` 23,
   `docs/DECISIONS.md` 18; and on napoleon at `2975b13`, 12 ready rows with none in progress and `J78` gating at least 8 rows. Your numbers
   at those shas should agree; a difference is something to explain in the report (a counting rule, an exclusion), never to tune away.
5. `docs/CONSUMING.md`: one short paragraph for `wsc audit` and the `[audit]` keys (the file is at the `doc_size` cap: pay for it with a
   cut of the same size, or link a new `docs/AUDIT_METRICS.md` that lists the rules; that file is the one owner of the metric definitions).
6. A first record committed on this branch: `docs/audits/AUDIT_<date>.json` and `.md` for the core (`--record`, online).

## Out of scope
- Proposals, answers, suppression and re-measuring (W45); the autopilot cadence (W47); a game's own metrics as gate modules (a later row
  if a game needs one).
- Fixing anything a finding names: the record is the deliverable.
- Napoleon's `wsc.toml` (its adoption job sets its keys).

## Open questions
1. Should `VERSION` count in `hot_files`? recommended: yes until the release workflow's W40 cut-over has a full window behind it, then
   add it to the core's `hot_exempt` in a later change; default after: 2026-11-10.
2. Should `conflict_files` fetch branches itself when online? recommended: yes, through the same one-call fetch the `jobs` verbs use, and
   never in `--offline`; default after: 2026-11-08.

## Kill criteria
- A metric cannot be computed from git, the registries and `gh` without a new dependency (C3: standard library only): drop that metric
  to `skipped` with the reason, build the rest, and say so.
- The calibration numbers differ from the 2026-11-05 ones by more than one merge on a file or one row on the queue, and no counting rule
  explains it after 10 calls: stop and report both sets.
- `wsc --root ../napoleon-remastered` needs any write to napoleon: stop that half; this job never writes outside the core.
- Over about 130 tool calls: stop, commit, report what is left.

## Finish
Report in `jobs/W44/report.md` with `## What was built`, `## Evidence` (tests red then green, the branch's CI run id, both calibration
outputs, the record's path), `## Deviations from the brief and why`, `## Open questions`, and the `[audit]` keys a game should set. Write the
usage line: `python3 wsc.py jobs usage W44 --write --from-json <file>`. Then:
`wsc reg set jobs W44 status=review report=jobs/W44/report.md` (`python3 wsc.py`)
Push `job/W44`, open the draft pull request, and stop: an independent reviewer merges (C18); the release workflow tags (C27).

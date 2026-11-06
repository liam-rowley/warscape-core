# Audit metrics: what `wsc audit` measures

The one owner of the metric definitions (W44, C41). Code: `warscape/audit.py`; the verb's flags: `warscape/verbs/audit.py`; every threshold is an `[audit]` key with its
default in `warscape/repo.py` `DEFAULTS`. Everything is read at one commit (origin/main), never the working tree. No model computes a number.

## The record
`"version": 1`, `repo` (origin's name, so a worktree records the same repo), `date`, `main` (sha), `window` (`since`, `until`, `job_merges`), `metrics` (`{id: {value, details}}`),
`findings`, `skipped` and `failed` (`[{metric, reason}]`). `skipped` is on purpose (offline, nothing to read, not in `--only`); `failed` broke, and makes the verb exit 1. A metric absent
from `metrics` is in one of the two, so a missing finding never reads as a fixed one. The Markdown is generated from the JSON.

A finding is `{id, metric, subject, severity, value, threshold, direction, evidence}`. Its id is `<rule>:<subject>` or `<rule>`, stable across runs: W45 suppresses and re-measures by
it. `direction` is the worse way: `above` or `below`. Severity is `medium` unless the rule says otherwise.

## How a merge is read
First-parent commits of main. A subject starting `<[jobs] id_prefix><n>:` or `<id> ` is a job merge, except `<id> brief`, a brief merge; `brief`, `plan`, `meta` and `release` start theirs; the rest are `other`
(`throughput` details, `kinds`). A job can merge twice (W38: its row, then its work): each merge counts in `hot_files`, the id once elsewhere, measured to its last merge. No
rename detection: a move touches both names.

## The rules

| Metric | Measures | Rule and threshold |
| --- | --- | --- |
| `hot_files` | files job merges touched, without `<[jobs] dir>/**`, `<registries_dir>/jobs/**`, `hot_exempt` | `hot_file:<path>`: share of job merges at least `hot_file_share`, count at least `hot_file_min`; high from `hot_file_high` |
| `conflict_files` | two-parent merges on origin's job/ and brief/ branches, not on main, in the window; a file changed from both parents to the merge | `conflict_file:<path>`: at least `both_sides_min` merges |
| `job_lifetime` | per job with a branch: hours from its oldest commit not on main to its merge, merges from main, files in the merge | `long_job:<id>` over `max_job_hours`; `wide_job:<id>` over `max_job_files`; `branch_exposure`: at least `branch_exposure_share` of jobs merged main |
| `work_mix` | the phases of the last `window_jobs` merged jobs | `overhead_share`: `overhead_phases` over `max_overhead_share` (`[]`: off) |
| `queue` | the `jobs view` lanes, as if the PC were here | `idle_queue` (high): ready rows, none in progress, review or fix; `pc_serial`: at least `pc_serial_min` ready, at least `pc_serial_share` of them `needs_pc`; `chokepoint:<id>`: at least `chokepoint_fanout` not-done rows wait on it, directly or not (high when it is `needs_brief`) |
| `review_loop` | rounds per done job in the window; share with one round and a plain `merge` | `review_churn`: under `min_round1_merge`. Details count lines with a bold `later` marker (no rule: W32) |
| `brief_cost` | median brief and report bytes; brief merges against job merges | `brief_heavy`: median brief over `max_brief_ratio` median reports |
| `startup_read` | KiB of `CLAUDE.md`, `README.md`, `startup_docs` | `startup_heavy`: over `max_startup_kb` |
| `doc_caps` | living docs (the `doc_size` gate's list) | `doc_cap:<path>`: at `doc_cap_share` of `[docs] max_kb` or more |
| `pin_lag` | `[core] version` against the newest `vX.Y.Z` tag at the origin of the `[ci] core` folder (a game), read with `ls-remote`; `--offline`: its local store, and the evidence and `details.tags_from` say so | `pin_lag`: at least `max_pin_lag` minors behind; a newer major counts as the limit |
| `throughput` | job and brief merges a day against the window before | `slowdown`: under `slowdown_ratio`; no finding with nothing before |
| `ci_durations` | online: median minutes per required check over the last `ci_runs` runs per workflow on main, a skipped job not counted | `slow_check:<name>`: over `ci_check_minutes[<name>]`, else `ci_check_default` |

`hot_files` and `conflict_files` raise nothing for a path no longer at main: it keeps its count, and the paths that would have fired are in `details.gone`.

The lanes ignore this machine's PC on purpose: `jobs view` shows a `needs_pc` row as waiting where the PC is absent, and a finding must not depend on where the audit ran.

## What a game sets
`overhead_phases` (its pipeline phase) and `startup_docs` (what its sessions read first, for napoleon `docs/DECISIONS.md` and `docs/plans/PLAN.md`); the rest have defaults that
work. `ci_check_minutes` takes the check names as `[ci] required_checks` writes them.

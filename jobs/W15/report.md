# W15 report: Registry verbs: reg remove, last_used stamping, exe words in find

W15 makes three changes to the registry CLI, all stdlib with host tests. `wsc reg remove <reg> <id>...` refuses while anything points at
the row (B28). A tool's last use is derived from the done job reports that cite it, so a repo with a job queue can turn retirement
warnings on (B6, C28). `wsc find` sends exe-shaped words to the game's `exe_strings.tsv.gz` (B43). Branch `job/W15`, VERSION 0.31.0,
built by session ed0f955b (a subagent; the orchestrating session of the same id wrote this file from the builder's hand-back, because the
builder's own write of it was refused).

## What was built
- **B28, `reg remove`.**
  - Code: `Registry.remove`, `row_file` and `refs_to` in `warscape/registry.py`; `remove`, `referrers` and `_problems` in `warscape/verbs/reg.py`.
  - What it refuses: any registry's `x-ref` field (a scalar or an array item); in the tools registry, another row's `superseded:<id>` or a
    tool path still in `ctx.files()`; in the jobs registry, an existing `jobs/<id>/` folder.
  - Backstop: if none of those match, every `Registry.check` and `tools.check` run before and after the removal, and any new problem
    refuses. The target registry's own canonical-form and stale-view lines are ignored, because the save fixes them.
  - A refusal exits 1, writes nothing and prints one `<file>: <row>: <field>` line per referrer. An unknown id also exits 1 and names the
    registry. Rows that only point at each other go in one call. On success the verb saves and re-renders the view.
  - The tools check's "remove the row" message now names `wsc reg remove tools <id>`.
- **B6, derived last use.**
  - Code: `last_uses`, `cite_pattern` and `done_job_date` in `warscape/tools.py`, plus its retirement check.
  - Which jobs count: only `done` ones. A job's date is the newest `## Round N (date, ...)` heading of its review; a legacy review uses the
    first date in its first 5 lines.
  - What counts as a citation: the tool's path as a whole path (a `core/` prefix is allowed), or `wsc <verb>`, `wsc.py <verb>` or
    `wsc.<verb>` as a word. The result is cached on `ctx`.
  - The warning uses the later of the derived date and the row's `last_used`, and names its source: `(jobs/..)` or `(row)`. `DEFAULTS` and
    the core's `wsc.toml` stay at 0; only the toml comment changed.
- **B43, exe words in `find`.**
  - Code: `exe_shaped`, `exe_table`, `exe_search` and the `--exe` flag in `warscape/verbs/find.py`. `discovery/exe_strings.py` `find` is
    split into `search` and `line`, and its output is unchanged.
  - The table is opened only when an exe word is present (or `--exe` / `--in exe_strings` is given). Words are ANDed as case-insensitive
    literals. `--json` is supported.
  - Exit code: 0 when either the registries or the table has a hit. An exe-only hit suppresses the "no matches" line.
  - With no table, `find` prints nothing extra, unless `--exe` is given; then it prints one line naming the fix.
- **`reg add tools --missing` paths.** The verb now resolves the paths against the repo root, not the shell folder. Run from the core
  checkout, a repo-relative `harness/job.sh` had resolved to the core's own file; the tests gate found this.
- **Docs and rows.** `README.md`: a `reg remove` line. `docs/CONSUMING.md`: a "Removing a row" note, a "Tool retirement" section and a
  `find` line under Discovery. `docs/DECISIONS.md`: C28. `docs/BACKLOG.md`: B6, B28 and B43 removed. Tool rows `wsc.reg`, `wsc.find` and
  `discovery.core.exe_strings` refreshed, ids kept.

## Evidence
- **Tests red first:** commits 3540988 and 7e6121d hold only tests: 38 run, 18 failures and 8 errors.
- **Tests green:** `python3 wsc.py gates` (full) has 13 ok, 2 warn and 0 failed. The host tests are 737 passed and 5 skipped (no POSIX sh,
  no capstone); the other warn is ci_render's existing note.
- **Acceptance:** `wsc reg remove tools wsc.reg` refuses with exit 1 (its file still exists) and leaves `git status` clean.
- **`find` unchanged in the core:** compared with `origin/main`'s `find.py` for `gfx_hardware_shadows`, `reg check`, `CampaignUI` and
  `zzqx`, the output and exit code are byte-identical.
- **Scratch napoleon copy (2026-11-04):** a `--depth 1` clone with this branch's tree at `core/`, nothing committed. It needed three local
  edits to load: add `[discovery] adapter = "discovery/napoleon"`, drop `[jobs] hooks` (0.20.0) and delete `tools/verbs/discovery.py` (0.15.0).
  - `find gfx_hardware_shadows`: the registry hits, then `exe strings (discovery/napoleon/exe_strings.tsv.gz): 2 hits` (0x0f0e4a8 and
    0x0f0e4c4), exit 0.
  - `last_uses`: 57 done jobs; 59 of 119 live tools have a derived date. At 90 days none warn, because every row's date is less than 90 days old.
- **CI:** draft PR #85; gates ubuntu passed when the builder stopped; windows, proxy and harness were pending.

## Deviations from the brief, and why
- **`--in exe_strings` also searches plain words**, as `--exe` does. Otherwise it would search nothing.
- **A path preceded by `/`, or followed by `.x`, `-x` or `/x`, does not count as cited.** The brief's literal "not followed by a letter,
  digit or `_`" would count `harness/job.sh.bak`, which its own test case rules out. A leading `core/` and a sentence's closing `.` still count.
- **`last_uses` loads the jobs and tools rows together** with `load_from_config` instead of `jobq.main_rows`.
- **The tests load the discovery modules with `importlib`** to satisfy the stdlib-only check.
- **This report was written by the orchestrating session** from the builder's hand-back text, unchanged in substance.

## Open questions
1. The `warscape/repo.py` `DEFAULTS` comment still says retirement is off "until the job queue stamps". The brief said leave `DEFAULTS`
   alone; C28 now owns the reason.
2. The rendered `last_used` column shows the row's date, not the derived one (brief open question 1).
3. A per-game `find` source would be a `find` stage of W13's gate modules. Nothing was built for it.
4. VERSION 0.31.0 is the next free number after `origin/main`'s 0.30.0. If another job merges first with it, the second takes the next number.

## What napoleon must do after the tag
- **No acceptance passes:** nothing under `proxy/` or `harness/` changed.
- **Retirement (opt-in):** set `[tools] retire_after_days = 90`, run `reg check tools`, then supersede or `reg remove` what it lists, or
  cite those tools in the next report that uses them. Then close `jobs/J5/rules.md` row 72.
- **`reg remove`:** replaces `git rm` of a row file (J55 item 4).
- **`find` and the exe index:** needs napoleon past 0.15.0 with `[discovery] adapter`.
- **The pin bump from v0.9.0:** also follows the notes for 0.10.0 to 0.15.0.

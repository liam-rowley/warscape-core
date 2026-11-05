# W31 report: Usage accounting in reports: a Usage line, wsc jobs usage, budget lifts, per-card usage

A game can now hold its reports to their budgets. With `[jobs] usage_from` set, `wsc jobs check` needs one `Usage:` line in each report on a row in review, fix or done. It fails usage above 1.25 times the effective budget, a model other than the row's, and a broken `budget_lifts` chain. `wsc jobs usage <id> --write` fills the line from a command the game names, so the core reads no transcript. `budget_lifts` is a new row field, and the `jobs view` cards show usage against budget, with a per-card line for gate modules (B50). Everything is off by default, so `jobs check` on a queue that sets neither key gives the same result as before. Built by session 4efda02d-37d4-4632-bba0-f82f9930ba5f.

Usage: 136 tool calls; models: opus; 2 sessions, by hand, no reader: build 87 (the review's transcript count) and fix round 1 about 49, 2026-11-05

## What was built, per decision
1. **The Usage line.** `parse_usage` in `warscape/jobq.py` reads the shape in decision 1. It ignores a line in a code fence, and it refuses two lines or a line with no models part or no free text. `Usage` is a NamedTuple of calls, models and note.
2. **Switch.** `[jobs] usage_from` and `usage_cmd` are in `repo.py` `DEFAULTS` and validated in the `semver_from` style. `usage_rule(jid)` is the `semver_rule` twin. The core's own `wsc.toml` sets `usage_from = 42` (see Deviations).
3. **The hook.** `run_usage_cmd` splits the template with `shlex`, fills `{id}` per argument, and runs with no shell, the repo root as cwd, a 60 s timeout and stdin closed. Non-zero, bad JSON, a duplicate key, a missing or mistyped key, a timeout and an empty `usage_cmd` are each a `ValueError` with the reason.
4. **The verb.** `wsc jobs usage <id> [--write] [--from-json FILE]` is in `warscape/verbs/jobs.py`. `set_usage_line` replaces the line or inserts it after the first paragraph, and it works on bytes so a CRLF report stays CRLF. It reads its own result back before anything is written. It refuses a missing report, and two lines.
5. **The checks.** `usage_problems(jid, row, brief, report)` is pure and `problems` calls it. The ceiling uses whole numbers (`calls * 4 > budget * 5`), so a budget of 150 allows 187 and refuses 188. `effective_budget` and `lift_problems` hold the lift rules. A malformed `budget_lifts` is an error, never a crash.
6. **`budget_lifts`.** It is in `schemas/jobs.schema.json` with `additionalProperties: false`. `wsc reg set` already takes JSON through `key:=`, so no `reg` change was needed; a test proves it (`RegSet`), and `docs/USAGE.md` gives the command.
7. **B50.** `Result.cards` is on `warscape/gates.py`. `card_lines` collects the `view`-stage cards and `card()` draws them under `.meta`. `usage_chip` draws `usage 142 / 150 calls · opus` from the report with no game code, red above 1.25 x. B50 is gone from `docs/BACKLOG.md`.
8. **No new dependency, no network, no `~/.claude`.** Standard library only. The command is the only seam.
9. **Napoleon's follow-up** is `docs/BACKLOG.md` B104, in B87's form.

`brief_budget` is factored out of `brief_problems` as the brief asked; the new regex limits the number to nine digits so `int()` cannot fail on absurd input.

## Tests
- Red first: commit f5d7d31, CI run 41927317973. Both `gates` jobs failed on `tests` with `Ran 883 tests ... FAILED (failures=15, errors=63, skipped=1)`, and 78 is the count the new tests gave locally.
- Green: `python3 wsc.py gates` on this checkout at 1b50727 on 2026-11-04: 15 ok, 1 warn, 0 failed, 995 host tests passed, 5 skipped (a POSIX sh is missing here for one, capstone for four).
- Final CI on the code: run 41928676211 at 1b50727 on 2026-11-04, success on `gates (ubuntu-latest)`, `gates (windows-latest)`, `proxy` and `harness-windows`. The commit after it adds only this report and the row, so its run cannot be cited here.

New tests: `tests/test_usage.py` (79 cases) and `tests/test_jobs.py` `UsageRule` (5 cases).

### Fixtures that must go red
Each was applied alone as a working-tree mutation, run against `tests.test_usage` and `tests.test_jobs.UsageRule`, and restored; the tests passed again afterwards.

| Mutation | Result | Tests that failed |
|---|---|---|
| The ceiling at 1.5 x | red | 4, first `test_the_ceiling_is_one_and_a_quarter_times_the_budget` |
| The ceiling ignoring lifts | red | 3, first `test_effective_budget_is_the_newest_lift_else_the_brief` |
| Model compared case-sensitively | red | 2, first `test_models_compare_by_lower_case_first_word` |
| `--write` appending a second line | red | 4, first `test_crlf_stays_crlf` |
| `usage_from` ignored | red | 5, first `test_finish_says_to_fill_the_line_once_the_rule_is_on` |
| A failing command still writing | red | 2, first `test_failures_exit_1_and_write_nothing` |

## Proof without a game
Run on a throwaway copy of this repo's `wsc.toml`, `registries/` and `jobs/`, with `usage_cmd` pointing at `tests/fake_usage_cmd.py` and a W42 row that exists only in the copy. Long paths are trimmed.

```
--- no line
jobs check: 42 rows, 1 problems
jobs: W42: report: no "Usage: <n> tool calls; models: <m1>, <m2>; <free text>" line (from W42 on; `python3 wsc.py jobs usage W42 --write` writes it)
--- the command writes the line
$ wsc jobs usage W42 --write  (exit 0)
Usage: 42 tool calls; models: opus; 2 sessions, fake reader for W42 in core-copy
jobs usage: wrote jobs/W42/report.md
jobs check: 42 rows, ok
--- --from-json replaces it
Usage: 90 tool calls; models: opus; 1 session, by hand
--- does not parse
jobs: W42: report: "Usage: lots" does not parse: the shape is "Usage: <n> tool calls; models: <m1>, <m2>; <free text>" (from W42 on; `python3 wsc.py jobs usage W42 --write` writes it)
--- over 1.25 x
jobs: W42: report: usage 126 tool calls is over 1.25 x the budget 100: correct the line, or add a budget_lifts entry to the row
--- a lift clears it
jobs check: 42 rows, ok
--- a broken chain
jobs: W42: report: budget_lifts[0]: from 90 is not the brief's budget 100
--- another model
jobs: W42: report: usage model sonnet is not the row's model opus: correct the line, or the row if it was wrong
--- the card (wsc jobs view --offline --no-open --out <temp>)
<p class="meta">phase 1 · opus · no PC · depends on <span class="muted">none</span></p>
<p class="usage over">usage 126 / 100 calls · opus</p>
```

`wsc jobs check` on the real queue is unchanged: the `jobs` gate says `41 jobs rows, queue ok` at `usage_from = 42`, and the rule has no row to read at that number.

**This job's own line.** It was written with `wsc jobs usage W31 --write --from-json <file>`. The numbers are hand-supplied: I counted this session's tool calls, and no reader measured them. With `usage_from = 31` in a throwaway copy, `jobs check` reports only W33, W37 and W38 (done rows with no line) and nothing for W31. That run had the W31 row at status review with this report in place.

**Only unit-tested:** a real `usage_cmd` against napoleon's transcripts, which is the follow-up row, and the page in a browser (the card HTML was read, not rendered).

## Deviations from the brief, and why
1. **The docs are in a new `docs/USAGE.md`, not `docs/CONSUMING.md`.** CONSUMING.md stood at 30,353 of the 30,720 bytes the `doc_size` gate allows, and other jobs in flight also write there. It gets a one-line link and stays at 30,507 bytes; the README's doc table has a row for the new file.
2. **`usage_from = 42`, not 40.** The brief allows W40, but W40 is being built now from a brief that predates this rule, and W41 got a row on `main` during this job. Either number would fail those reports on their next merge of `main`. W42 is the first number with no row. The proof ran again at 42 after that merge.
3. **`jobs next` and `jobs fix` steps name the line (not in the brief).** `build_steps` and `fix_steps` add the `jobs usage` command for a job under the rule. `jobs check` catches a missing line, but it cannot see a stale one, and a fix round would otherwise leave the fix session out of the count. `usage_step` and two test cases; nothing changes below `usage_from`.
4. **`Result.cards` values.** The brief says "escaped text, or HTML by the rule of `Result.html`" and does not say how a value picks one. A string is escaped, and `{'html': '...'}` is drawn as is, so plain text is safe by default.
5. **One fixture script.** `tests/fake_usage_cmd.py` serves both the tests and the proof, in place of a script written by each test (step 2) and another under `tests/` (step 4).
6. **`jobs` now has a positional `job` argument**, which `usage` needs. Without a guard `jobs next W31` would have ignored the id and claimed some other job, so every other action refuses it and names `--id` (`test_only_usage_takes_a_bare_id`).
7. **The free text is required.** Decision 1 calls the shape exact, so `Usage: 12 tool calls; models: opus` does not parse. `wsc jobs usage` always writes the session count, so its line always has one.

## Open questions
The brief's four, each following its recommendation: over-budget and model mismatch are errors; cost stays free text; review rounds do not count; `usage_from` is set in this job, because this report passes its own rule.

New ones for the reviewer or Liam:
1. **A job in review shows no chip until it merges.** `card()` reads the working tree, and a job's report is on its branch until then. The row's `budget_lifts` on the branch are not read either. Reading the report from the branch needs one more `cat-file` per job in `branch_rows`; I left it out as outside the brief.
2. **The model rule and side requests.** A session that also makes small requests on a smaller model has two models in its transcript. The rule would fail that line, so the game's command must leave them out; B104 and `docs/USAGE.md` say so. If napoleon wants them shown, the rule needs a way to allow them.
3. **`jobs next` reads the working tree's rows.** In this session's first run the worktree sat at f1dbb13, so `jobs next --id W31` refused with `W31 (needs_brief): in progress on brief/W31`, although `origin/main` already had the brief. A fast-forward fixed it. Reading rows from the fetched `origin/main` would stop that, as a small backlog row; I did not add one here.

## What Liam must do
Nothing in the core. For napoleon, B104 needs a `needs_brief` row in napoleon-remastered: `usage_reader.py --job <id> --json` for build and fix sessions only, `[jobs] usage_cmd` and `usage_from`, its CLAUDE.md line, and the Opus override as a D line.

## Fix round 1
Session 9756d055-2ef5-4875-acd0-8bbbd0980fac, 2026-11-05, on `origin/main` b8ecfb7. Every blocker and should-fix item from round 1 is addressed.

### Blockers
1. **C35 taken, the branch does not merge (0133efa, fbdfce1).** Merged `origin/main`. Main's C35 to C38 stay and this job's row is C39, which none of the three open `plan/` branches uses. The backlog row is B104, after main's B90 to B95: B88 and B89 are pull request 114's, B96 to B101 are 119's, B102 and B103 are 121's. Every "B88" in this report became B104. The review asked for that, so this is the one edit to earlier sections besides the Usage line.
2. **`registries/tools.jsonl` (0133efa).** One row each: `wsc.jobs` keeps this job's `jobs usage` text and `wsc.policy` keeps main's `--scan` text. `wsc reg add tools` was rerun for both, and the `jobs.py` header already held main's text and this job's.
3. **`docs/CONSUMING.md` over the cap (f08257c).** 30,713 of 30,720 bytes, read from the merged tree. The view page's CSP detail and the "new marked version" sentence went, because `warscape/jobq.py` owns both (the `MARKED_URL` comment, the CSP docstring), and the usage link line is shorter. Every key name stays on that line. Only 7 bytes are free, so the next job to write here has to make room.

### Should-fix
1. **`usage_record` took a model id (9e8ee38).** A model whose family is not in `S.models` is now a `ValueError` naming the value, with two cases in `Record.test_a_bad_record_is_refused`. `UsageProblems.test_a_record_the_verb_takes_is_a_line_the_rule_takes` covers the round trip. Beyond the review: `docs/USAGE.md` and B104 now say a reader maps ids to family names, because napoleon's reader keys by model name. Red with the check disabled: `test_a_bad_record_is_refused`.
2. **The backslash trap (0dbd030).** `load_config` refuses a backslash in `usage_cmd`, with a case in `Config.test_bad_values_are_refused`, and the sentence in `docs/USAGE.md` is gone. The new rule refused the `Verb` fixture on Windows, as its `sys.executable` path has backslashes, so the fixture now writes `as_posix()` paths. Red with the guard disabled: `test_bad_values_are_refused`.
3. **The Usage line (this commit).** Rewritten with `wsc jobs usage W31 --write --from-json <file>`. The numbers are by hand, and no reader measured them: 87 for the build (the review's transcript count, not the build's own 85) and about 49 for this session, counted before its last calls.

### Later
B102 and B103 are the reviewer's, on `plan/w31-review-later` (pull request 121). This round did not touch them.

### Checks
- `python3 wsc.py gates` at 0dbd030 on 2026-11-05: 15 ok, 1 warn, 0 failed; 1137 host tests passed, 5 skipped (a POSIX sh with symlinks for one, capstone for four).
- `python3 wsc.py policy --branch job/W31 --base origin/main`: refused only for the missing merge verdict and the `done` row.
- `main` was red on `proxy` at the review (run 42066067742). I did not look at that run again, so the merge round still has to see it cleared or rerun.

The worktree `W31-build` still has `job/W31` checked out at e12011e, so this round was built on a local branch and pushed to `job/W31`.

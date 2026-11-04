# W31: Usage accounting in reports: a Usage line, wsc jobs usage, budget lifts, per-card usage

Model: Opus, reason: napoleon D52 (builds run on Opus). The job changes the report and row contracts every game's queue checks (`jobq.py` `problems`, the
jobs schema) and adds a hook that runs a game's command; a wrong rule blocks every game's `jobs check`, so it needs the careful model. Budget about 150 tool calls:
about 35 for the pure library and its red tests, 35 for the `jobs check` rules and schema, 30 for the verb and the game hook, 20 for B50 (cards on the view),
30 for docs, gates and CI round trips. At the cap, stop, commit, and report what is left.
Semver: minor

## Goal
Audit 2026-11-03 (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`, finding R3, "Automation opportunities" 7, plan item 14) found that usage is
asked for and never measured: `brief_problems` checks that a call budget and a kill criterion exist, 0 of 52 napoleon reports carry a usage line, budgets
were lifted mid-job in J9, J10 and J40 in prose only, and napoleon's `tools/usage_reader.py` reads the transcripts but compares nothing with the budget.
After this job, for a game that switches it on:
1. **A report states its usage.** `Usage:` line in `report.md`, checked by `wsc jobs check`.
2. **`wsc jobs usage <id>`** fills that line from the game's own usage source through a command the game names in `wsc.toml` (the core reads no transcripts).
3. **Over budget and wrong model are flagged**: usage above 1.25 times the brief's budget, or a model other than the row's.
4. **A budget lift is a row field**, `budget_lifts` (date, from, to, why), not prose.
5. **B50, folded in:** a per-card usage line in `wsc jobs view`.

## What exists (read before building; citations checked 2026-11-04 against `origin/main` f1dbb13)
- **`warscape/jobq.py`:** `brief_problems` (:107, the `Budget about <n> tool calls` regex is the one to reuse: factor it into `brief_budget(text)`), `report_problems`
  (:166, no row argument today), `problems` (:273, the loop that calls both; every message is an error, there is no warn channel in `problems`), `semver_rule`
  (the model for a `*_from` switch: `[jobs] semver_from`, `repo.py` `DEFAULTS['jobs']`, validated near `repo.py:188`), `render_view`/`card()` (:968, :999) and
  `panel_html` (:959).
- **`warscape/gates.py`:** `Result` (:22; `html` is the one field a `view` module may add). `warscape/gatemods.py` runs the `view` stage (`run_stage(ctx, 'view', rows=rows)`).
- **`warscape/verbs/jobs.py`:** the action chain (`check`, `next`, `review`, `fix`, `view`, `worktrees`) and its header (`usage:` and `when:` lines and the `tools` row move with a new action).
- **`schemas/jobs.schema.json`** (`additionalProperties: false`: `budget_lifts` needs the schema; `x-view` columns).
- **`docs/BACKLOG.md` B50** (the per-card line, "build it once napoleon wants per-card usage": J49's open question) and **B87** (the form of a napoleon follow-up row).
- **The game side** (napoleon-remastered, read-only here): `tools/usage_reader.py` (`usage_by_session`, `branch_trailers`, `usage_by_job(rows, sessions, trailers)` ->
  `{'jobs': {id: {sessions, routes, calls, models, cost, first, last, wall_s}}}`; `models` is `{model: [in, out, cache_read, cache_write]}`; `routes` names build,
  review, fix, brief; it already has `budget_from_brief`), and its decision D52 (2026-11-04: builds on Opus, reviews and briefs on Sonnet).
- **`jobs/W26/report.md`** (the claim and the `*_from`/`pc_state` key pattern), **`jobs/W29/brief.md`** (the shape of a core brief and of a `semver` rule).

## Decisions already made (follow them; a deviation goes in the report with its reason)
1. **The Usage line.** One line in `report.md`, directly under the title paragraph, exactly this shape (the first thing a reader sees, and one regex):
   `Usage: <n> tool calls; models: <m1>, <m2>; <free text: sessions, cost estimate, source, date>`
   `n` is an integer, models are lower-case family names (`opus`, `sonnet`, `haiku`), compared with the row's `model` by their first word. The free text is for humans.
   The numbers are those of the **build and fix sessions** of the job, not its reviews and not the brief (D52 puts reviews on Sonnet; a review on Sonnet is not a mismatch). The game's command decides which sessions those are (decision 3).
2. **Switch and numbers.** `[jobs] usage_from = <n>` (default 0 = off, like `semver_from`): from job number `n` on, a report with status `review`, `fix` or `done`
   needs the line. A game sets it to the first job whose brief predates nothing it cannot satisfy; the core's own `wsc.toml` sets it to the first job after this one
   merges (the number the report states; W40, the `semver_from`, is fine). Older reports are exempt, never edited.
3. **The hook is a command, not Python.** `[jobs] usage_cmd = "<argv template>"` in the game's `wsc.toml`, with `{id}` replaced by the job id, run with the repo root as
   cwd, no shell, a 60 s timeout. It prints one JSON object on stdout: `{"calls": int, "models": ["opus"], "sessions": int, "note": "text"}` and exits 0; anything else
   (non-zero, bad JSON, missing keys, timeout, empty `usage_cmd`) is `wsc jobs usage` exit 1 with the reason and writes nothing. Nothing about transcripts, paths or
   Claude Code's format enters the core. Napoleon's `tools/usage_reader.py` gains a `--job <id> --json` mode (a napoleon follow-up row, decision 9, not part of this job).
4. **`wsc jobs usage <id> [--write] [--from-json FILE]`.** Prints the line the command produced (or the one `--from-json` holds: the tests' seam and a hand route).
   `--write` replaces an existing `Usage:` line in `jobs/<id>/report.md` or inserts one after the first paragraph under the `# <id> report` heading; it changes nothing else
   in the file and refuses a report that is missing. It never runs a game or touches anything outside the repo; the command is the game's, exactly like the gate modules.
5. **The checks (`jobs check`, from `usage_from` on, in `problems` through a new `usage_problems(jid, row, brief, report)` that is pure):**
   - no `Usage:` line, or one that does not parse: error with the shape in the message;
   - `calls` > 1.25 x the **effective budget**: error naming both numbers. Effective budget = `to` of the newest `budget_lifts` entry, else the brief's `Budget about <n> tool calls`;
   - a model in the line other than the row's `model`: error naming both (the fix is in the report, or the row if the row was wrong; the Opus override of D52 is a decision row, not a flag);
   - a `budget_lifts` entry with `to` <= `from`, a `from` that is not the previous `to` (or the brief's budget for the first), or a missing `why`: error; the schema handles shape.
   No warn channel exists in `problems`; errors are right because the reviewer clears them with a lift entry or a corrected line, and the check runs on the job branch.
6. **`budget_lifts` on the row.** An optional array of `{date (YYYY-MM-DD), from (int), to (int), why (non-empty string)}`, `additionalProperties: false`. A lift is added by the
   session that raises the budget (`wsc reg set` takes JSON? check how `reg set` writes arrays and use it; if it cannot, add the narrowest `reg` support and test it, or document the JSONL edit plus `reg render`).
   A lift never edits the brief (the brief is the contract as written; the row is the history).
7. **B50, per-card lines.** (a) `Result.cards: dict = field(default_factory=dict)` (job id -> escaped text, or HTML by the rule of `Result.html`); `render_view` collects them from the
   `view`-stage results and `card()` draws a line under `.meta`. (b) The core draws its own usage chip from the report's `Usage:` line, no game code: `usage 142 / 150 calls · opus`
   (budget lift applied), red class when over 1.25 x. Missing Result `cards` or a malformed one never fails the page. Remove B50 from `docs/BACKLOG.md` (a done row leaves it).
8. **No new dependency, no network, no reading of `~/.claude`.** Standard library only. The core never opens a transcript.
9. **Napoleon's follow-up** (a `needs_brief` row for napoleon-remastered, named in the report, B87's form): `usage_reader.py --job <id> --json` printing decision 3's object for build and fix
   sessions only; `wsc.toml` `[jobs] usage_cmd` and `usage_from`; its CLAUDE.md line; the Opus override recorded as a D line (the audit's other half of R3, a Liam item).

## Scope: files this job touches
`warscape/jobq.py` (`brief_budget`, `parse_usage`, `usage_problems`, `effective_budget`, `problems`, `card()`, `render_view`), `warscape/repo.py` (`DEFAULTS['jobs']`:
`usage_from`, `usage_cmd`, with the same validation style as `semver_from`), `warscape/gates.py` (`Result.cards`), `warscape/gatemods.py` (collect `cards`),
`warscape/verbs/jobs.py` (the `usage` action, `HELP`, header lines), `schemas/jobs.schema.json` (`budget_lifts`), `wsc.toml` (`usage_from` left 0 until this merges is fine;
say which in the report), `tests/test_usage.py` (new), `tests/test_jobs.py`, the fixture game under `tests/` if the existing `test_fixture_game` is where a `jobs` run is exercised,
`registries/tools.jsonl` only if a tool header changes, `docs/CONSUMING.md` ("The job pipeline": the Usage line, the two keys, the command's JSON, `budget_lifts`, the cards field),
`docs/DECISIONS.md` (the next free C number; read `main` for it before writing), `docs/BACKLOG.md` (remove B50, add the napoleon follow-up as a B row if it fits the file's form),
`jobs/W31/report.md`. **Not** `VERSION` (the release workflow owns it, C27; the Semver line is the level), not `registries/jobs/` other than W31's own row, not a game's files.

## Steps
1. Read "What exists". `python3 wsc.py gates --fast` once for a baseline. Fetch `origin/main` and re-check that `jobq.py` has not moved under the line numbers above.
2. **Failing tests first**, committed red (`tests/test_usage.py`, pure inputs, plus the cases in `tests/test_jobs.py`):
   - `parse_usage`: the exact shape, extra spaces, no models part (error), non-integer, two `Usage:` lines (error), `Usage:` inside a code fence (ignored);
   - `usage_problems`: off below `usage_from`; missing line; at 1.25 x passes, one above fails; a lift raises the ceiling; a lift with `to` <= `from`; a chain break; model mismatch,
     `Opus` vs `opus`, a two-model line where one differs; a `needs_brief`/`queued` row is not checked (no report yet);
   - `problems` integration: a report-less review row, a done row below `usage_from` untouched;
   - the verb with a fake `usage_cmd` (a tiny script written by the test, `sys.executable`): ok, non-zero exit, bad JSON, missing key, timeout (use a short injected timeout), `--write` insert,
     `--write` replace (every other byte of the report unchanged), `--write` on a missing report, `--from-json`;
   - schema: a valid `budget_lifts`, a lift with an unknown key, a bad date, an empty `why`;
   - `Result(cards=...)`: drawn on the right card, escaped, a card for an unknown id ignored, a non-dict ignored; the usage chip text for within, over, missing.
3. Build in this order, one commit each, tests green at each: library functions and `repo.py` keys, then `problems` and the schema, then the verb, then `cards` and the chip, then docs.
4. **Proof the builder can make without a game:** run the verb against the core's own repo with a fixture command (a script under `tests/`) and `--from-json`, and `wsc jobs check` on a
   temporary copy of the registries with `usage_from` set low (paste the output: ok, then each failure message once). Run `wsc jobs view --out <temp path> --no-open` and read the card HTML for a report with a Usage line.
   State what could only be unit-tested (a real `usage_cmd` against napoleon's transcripts: that is the follow-up row).
5. Docs, `python3 wsc.py gates` (full), `python3 wsc.py policy --branch job/W31 --base origin/main`.

## Tests and acceptance
- New host tests red first (the run id of the red CI run), then green; `python3 wsc.py gates` green; the branch's final CI run id.
- Fixtures that must go red (apply one at a time as working-tree mutations, restore, list in the report like W26's table): the ceiling at 1.5 x, the ceiling ignoring lifts, model compared
  case-sensitively, `--write` appending a second line, `usage_from` ignored, a failing command still writing.
- `wsc jobs check` on the core's own queue is unchanged with `usage_from = 0`.
- Acceptance for the reviewer: the Usage line of this job's own report, produced with `wsc jobs usage W31 --write --from-json <file>` (the numbers hand-supplied from the session, stated as such), parses and passes the rule.

## Kill criteria
- The rule would fail any report already on `main` for a game that has not set `usage_from`, or `wsc jobs check` on the core's own queue changes with the default: stop and fix.
- The core reads a transcript, a `~/.claude` path or any file outside the repo (the command is the only seam): stop.
- `problems` needs a warn channel to be usable (reviewers would be blocked by a correct report): stop, report, ask Liam; do not downgrade a rule silently.
- A change to `render_view` breaks an existing view test and the fix is not local: stop and report.
- Core CI red after three fix attempts for a cause in this change, or about 150 calls: stop and report.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **Error or warning for over-budget and model mismatch?** Recommended: error (decision 5): the reviewer clears it with a lift entry or a corrected line; a warning is what the audit found nobody reads.
2. **Should cost (USD) be a field?** Recommended: no; free text in the line. The estimate includes side requests and is not a bill (napoleon J49).
3. **Count review rounds against the budget?** Recommended: no; the budget is the build's, reviews are on Sonnet by D52 and have their own sessions.
4. **`usage_from` for the core's own queue.** Recommended: set it in `wsc.toml` in this job only if the report passes its own rule (acceptance above); otherwise leave 0 and say so.

## Finish
Report in `jobs/W31/report.md` (what was built per decision, tests red then green and where they ran, the fixture table, the proof outputs, deviations, open questions, the napoleon follow-up
row and what Liam must do), with its own `Usage:` line, then `wsc reg set jobs W31 status=review report=jobs/W31/report.md` (`python3 wsc.py`).
Push `job/W31`, open the draft pull request, and stop: an independent reviewer merges (C18); the release workflow tags (C27).

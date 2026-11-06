# W32: Brief questions as proposals, and trigger paths on later rows

Phase 1 (the pipeline). The 2026-11-03 audit (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`, R4, R9, automation 4) found two leaks: open questions wait on Liam with no default, and
`later` items are forgotten when a job walks past them. C41 moved most of the first fix elsewhere: `later` rows are W43's and the Waiting on Liam lane is W45's. Two things stay here. A brief's open
questions become W45 proposals of kind `question`, so they reach Liam through the same table and the same `decide/` branch as audit findings, and the ones past their date can be applied in one merge.
And a `later` row can name the paths it cares about, so `policy` says so when a branch touches one.

Model: Opus, reason: C261106-bcaa puts every core job on Opus, and this job changes the guard on the owner's answers (the row said Sonnet; this brief's branch sets it to opus).
Budget about 140 tool calls: about 15 reading, 25 for fixtures and red tests, 55 to build, 15 for the dry run, 30 for docs, gates and the report. Comparables by their `Usage:` lines: W31 136, W43 115, W44 130; W45 was 240 with three fix rounds, on a new guard, and this job extends that guard rather than writing one.
Semver: minor
This row is below `[jobs] semver_from`, so `policy` will not stop you editing `VERSION`: leave it anyway, the release workflow reads the row's level (C27; W31 had the same standing).
No DLL or harness input changes: schemas, `warscape/` library code, the `proposals` and `jobs` verbs, `wsc.toml`, tests and docs. A game's pin bump to this tag carries no acceptance run for it (napoleon rule 79). No workflow file changes.
Subagents: none. No PC.

## Start
1. `git pull`; `python3 wsc.py jobs next --id W32` and follow its mechanics. If this session's model is not Opus, stop and say so.
2. `python3 wsc.py gates --fast` for a baseline; `python3 wsc.py find proposal`, `python3 wsc.py find later` (reuse before you write).
3. Read `docs/PROPOSALS.md` whole, C41 and C261106-bcaa (`registries/decisions/`), the rows of W47, W124, W125, W126 and W130, and `jobs/W45/report.md` from "Open questions" on, including "The routes".

## Target facts (check each again before relying on it)
- `schemas/proposals.schema.json` already has `kind: question`, which needs no `finding` or `baseline`. `additionalProperties` is false on both schemas, so every new field is a schema change.
- **A question row must never carry `finding`.** `overlay` in `warscape/proposals.py` reads `r['baseline']` of any row with a `finding` once it is applied, so such a row crashes `wsc audit`. `check` and the `live` count read `finding` too.
- `proposal_row_problems` in `warscape/policy.py` already lets a `kind: question` row with no `finding` skip the class rule, and `auto_refusal` turns down every row that is not a finding. So `auto_apply` can never take a question. Keep it so: `[audit] auto_apply` stays empty (W130).
- `FILLED` in `warscape/policy.py` lists what `plan/` and `decide/` may change on an existing row. A field not in it is frozen once drafted, which is what the new fields want.
- `decide_answer_problems` refuses an `answer.by` that is not the owner. `apply_rows` already writes one decision row naming each accepted row, and takes `by` and `who` as arguments. It adds no decision row for `defer` or `none` options.
- `check` in `warscape/policy.py` has `base_rows`, `changed` and `warns` on every branch kind, so the trigger warning needs no new argument to the judge child, and `JUDGE_API` stays 1. New settings go through `settings()`.
- `repo.matches` is the glob rule (`*` and `?` inside a segment, `**` across folders).
- `scan_rule` in `warscape/policy.py` gives None to a line with no known mark, so a new warning does not join a rule's tally in `wsc policy --scan`. Confirm `scan_tally` copes with it.
- `gate_jobs` in `warscape/gates.py` turns `warns` from `jobq.check` into a `warn` result. `jobq.check` also returns `summaries`, which only the verb prints.
- `ask` sorts by `baseline.severity`, and a row with no baseline sorts last, so at `[audit] max_questions` findings would crowd out every question.
- `unfenced` in `warscape/jobq.py` skips code fences. Check for an import cycle before choosing the parser's module: `proposals.py` imports `policy.py`, and the `jobs` verb imports `proposals` inside a function.
- The shape in the wild varies: `recommended:` or `Recommended:`, `tag: risk` or `Tag: taste`, text after the date, and some items carry both a date and a tag (`jobs/W94/brief.md`, `jobs/W41/report.md`, `jobs/W45/report.md`). Most old items have `recommended:` and no date.
- `job/W32` may change only its own jobs row and, by the guard, no proposal row. So this job can neither fill `trigger_paths` on other rows nor commit the first question rows.
- `docs/CONSUMING.md` sits at the `doc_size` cap: anything added there is paid for with a cut. `docs/CONSUMING_OPTIONS.md` has room.
- The Windows `tests` gate is close to `[tests] timeout_s` (W139). A judge test costs seconds each.
- This session's guard may refuse compound shell commands: one git or python call per command.

## Decisions already made for this job
1. **The shape of a question.** An item of a `## Open questions` section (numbered or bulleted, wrapped lines included, code fences skipped) with `recommended: <answer>` and either `default after: <YYYY-MM-DD>`, a `tag: taste|risk|legal`, or both, in any case. The answer ends at `; default after:`, `; tag:` or the end of the item. An item with a tag is never due, whatever date it also has.
2. **The row.** `draft --questions` writes `kind: question`, `class: brief_question`, `question` (the item's text before `recommended:`), `tag`, and two new fields: `default_after` (date) and `source` (`{path, key}`: the file read, and the first 12 hex of the sha256 of the item's text with its whitespace collapsed). Both are frozen by not being in `FILLED`. `options` are two: `recommended` (kind `decision`, the recipe's `decision` naming the job and the answer, `reversible: yes`) and `defer` (kind `defer`). `recommended` is the key `recommended`. The verb fills the row: no skeleton, no session needed.
3. **One source per job.** Rows are drafted from a job's `report.md` when it is on the tree, else from its `brief.md`, because a report's questions are the state of the world and its text often restates the brief's. Only items of decision 1's shape are drafted, so old questions with no date and no tag stay out.
4. **`wsc proposals draft --questions`, not `jobs check`, writes rows:** a check that writes cannot run in a gate. It runs on a `plan/` branch. It adds a row for each item with no row on its `source.key`, whatever that row's status, and closes as `gone` an open untagged question row whose item has left its job's source, printing each. A tagged one stays open and is printed. Nothing else changes.
5. **Due.** A row is due when it is `kind: question`, `open`, has no `tag`, and today (UTC, `today_utc`) is after `default_after`, strictly. `ask` lists due rows first.
6. **A date never fails a gate.** `jobs check` prints the due rows on stdout, one line each, with the command to apply them, and a count in its summary. Its exit code and the `jobs` gate's status do not depend on today: a date passing must not turn main red or put a warning on every branch. `proposals check` reads no clock.
7. **`wsc proposals answer --due`** on `decide/<date>` accepts every due row at its recommendation, alone or with `--answers` and `--quote` (rows named there win). `--quote` is not needed with `--due` alone. Due rows get `answer.by` `default_after`, and their own decision row, `who` saying they defaulted and the owner merged. The `ANSWERS_` file lists them in a section of their own, saying no message was given for them: it never quotes the owner for a row the owner did not answer. Only the owner merges, as for any `decide/` branch: nothing here queues the merge.
8. **The guard.** `decide_answer_problems` takes `answer.by` `default_after` only on a `kind: question` row with no tag, `answer.option` its `recommended`, and `answer.date` after its `default_after`. `AUTO_BY` is the model for the constant. Every other rule on `decide/` stands.
9. **`proposals check` adds:** a question row has `source`, and `default_after` or a `tag`, and no `finding`, `metric` or `baseline`; `class` is `brief_question`; a finding row has no `default_after` or `source`; `source.path` exists; two live rows on one `source.key` are refused, as two live rows on one finding are; `answer.by` `default_after` holds decision 8 here too, by one shared function, as `auto_refusal` is shared.
10. **The brief rule.** `[jobs] question_shape` (default false, the core's `wsc.toml` true, typed in `repo.py` as `usage_from` is): `jobs check` refuses a `queued` row's brief with an open-questions item that has no `recommended:`, or neither a date nor a tag. Status decides, not a job number: a promoted `later` row keeps its low id. A section that says there are none passes.
11. **`trigger_paths`** on `schemas/jobs.schema.json`: a list of at least one glob, read on `later` rows only, set with `wsc reg set jobs <id> trigger_paths:='[...]'`. In `policy`, on every branch kind but `release/`, each `later` row **of the base** with a path in `changed` matching one of its globs gives one warning: the row's id, its title, up to three paths, and "read the row: do it here only if the brief allows, else leave it". A warning never refuses. Reading the base's rows means a branch cannot silence it by editing the row.

## Deliverables
1. The schema changes (decisions 2 and 11), and `warscape/policy.py`'s docstring.
2. The parser, one function, used by `draft --questions` and by decision 10.
3. `draft --questions`, `answer --due`, the `ask` order, the verb's header and `HELP`, and its tools row (`python3 wsc.py reg add tools warscape/verbs/proposals.py`, and `warscape/verbs/jobs.py` if its text changes).
4. The due list in `jobs check` (decision 6), with nothing when the repo has no proposals registry.
5. The guard and `check` (decisions 8 and 9), and `[jobs] question_shape` (decision 10).
6. The trigger warning (decision 11).
7. Host tests, red first, in `tests/test_proposals.py`, `tests/test_jobs.py` and `tests/test_policy.py`, pure logic wherever a call can be made directly. At most three new cases in `tests/test_proposals_judge.py`, each through the real judge: a tagged row answered by `default_after` is refused; a row not yet past its date is refused; the same diff with `by` the owner and no quote in the file is refused. Must exist: the parser on the wild shapes above and inside a fence; a re-run drafts nothing; a row whose text changed is closed and redrafted; the last day is not due and the next is; with the clock past every date, `gates`' `jobs` result and `jobs check`'s exit code are unchanged; `wsc audit` runs over accepted question rows; `answer --auto` leaves a question open with its class listed; a trigger on the base fires though the head removed it; a `later` row added by the branch does not fire; a row that is not `later` does not fire.
8. A mutation check on the guard and on `due`, as W45 did: say how many were killed.
9. **The dry run**, in a throwaway clone inside your ignored `_scratch/`, its `origin/main` moved to your head (a `decide/` branch is judged with the base's rules, W45's report shows how): `draft --questions` over the real `jobs/`, `proposals check`, `ask`, `jobs check` showing due rows, `answer --due` on `decide/<date>`, `policy` ok there, the same diff refused on `plan/`, and a `later` row with `trigger_paths` warned on. Delete the clone. Commit no proposal row.
10. Docs: `docs/PROPOSALS.md` owns the shape, the fields, due and the round. Add one line in `docs/REVIEW.md` "Later items" saying a `later` row should name `trigger_paths` when its paths are known, and that a reviewer reads the warning. Keys go in `docs/CONSUMING_OPTIONS.md`, a section in `docs/UPGRADING.md` says a game opts in and needs nothing at its bump, and `docs/AUDIT_METRICS.md`'s "no rule: W32" becomes "no rule", as C41 left this job no such rule.
11. One decision row (`python3 wsc.py reg add decisions --mint who=... decision=... reversible=yes`) naming W32 (rule F): a date never fails a gate, a default is applied only by the owner's merge and says so, and `trigger_paths` warns.

## Out of scope
- Filling `trigger_paths` on existing rows, and committing the first question rows: `job/` cannot, so both are `plan/` follow-ups your report spells out, with the commands.
- Anything that starts a `decide/` branch by itself, or a tick for it (W46, W47). `draft --max` for findings (W47). `[audit] auto_apply` and everything in W130. W124, W125 and W126, though you read them; a close on no evidence stays as it is.
- Questions in `review.md`, and a shape rule on reports. Rewriting old briefs or reports. The napoleon side: nothing changes there until it opts in.
- A stale `trigger_paths` check: a rename on a job branch could not fix another row, so a gate on it would trap that job.
- `docs/AUDIT_METRICS.md`'s `later` marker count stays a count.

## Open questions
1. The row says a brief's questions; decision 3 also reads reports, because W45's and W41's carry the live ones in this very shape. Is that right? recommended: yes, one source per job, the report once it is on the tree; default after: 2026-11-13.
2. Liam's answer may be neither option: the `answer` verb only picks a key, and W126 will stop a `decide/` branch rewriting `options`. Is the route a `plan/` branch that adds the option first, then the `decide/` branch? recommended: yes, said in `docs/PROPOSALS.md`, no code; default after: 2026-11-13.
3. Should a new `later` row have to carry `trigger_paths`? recommended: no, optional, as many `later` rows have no path yet; default after: 2026-11-20.
4. A default still needs Liam's merge, because only he merges `decide/` (C41), so "default after" means "applied in bulk with one merge", not "applied without him". Should due rows ever apply with no merge of his? recommended: no, the approval stays his, and one merge is cheap; tag: risk.

## Kill criteria
- The guard of decision 8 cannot be judged without a required new argument to the `--judge` child: stop and report, a `JUDGE_API` break is Liam's call.
- `python3 wsc.py audit --offline` at the merge base and at the head differ on any finding or metric: stop and report the difference.
- `draft --questions` in the dry run makes more than 25 rows: stop, report the list, and do not tune the shape to fit, as the source rule may be wrong.
- The dry run's `policy` line does not say ok on `decide/<date>`, or is not refused on `plan/`, after 10 calls: stop and report both outputs.
- The Windows `tests` gate times out on CI against `[tests] timeout_s`: slim the fixtures and report the run; do not raise the limit (W139 owns it).
- Over about 140 tool calls: stop, commit, report what is left.

## Finish
Report in `jobs/W32/report.md` with `## What was built`, `## Evidence` (tests red then green, the branch's CI run id, the mutation count, the dry run's output, what the tests add to the Windows run), `## Deviations from the brief and why`, `## Open questions`, and two follow-ups written as commands: the `plan/` branch that drafts the first question rows, saying how many it will make and which are already due, and how to add `trigger_paths`, with a first batch of rows you judged worth it. Say which drafted questions look settled already, so the first round does not ask them again.
This row is below `[jobs] usage_from`, but give the report a `Usage:` line anyway, by hand: `python3 wsc.py jobs usage W32 --write --from-json <file>`, so this job counts as a comparable.
`wsc reg set jobs W32 status=review report=jobs/W32/report.md` (`python3 wsc.py`)
Push `job/W32`, open the draft pull request, and stop: an independent reviewer merges (C18); the release workflow tags (C27).

## Registry gaps
None.

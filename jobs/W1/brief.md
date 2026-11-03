# W1: Triage the core backlog into queue rows

Model: Sonnet. Budget about 45 tool calls; at the cap, stop and report what is done.

## What
Read `docs/BACKLOG.md` (every open item, B1 to B49; the numbers have gaps, triage the rows that exist), `docs/DECISIONS.md` (C18, C19) and the
`registries/jobs/` rows, and decide for each item what becomes of it. Write the decisions as one table in `jobs/W1/triage.md`: one line per open
item, in backlog order, with exactly one of three outcomes.
- **Row**: a proposed `jobs` row: title, description (one or two sentences a brief writer can start from), model (`sonnet`, or `opus` with a
  one-line reason; the rule is in `docs/CONSUMING.md`, "The job pipeline"), `needs_pc` (true when the work needs the game or a PC run), `depends_on`
  (ids of other proposed rows by their item number until ids exist, and existing rows such as W2), and `phase`. A row may cover one item or several.
- **Merged into B<n>**: the item is the same change as another (or a part of it); name the item that carries it. The carrying item's row says it covers both.
- **Stays a backlog note**: say why in one line (too vague to brief, waits on a game's evidence, low value, a decision rather than code).
Group items that touch the same file (for example the `capture.cpp` items B32 to B34, the `acceptance.py` items B26 and B31, the `pc_deploy.py` items
B39 and B42, the `core_pin` items B7, B11, B12) and order the rows so a dependency comes first. Do not invent ids: number the proposed rows P1, P2, ...
in the table; the follow-up assigns `W<n>` ids.

Then write `jobs/W1/report.md`: counts (rows proposed, merged, notes), the dependency order you chose, the judgement calls a reviewer should check,
and open questions. It starts `# W1 report: <title>` and has `## Deviations` and `## Open questions` sections (`jobs check` enforces them).

## Why the table, not the rows
A `job/W1` branch may change only row W1 of the jobs registry (`warscape/policy.py`), so it cannot add the rows this job exists to produce, and
`wsc reg add jobs` on it would be refused by CI's `policy` check. The deliverable is therefore the table. After the W1 review merges, a separate
`plan/` branch applies the table mechanically (a `plan/` branch may change `registries/jobs/*`): one `wsc reg add jobs` per proposed row, each
`needs_brief`. That follow-up is the orchestrator's, not part of W1: do not start it, do not write `plan/` branches.

## Must not
- No code, no tests, no `VERSION` change, no edits under `warscape/`, `proxy/`, `harness/`, `schemas/` or `tests/`.
- No new rows and no edit to any row but W1 (`wsc reg set jobs W1 ...` at the end is the only registry write). Do not run `wsc reg add jobs`.
- Do not edit `docs/BACKLOG.md`: removing a line is part of the job that builds the change, so the follow-up and later jobs do it, not the triage.
- Do not write briefs for the proposed rows; the description is a starting point only.
- Do not mark W1 `done`; the reviewer does.

## Kill criteria
- A backlog item cannot be understood from `docs/BACKLOG.md`, the decisions and the code it names after 3 tool calls: mark it "stays a backlog note:
  needs an owner's answer", list it under open questions, and move on.
- More than 15 proposed rows come out of the pass, or a proposed row needs a design decision the backlog line does not contain: stop and report
  with the table so far (the orchestrator will split the triage).
- Work starts on a code change or a row: stop, discard it, and report.

## Finish
Commit `jobs/W1/triage.md` and `jobs/W1/report.md` on `job/W1` (the commit trailer rule in `CLAUDE.md` applies). Report in `jobs/W1/report.md`, then
`wsc reg set jobs W1 status=review report=jobs/W1/report.md` (`python3 wsc.py`), and push.

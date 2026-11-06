# W132: The owner can grant one more review round

Phase 1 (the pipeline). A job blocked after 3 review rounds has no way forward in code, though `docs/REVIEW.md` says "The owner decides". `jobs check` refuses a fourth round
(`MAX_ROUNDS`, `warscape/jobq.py`), `jobs review` refuses to name one, and a reviewer who must fix a conflict cannot write `merge` (rule A). W45 round 3 is the case
(`jobs/W45/review.md` on `job/W45`: `merge after fixes`, with the reviewer's own commits `0bfc589` and `0ae0a89` unreviewed). Liam chose option A: one more fresh round, granted in the repo.

Model: Sonnet, reason: none needed (Sonnet is the default). Python in `jobq.py` and `policy.py` with host tests; no DLL, no PC, no `proxy/`. `needs_pc` stays false.
Budget about 70 tool calls: about 15 reading, 20 for the tests, 15 to build, 10 for docs and gates, 10 for the report and the pull request.
Semver: minor
Subagents: none; do the work in this session.

## Start
1. `git pull`; `python3 wsc.py jobs next --id W132` and follow its mechanics. If this session's model is not Sonnet, stop and say so.
2. Read `warscape/jobq.py` (`MAX_ROUNDS`, `BLOCKED_BY_ROUNDS`, `round_problems`, `round_status_problems`, `not_ready`, `review_steps`, `Branch`), `warscape/policy.py`
   (`decision_row_problems`, `decision_row_errors`, `check`, and the branch-kind dispatch), `schemas/decisions.schema.json`, `docs/REVIEW.md` "Rounds", and `jobs/W45/review.md` round 3 on `origin/job/W45`.

## Target facts (check each again before relying on it)
- The decisions registry is one minted row file per decision (`registries/decisions/C<yymmdd>-<hex>.json`, W43), append only, `additionalProperties: false` in its schema.
  `[policy] plan` and `[policy] meta` both list `registries/decisions/*`; `plan/` merges itself (C40), `meta/` waits for Liam. `decide/` is not a branch kind of main yet
  (W45 introduces it on `job/W45`), so the rule below names it only if the base's `policy.py` knows it.
- `policy` judges with the base's rules and reads the head only as data (C24), so a grant must be on the **base** (merged) to count; a branch that adds one is not helped by it.
- Round limits live only in `jobq.py` (`round_problems`, `round_status_problems`, `not_ready`, `review_steps`, and the audit's round count); `policy.py` has no limit of its own.

## Decisions already made for this job
1. **The grant is a decision row** with a new optional field `grants_round`: a job id (`W45`). One row grants one more round to that job; `n` rows naming it grant `n`.
   The limit for job `J` is `MAX_ROUNDS + (rows of the decisions registry on the base that name J)`. Add the property to `schemas/decisions.schema.json`
   (pattern `^[A-Z][1-9][0-9]*$`); `wsc reg add decisions --mint who=... decision=... reversible=... grants_round=W45` must work (check how `reg add` takes fields).
2. **Only a branch Liam merges may add such a row.** `policy` refuses an added decision row with `grants_round` on every branch kind except `meta/` (and `decide/`, if the base knows
   that kind). In particular it is refused on `plan/*`, `brief/*`, `release/*` and every `job/*`, including the granted job's own branch. The error names the fix ("a `meta/` branch,
   which only the owner merges"). The row must also name a job whose row exists on the base with status `blocked` and `blocked_by` the rounds reason (a grant for a running or done job is refused).
3. **The limit follows the grant everywhere**: replace the constant by one function `max_rounds(jid, grants)` that `round_problems`, `round_status_problems`, `not_ready`, `review_steps`,
   the `jobs view` card and `audit` use; `grants` is read from the decisions registry of main (the base), not from the branch. With no row the behaviour is byte-identical to today
   (every existing test passes unchanged).
4. **The flow after a grant is the ordinary one.** Round 3 (non-merge) with a grant: the row is `fix` or `review` as for rounds 1 and 2 (a fix session appends `## Fix round 3`, then sets `review`);
   round 4 is a fresh session, `review_steps` says "round 4 is the last" when no more grants remain and the blocked row text uses the granted limit. The blocked row from before the grant
   (`status=blocked`, `blocked_by` the rounds reason) is moved by the job's own branch to `fix` or `review`; `round_status_problems` accepts that once the grant is on the base.
   Without a grant `blocked` stays the only valid state after round 3, as today.
5. **Test through the real judge**, not only the pure function: a host test that builds a throwaway repo (the pattern of `tests/test_proposals_judge.py`) with real commits on real branch names and runs
   `python3 wsc.py policy --branch <b> --base origin/main` (parent and `--judge` child) for: a grant on `meta/x` (ok); on `plan/x`, `brief/W132`, `job/<granted id>` and `job/<other id>` (each refused);
   a grant for a job that is not blocked or not a row (refused); a changed grant row (refused by the append-only rule, not new); a job branch with a round 4 and a grant on its base (ok), and
   the same without a grant (refused by `jobs check`). The round-4 case uses W45-shaped files (review.md with three rounds, report.md with `## Fix round 3`).
6. **Docs, short**: `docs/REVIEW.md` "Rounds" (one paragraph: how the owner grants, with the exact `wsc reg add` command and `meta/` branch), `docs/CONSUMING.md` "The job pipeline" (one line; the `doc_size`
   gate is tight: CONSUMING.md was 30717 of 30720 bytes on the W45 merge tree, so make room by shortening an older line, not by raising the cap). A learning becomes code, so no prose beyond that.
7. Standard library only.

## Deliverables
1. `warscape/jobq.py` and `warscape/policy.py` as in decisions 1 to 4; `schemas/decisions.schema.json`; any `reg add` change needed for the field.
2. Host tests as in decision 5, plus unit tests for `max_rounds` (0, 1 and 2 grants; a grant for another job; a grant row with no job).
3. **Prove it red first**: run the new tests against the unchanged code and say what each printed.
4. Docs as in decision 6. Update tool registry rows only if a header changes.
5. A worked check on W45 as a dry run: in a throwaway clone, add a grant row for W45 on a `meta/` branch, and show `jobs review --id W45` naming a round 4 once the row says `review`. State plainly that the real grant row is Liam's to write and merge (`meta/`), and that this job does not write it.
6. `python3 wsc.py gates` (full) green, `git fetch` and the branch checked against the latest `origin/main` (merge-tree clean, `policy` ok) before review; cite the CI run id.

## Out of scope
- Writing the real W45 grant, merging anything on W45, or changing W45's row (Liam's call, a `meta/` pull request).
- Raising `MAX_ROUNDS`, a new branch kind, or letting any session grant itself rounds.
- W130 (what must hold before `auto_apply` is filled), W125 and the audit's proposals.

## Open questions
- Should the grant also be accepted from a `decide/` branch? recommended: yes, only if the base's `policy.py` already has that kind when this job builds (W45 may not be merged yet); otherwise `meta/` only, and W45 adds `decide/` to the rule in its own review; default after: 2026-11-20.
- Should a grant row carry a reason field? recommended: no, the `decision` text is the reason.

## Kill criteria
- The rule cannot tell the granting branch's kind from its name inside `check` without reading head data as configuration (C24): stop and report.
- A grant on `plan/` or a job's own branch passes the real judge in any test: that is the defect this job exists to remove; do not ship until it is refused.
- The change needs a `.github/` workflow edit: stop and report (a workflow change is a `meta/` job).
- Over about 70 tool calls: stop, commit, report what is left.

## Finish
Report in `jobs/W132/report.md` with the sections `## What was built`, `## Evidence`, `## Deviations from the brief and why`, `## Open questions`. Evidence must hold: the red output, the judge test names and
results, the W45 dry run, the CI run id with both runners, and a date on every "verified". Run `python3 wsc.py jobs usage W132 --write` where it applies, push `job/W132`, open the draft pull request, then
`wsc reg set jobs W132 status=review report=jobs/W132/report.md`. An independent reviewer merges (C18); never mark your own job `done`.

## Registry gaps
- path: tests/test_proposals_judge.py; owner: liam; reason: a host test file, cited as the pattern, not a tool (wsc.toml `[tools]`)
- path: jobs/W45/review.md; owner: liam; reason: a dated review record on job/W45, cited for the case

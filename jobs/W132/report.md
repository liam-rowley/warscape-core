# W132 report: The owner can grant one more review round

Liam (the owner) can now grant a job blocked after its review rounds one more fresh round, as a decision row only a `meta/` branch may add. The limit follows the row everywhere `MAX_ROUNDS` was used.

## What was built
- `schemas/decisions.schema.json`: optional `grants_round` (a job id).
- `warscape/policy.py` `grant_problems` (called from `check`): an added decision row with `grants_round` is refused on every branch kind but `meta/` (and `decide/`, which no base knows yet, so it is refused as a kind until one does). `plan/`, `brief/`, `release/` and every `job/` branch, the granted job's own included, are refused. The row must name a job that is on the base `blocked` with `blocked_by` "<n> review rounds without merge".
- `warscape/jobq.py`: `read_grants`, `max_rounds(jid)`, `blocked_by_rounds(jid)`; `S.grants` is filled by `configure` from the tree's decisions folder. `round_problems`, `round_status_problems`, `not_ready` and `review_steps` use them. With no row nothing changes.
- `tests/test_grant_round.py`: 6 judge tests (real commits on real branch names in a throwaway clone, `wsc policy` parent and `--judge` child) and 6 unit tests.
- Docs: `docs/REVIEW.md` "Rounds" (the exact command), one line in `docs/CONSUMING.md`, paid for by shortening two older lines.

## Evidence
- Red first, 2026-11-06: against the unchanged `warscape/` and schema, `python3 -m unittest test_grant_round` printed `FAILED (failures=3, errors=6)`: the 6 unit tests error (`max_rounds`/`read_grants` missing), and the 3 judge refusal tests fail (the row passed on `plan/`, `brief/`, `release/`, `job/`, and for unblocked or unknown jobs). With the change: 12 tests OK.
- W45 dry run, 2026-11-06, a throwaway worktree of `origin/job/W45`: before a grant `max_rounds` 3, `not_ready review` says "W45 is blocked, not review". With a `grants_round: W45` row and the row set to `review`: `max_rounds` 4, `not_ready('review')` is None (round 4 may start); `jobs check` rules still want `## Fix round 3` in W45's report first, as brief decision 4 says. **The real grant row is not written**: it is Liam's, on a `meta/` branch (`python3 wsc.py reg add decisions --mint who=Liam decision="..." reversible=yes grants_round=W45`).
- Gates, 2026-11-06, on commit a49495c (main unchanged at dd98dce, so nothing to merge): `python3 wsc.py gates` 14 ok, 2 warn (this clone hook path; the known skips), 0 failed, 1395 tests passed, 5 skipped, 711 s. The first two full runs failed: CONSUMING.md 30810 bytes over the 30720 cap, a `KeyError: policy` in `configure` for a config without `[policy]`, a test importing a non-stdlib test module, and the report row; each fixed.

## Deviations from the brief and why
- The limit is read from the decisions folder of the checked-out tree, not from main's. `policy` already refuses a grant from any branch but `meta/`, so a tree that holds one got it through the owner; reading main would need a git read in every `jobs` verb. A job branch that has not merged main does not see the grant until it does.
- The brief asked for a judge test of "a job branch with round 4 and a grant on its base (ok)". `policy` holds no round limit (the limit is `jobs check`'s), so that is covered by the unit tests of `round_problems`, `round_status_problems`, `not_ready` and `review_steps`, and the dry run above, not by `policy`.
- Open question 1: `decide/` is in `GRANT_KINDS` but the base does not know the kind, so `policy` refuses the branch as a kind anyway; W45 needs no change to this rule.

## Open questions
- CI run id: on the pull request after this push (not known when written).
- A grant is not checked against the job's actual round count (only that the base row is blocked); a second row for the same job while blocked once more is allowed on purpose: one row per extra round.

Usage: 75 tool calls; models: sonnet; counted from this session by hand (no usage_cmd output), about 5 over the brief budget of 70 because the first full gates run needed a second pass.

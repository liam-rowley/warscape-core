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

Usage: 115 tool calls; models: sonnet; 2 sessions, counted by hand: the build's 75 plus about 40 in fix round 1, which ran on Opus by decision C261106-bcaa; this field takes only the row's model

## Fix round 1
Answers review round 1 (2026-11-06, at 270254b). origin/main merged first (61b730b: b81d55a, the Opus decision row and W133). The fix session ran on Opus by decision C261106-bcaa; the row and merged brief still say Sonnet, and `jobs check` takes only the row's model, so the Usage line's model field says sonnet.

- **B1, fixed (f2fe8e2).** The rule read a state main never holds. The `meta/` pull request now carries the grant and the job's row set to `blocked`, and `grant_problems` reads the **head** row, as data. **This deviates from brief decision 2**, which asked for the base row, as the review recommended. The base row must be `queued` or `blocked` (the rows a job that ran can have on main), so a grant for a `done` or `needs_brief` job is still refused. The judge tests now seed `queued`, the shape main really holds.
  What this gives up: a grant for a running job can no longer be told apart. Main says `queued` for a running job too, and the head row is only what the pull request claims. Reading `job/<id>` from the judge would prove it; that needs a third tree in the judge and a look at the workflow's fetch, so it was left, as the review says.
- **S1, docs and text changed, control left for Liam (f2fe8e2, 06f6e84).** The error, the `GRANT_KINDS` comment, the schema description and `docs/REVIEW.md` now say the owner merges `meta/` by rule and nothing enforces it. No control was added: it needs something a session cannot hold, and that is Liam's `meta/` decision. `decide/` has the same gap.
- **S2, fixed (f2fe8e2).** `FourthRound.test_the_grant_then_a_fourth_round` walks the road through `wsc policy` and `jobs check` on a W45-shaped branch: no grant (policy rc 0, `jobs check` rc 1 "at most 3"), the grant on `meta/` against a `queued` base (rc 0), grant on main but not merged (rc 1, says so), merged (both rc 0).
- **S3, fixed by the message (1267da1, 06f6e84).** `round_problems` and `round_status_problems` now say a grant on main counts here only once this branch has merged main (`grant_hint`), and `docs/REVIEW.md` says merge main first. Grants are still read from the tree, not from `origin/main`: the review offered either.
- **S4, fixed (f2fe8e2, 06f6e84).** The documented command says `reversible=no`, and `policy` refuses a grant row that says otherwise, so the claim cannot come back. `read_grants` still counts every row.
- **S5, fixed here.** CI of round 1's head: run 42232795411, as the review found. Round 4 shown below; this head's run is under Evidence.
- **L1, left:** it is W133. **L2, fixed (1267da1):** `BLOCKED_BY_ROUNDS` removed. **L3, left:** stale `blocked_by` text only, and a merge of W45 does not depend on it.
- **Corrections to the sections above** (left as written): "W45 needs no change to this rule" under Deviations is wrong: W45's `decide/` rule allows only `needs_brief` job rows, so a grant on `decide/` would need that widened, and the row change is now part of a grant. The dry run under Evidence never ran the judge; the one below replaces it.

### Evidence, fix round 1
Red first, 2026-11-06: the new tests against the code as the review left it gave `FAILED (failures=4, errors=1)`: the grant on a `queued` base refused, no `status=blocked` or `reversible=no` in the messages, no "merged main" hint (the error was the new test's own helper use, fixed). With the fix: `tests/test_grant_round.py` 18 tests OK.

The W45 proof, 2026-11-06, run w45-fix1: a throwaway clone with a bare local origin, real `origin/main` b81d55a with W132 squashed on it, real `origin/job/W45`, `wsc policy` parent and `--judge` child. Nothing touched GitHub, and **no real grant was written**: that is Liam's, on a `meta/` branch.

| Step | Result |
| --- | --- |
| W45 before | `queued` on main, `blocked` / "3 review rounds without merge" on job/W45 |
| Grant alone on `meta/grant-W45-norow` | rc 1: "its row on this branch is queued, not blocked by its review rounds" |
| The two commands of `docs/REVIEW.md` on `meta/grant-W45` | `policy` rc 0 (2 files), `jobs check` ok |
| No grant, job/W45 row `review` with `## Fix round 3` | `jobs review --id W45`: "already has 3 rounds" |
| Grant merged, job/W45 merges main | conflicts in `registries/jobs/W45.json` and `warscape/policy.py`, both add/add |
| Row to `fix`, `jobs fix --id W45` | names fix round 3 |
| `## Fix round 3`, row `review` | `jobs check` ok |
| `jobs review --id W45` from main | "Claimed round 4", "This is round 4" |
| Round 4 `merge`, row `done` | `jobs check` ok, `policy --branch job/W45` rc 0 (27 files) |
| A fifth round | `jobs check`: "at most 4" |

The refusals of the review's table, re-run in that run with the grant and the row together on the head, the strongest form:

| Branch | Result |
| --- | --- |
| `meta/ok`, `meta/job/W45` | accepted |
| `plan/x`, `plan/grant-W45`, `brief/W45`, `brief/W132`, `brief/foo`, `release/v0.47.0`, `release/v9.9.9`, `release/x`, `job/W45`, `job/W132`, `job/W999` | refused by the grant rule |
| `spike/g`, `rev/W45`, `grant`, `meta`, `metax`, `Meta/g`, `META/g`, `meta-x/g`, `plan`, `job`, `refs/heads/meta/g` | refused by the grant rule |
| `decide/2026-11-06`, `decide/x` | refused as an unknown kind |
| `job/foo` | refused by the crash W133 owns |

Smuggling, all rc 1: a grant added to an existing row (append only), a row in a subfolder, a `.JSON` name, a symlink row, a real `registries/Decisions/` tree entry on `plan/`. Judge tests also refuse: a job not blocked on the head, another blocked reason, `needs_brief` and `done` base rows, no such job, a bad id, `reversible=yes`, a changed grant row.

### Open questions, fix round 1
- **For Liam: S1.** `meta/` being the owner's is a rule only. Is that enough, or does a grant need a control a session cannot hold?
- **For W45's fix session:** merging main conflicts as above. Keep both sides of `warscape/policy.py` (both new function groups, both `errs +=` lines) and the branch's own row. A grant's row needs a `meta/` branch until W45 widens `decide/`.

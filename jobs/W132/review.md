# W132 review

## Round 1 (2026-11-06, branch job/W132 at 270254b)

**Verdict: do not merge.**

The refusal half works: a grant was refused on every branch kind I put through the real judge. The acceptance half does not: the grant this job exists for is refused too, so W45 stays stuck. The cause is one rule, and it comes from the brief. No file outside this job's folder and row was changed in this round.

### Blocker

**B1. The real grant is refused: `warscape/policy.py:274` demands a state main never holds.** The rule wants the job `blocked` on the base, but a job's status changes only on its own branch, and a job branch merges only as `done`. W45 is `queued` on `origin/main` (b38465d) and `blocked` only on `origin/job/W45`; no row on main has ever said "review rounds without merge". So the command in `docs/REVIEW.md:22`, for the job the brief names, fails:

```
policy: registries/decisions/C261106-8af6.json: grants_round W45: its row on the base is queued, not blocked by its review rounds
```

To see it fail: in a throwaway clone with W132 squashed onto main, on `meta/grant-W45`, run `python3 wsc.py reg add decisions --mint who=Liam decision="x" reversible=yes grants_round=W45`, commit it, then `python3 wsc.py policy --branch meta/grant-W45 --base origin/main`. It exits 1.

Why the tests and the report missed it: `tests/test_grant_round.py:67` seeds a base row as `blocked`, a shape that never occurs, and the report's W45 dry run was made on a worktree of `origin/job/W45`, where the row does say blocked, and never ran the judge.

The only route that works today is undocumented: a `plan/` branch first writes `blocked` on main (rc 0 through the judge; `jobs check` stays ok), then the grant passes `meta/`. That also shows the rule proves little, because a branch that merges itself can satisfy it for any job.

Recommended fix, which deviates from brief decision 2 and must be named in the report: the `meta/` pull request carries both the grant and the job's row set to `blocked`, and the rule reads the **head** row (`head_rows`, as data). One pull request, owner-merged, and no self-merging step. Reading `job/<id>` from the judge would prove more, but CI would have to fetch that branch, which is a workflow edit and this brief's kill criterion. Either way, add a judge test whose base row is `queued`, and repeat the W45 dry run from main through the judge. W45's `decide/` rule allows only `needs_brief` job rows, so a grant on `decide/` would need that widened when W45 lands.

### Should-fix

**S1. "Only the owner merges" is a convention, not a control: `warscape/policy.py:255`, `:269`, `docs/REVIEW.md:22-23`. Liam decides this one.** The judge proves the branch *kind*, not who merged. The `Main` ruleset (26071159) has `deletion`, `non_fast_forward` and `required_status_checks` only: no pull request rule, and the repo has no CODEOWNERS. `ci/policy.yml.in` never looks at the actor, and sessions hold Liam's own `gh` token (`liam-rowley`, `repo` scope, read 2026-11-06). So a session that opened a `meta/` pull request and ran `gh pr merge --auto --squash` would meet no check, because `policy` passes the same row whoever wrote it. Not attempted on the real repo: the evidence is the ruleset, the workflow and the rc 0 from the judge. Past `meta/` merges by `liam-rowley` (#135, #99, #18) prove nothing, as that is also the sessions' login. The brief set `meta/` as the boundary, so this is not a builder's error, and a real control needs something a session cannot hold; that, and any workflow change, is outside this job. The fix session should only stop the docs and the error text overstating it ("merged by the owner by rule; nothing enforces it"), and leave the control to Liam as a `meta/` decision. W45's `decide/` has the same gap.

**S2. The brief's round 4 judge test is missing (decision 5).** The report's reason, that `policy` holds no limit, explains why `jobs check` must be run too, not why the case is left out. I ran it, so it is cheap to add: a job branch with 4 rounds and a merge verdict gives policy rc 0 and `jobs check` ok with a grant; without one, policy rc 0 and `jobs check` rc 1 ("at most 3"). A case with W45's real shape would also have caught B1.

**S3. A job branch that has not merged main is told the wrong thing: `warscape/jobq.py:520-523`.** Decision 3 said to read grants from main; the report names the deviation to the checked-out tree. But `gates` runs on the push of the branch head, never a merge ref (`.github/workflows/gates.yml:9`), so with the grant on main and not yet in the branch, `jobs check` exits 1 with "at most 3 ... the owner can grant one more", for a grant that exists. Reproduced on `job/W901` with 4 rounds. Say "merge main first" in `docs/REVIEW.md:24` and in the message, or read `origin/main` as decided.

**S4. `reversible=yes` is not true: `warscape/jobq.py:70`, `docs/REVIEW.md:22`.** The documented command says a grant can be reversed, but `read_grants` ignores `replaces`. A reversal row passed the judge on `plan/` and the count stayed `{'W901': 1}`. Write `reversible=no` in the command, or have rows named in `replaces` stop counting, and if so only from an owner's branch, as `plan/` must not cancel the owner's grant.

**S5. Report evidence.** The brief's Finish asks for the CI run id with both runners; the report has none (it is run 42232795411, below). Deliverable 5 asked to show `jobs review --id W45` naming round 4; the report shows `not_ready` only. It does work: once the row said `review` with `## Fix round 3`, `jobs review --id W45` claimed round 4 and wrote "This is round 4" (against a bare local origin, with W132 on main and main primed as in B1).

### Later

- **L1.** `warscape/policy.py:307`: on a branch like `job/foo`, `kind` is `job` but `m` is None, so rule F raises `AttributeError` and the judge refuses with a traceback, not a reason. It was on main before this job and fails closed. Filed through a `plan/` pull request.
- **L2.** `warscape/jobq.py:154`: `BLOCKED_BY_ROUNDS` has no caller left in `warscape/`, only the docstring at `:534`. Remove it, or use it for the default.
- **L3.** `reg set jobs <id> status=fix` leaves `blocked_by` on the row. `jobs check` and `gates --fast` accept it and `jobs fix` runs, so it is only stale text. Clear it in the same fix if convenient.

### What was checked

All on 2026-11-06. The judge runs used a throwaway copy of real main plus W132 squashed, so the base judged with W132's rules, with a bare local origin; `wsc policy` parent and `--judge` child; nothing touched GitHub. Python 3.15.2 on this Windows host.

- **Machines:** `python3 wsc.py gates` 14 ok, 2 warn, 0 failed, 1395 host tests passed, 5 skipped. `policy` at 270254b refuses only for the missing review and the row, as expected before this commit.
- **Windows CI, run 42232795411 at 270254b:** `gates (windows-latest)` ran the full `python wsc.py gates` on Python 3.12.10, no pass-marker skip: 1395 passed, 5 skipped, 816 s. `gates (ubuntu-latest)` and `harness-windows` green; `proxy` skipped as no input changed. The log does not name single tests: the 12 are placed there by W81's 1383 + 12 = 1395, the `[tests]` discovery of `tests/`, and no skip in the file.
- **Latest main:** `origin/main` moved to b38465d during this review (one decision row, C261106-bcaa). It shares no file with W132, `git merge-tree` is clean, `policy` gives the same result, and W45 is still `queued` there.
- **Red first, reproduced:** `tests/test_grant_round.py` on unchanged main: `FAILED (failures=3, errors=6)`, as reported. On the branch: 12 tests OK.
- **Grant by branch kind** (base row blocked by hand, so the kind rule is what is tested):

| Branch | Result |
| --- | --- |
| `meta/ok`, `meta/job/W45` | accepted |
| `plan/*`, `brief/W45`, `brief/W132`, `brief/foo`, `release/v0.47.0`, `release/x` | refused by the grant rule |
| `job/W45` (the granted job), `job/W132`, `job/W999` | refused by the grant rule |
| `spike/g`, `rev/W45`, `grant`, `meta`, `metax`, `Meta/g`, `META/g`, `meta-x/g`, `plan`, `job`, `refs/heads/meta/g` | refused by the grant rule |
| `decide/2026-11-06`, `decide/x` | refused as an unknown kind (the base does not know `decide/`), as the report says |
| `job/foo` | refused by a crash (L1), before the grant rule's verdict is printed |

- **Control:** a fully mergeable `job/W900` passes (rc 0); the same branch plus a grant is refused, so the grant alone decides it.
- **Smuggling, all stopped:** a grant added to an existing row (append only); a row in a subfolder or named `.JSON`; a symlink row ("not a JSON object"). A real `registries/Decisions/` tree entry slips past the prefix test and this Windows checkout does count it (`{'W45': 1}`), but the `windows_paths` and `registries` gates fail it and `plan/` refuses it by its globs. `grants_round` on a job row passes the judge but is never read as a grant.
- **Risk-first reading:** `grant_problems` and `read_grants`, because they are the boundary. The `jobs view` card and `audit` need no change: neither holds a limit (decision 3). `wsc reg add decisions --mint ... grants_round=W45` works.

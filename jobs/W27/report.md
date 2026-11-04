# W27 report: Review integrity: reviewer code, fresh rounds, append-only rounds, cited evidence

`wsc policy` now reads a job branch's commits by sha and checks who wrote each review round and what else its commits changed (rules A, B), that review rounds
are append only on every commit (C), that cited run folders, branches and commits can be opened from `main` (D), that a `merge` on a large diff cites evidence
(E) and, opt-in, that a decision row added on `job/<id>` names `<id>` (F). `wsc jobs review` and the autopilot claim the round on origin first
(`refs/claims/<id>/round-<n>`), a report beside `jobs/<id>/handback.md` says what the orchestrator added, and W23's bootstrap `pull_request` trigger is gone. Rule
A and rule D's branch cites are warnings, not refusals: the scan of the merged job branches passed the brief's kill criterion (below). Started from `origin/main`
72f50d4 (VERSION 0.30.0); merged `origin/main` 6e743da, then 60ba80e; 0.35.0, C30.

Written by the orchestrating session (same session id as the builder) from the builder subagent's hand-back text, unchanged in substance; the harness refused the
builder's own write of this file (the R10 case this job's `handback.md` rule is for).

## What was built
- **`warscape/policy.py`** (the docstring lists every rule and pattern):
  - `check()` gains `reads=` (the git reads of rules A-E: `commits()`, `history(path)`, `numstat()`, `exists(path)`, `ref_state(name)`, `sha_state(sha)`; None
    skips them) and `warnings=` (a list the warnings go to). It stays pure; `run_check` builds `GitReads` (every read at `repo` by sha) and takes `warnings=`. No
    existing caller or test changed; `JUDGE_API` stays 1.
  - **A** (`round_problems`, warning): a round's commits are the review.md commits whose file holds round N as its newest, any other commit by a session of those,
    and a commit by nobody known (no trailer, or a session neither the builder's nor a round's) after the first review commit, which goes to the round of the next
    review commit (the newest round when none follows). The builder's sessions are every report.md writer, so a fix session is never a reviewer. A file outside
    `jobs/<id>/` and `registries/jobs/<id>.json` under a `merge` verdict warns, naming the shas and paths, "write the verdict `merge after fixes`; a fresh round
    reviews your change".
  - **B** (error): "round 2 was written by a session that wrote round 1 (R1): a fresh session per round (docs/REVIEW.md)". The builder in a round and a missing
    trailer keep today's messages.
  - **C** (`append_only_problems`, error): each base round is unchanged at the head. Commit by commit (`git log --full-history` and one `cat-file --batch`), an
    earlier round stays byte-identical once a newer one exists, so a rewrite then a restore is refused at the rewrite. Before that, only the session that wrote it
    may edit it.
  - **D** (`evidence_problems`): a repo-relative `runs/` path missing from both trees is an error; an unmerged `job/`, `brief/` or `origin/` ref is a warning
    (merged means an ancestor of the base, a tag's target, a `done` row on the base for a squash-merged job, or the brief on the base); a ref the clone lacks, and
    an unreachable or unknown commit sha, are warnings.
  - **E** (`thin_merge_warning`, warning): over `[policy] thin_merge_lines` 500 or `thin_merge_files` 20 outside the jobs folder and the registries, with a newest
    round that names no run id, actions URL, `run <digits>`, test name or runs/ path.
  - **F**: `[policy] decisions_cite_job` (default false; the core's `wsc.toml` sets it true). The policy facts gain `added_decision_rows`.
  - `wsc policy` prints `policy: warning: ...` lines after the note and before the verdict line; the pre-W23 fallback in `policy_base.py` prints them too. Exit
    codes do not change.
- **The claim** (`warscape/claims.py`, a library module, plus `jobq.take_claim` and `jobq.print_claims`):
  - The claim ref points at a commit made for it: the head's tree, the head as parent, and `session:` and `time:` in the message. Two claimers therefore push
    different commits, and git refuses the second (non-fast-forward, no force).
  - A claim older than `[jobs] claim_hours` (4) is deleted with a lease on its sha, then taken.
  - `jobs review` releases claims of rounds the branches already have; `jobs next` releases those whose branch is gone. `next`, `review` and `view` print live claims.
  - An unreadable origin refuses; `--offline` claims nothing. `jobs review --session` names the claimer (default `$WSC_SESSION_ID`, then
    `$CLAUDE_CODE_SESSION_ID`, then user@host).
  - `JobServer(claim=...)` claims for a review after the agent and claude checks and before the launch: 409 naming the holder, 503 when the claim cannot be
    proved, nothing in a dry run.
  - `.githooks/pre-push` skips its gates for a push of `refs/claims/*` only.
  - Probed once on GitHub (2026-11-04): a push to `refs/claims/W27/probe` was accepted, a second push of the same sha was "up to date" (hence the claim commit),
    and the ref was deleted.
- **`handback.md`**: `jobq.problems` fails with "report.md sits beside a handback: say what the orchestrator added" when `## Orchestrator additions` is missing.
  `branch_rows` reads whether a branch has a handback, and `review_steps` and `fix_steps` name it. `review_steps` now also says that a reviewer of an earlier round
  may not review, and that changing a file outside the job folder means `merge after fixes`.
- **CI**: the `pull_request` trigger and its comment are gone from `ci/policy.yml.in`, and `.github/workflows/policy.yml` is re-rendered. `ci_render` and `gates`
  print no bootstrap warning.
- **Docs and rows**: `docs/REVIEW.md` (Starting, Rounds, Setup, Steps 2 and Output; small fixes now only under `merge after fixes`); `docs/CONSUMING.md` (the
  keys, the fact and a short "Review integrity" section, under the 30 KB gate); `CLAUDE.md` Jobs; C30; the `wsc.jobs` and `wsc.policy` tools rows; `VERSION`
  0.35.0; `tests/fixture_game/wsc.toml` spells out the thin-merge keys.

## Evidence
- **Red first:** 8a1df01 (tests only, on 72f50d4). 44 new cases were red in `test_policy`, `test_jobs` and `test_ci`: errors because `reads=`/`warnings=` and
  `warscape.claims` did not exist yet, failures for handback, rule F and the trigger. The 5 new CLI repros in `test_policy_base` were red too.
  `test_off_by_default_and_plan_branches_are_unchanged` and the B cases that reuse today's messages were green on purpose (no regression).
- **Green:** `python3 wsc.py gates` (full) on the merged head, 2026-11-04: 13 ok, 2 warn (this worktree's hooks wiring; 5 skipped tests needing capstone or a
  POSIX sh), 0 failed; 785 host tests. `gates --fast` ok. `python3 wsc.py policy --branch job/W27 --base origin/main`: judged with the rules of origin/main at
  6e743da (core 0.33.0), with the rule-input note; refused only for the missing report and review and the row that is not done, as a job in review should be.
- **Tests added:** `tests/test_policy.py`: W27ReviewerCode (6), W27FreshRounds (4), W27AppendOnly (6), W27Evidence (10), W27ThinMerge (4), W27DecisionsCiteJob (3).
  `tests/test_policy_base.py`, CoreMode `test_w27_*` (5): A warns; B refused; C rewrite-and-restore refused; D missing run folder refused, with the
  unmerged-branch warning; warnings print before the verdict and exit 0. `tests/test_jobs.py`: Handback (3) and ReviewClaim (7): the first claimer wins and the
  second names it; stale takeover; release; unreadable remote; two `jobs review` runs against one bare origin leave one winner; server 409; server 503.
  `tests/test_ci.py`: `test_w27_this_repos_policy_workflow_is_pull_request_target_only`. Two existing verb tests now stub `print_claims` and `take_claim`: they
  run `jobs review` against the real origin.
- **False-positive scan** (2026-11-04, scratch script, not committed). Every merged `job/*` pull request was judged at its head against its merge commit's first
  parent, with this branch's rules, gate modules off and `decisions_cite_job` on:
  - warscape-core, 23 merged: A 5 (W4, W6, W19, W24, W37: a reviewer's code or docs/BACKLOG.md under `merge`); B 0; C 0; F 0; D run folders 2 beyond the
    audit's W2 (W12 cites napoleon's run folders; W30 cites `runs/r1` as an example); D branch cites 4 (W1, W12, W23, W30).
  - napoleon-remastered, 60 merged (its `wsc.toml` loaded without the `[jobs] hooks` key this core replaced): A 27; B 4 (J4, J20 and J52 are the audit's; J8 is
    beyond); C 0; D run folders 1 (J82); D branch cites 9; F 2 (J1, J3).
  - Kill criterion (more than 3 beyond the audit's): A (32) and D's branch cites (13) became warnings in 295ba8a. B (1), C (0), D's run folders (3) and F (2)
    stay errors.
- **Bootstrap removal:** the recorded `pull_request_target` run of policy is 41871905211 (success, 2026-11-04, `plan/c27-tags-by-workflow`). W27's own pull
  request #93 got policy workflow run 41891758310; its `policy` job was skipped because the PR is a draft. The reviewer's ready-then-push gives its first real run.

## Deviations from the brief, and why
- **Rule A is a warning, and so is an unmerged branch cite (rule D).** Each refused more than 3 merged job branches beyond the audit's (the kill criterion). So the
  acceptance "rules A-C end REFUSED" holds for B and C. A's repro ends `ok` with a warning that names the commit, the path and the fix. Rule D still refuses a
  missing run folder. (Liam's 2026-11-04 answer, C28 on main, set rule A's file set to every change outside the job folder; it did not decide warning or error.)
- **Rules A-F landed in one commit (788f543), not one per rule**, to stay within the call budget. Each rule has its own functions and test class; 295ba8a then
  made A and D's branch cites warnings.
- **"Merged" for a cited branch also counts a `done` row (job) or the brief (brief branch) on the base.** Every job here is squash-merged, so no merged job branch
  is an ancestor of `main`.
- **A run-folder cite must be repo-relative.** `RUN_PATH` does not match inside a URL or after `/`, `\`, `:`, `<` or `~`: an absolute PC path cannot be proved
  either way.
- **The `GOLDEN` hashes do not change.** They cover the fixture's templates and the block renders, not the core's own `ci/policy.yml.in`. The W23 test became the
  W27 test.
- **`jobs next` releases only claims whose branch is gone**, because it reads no branch's rounds. `jobs review` releases claims of rounds the branches already
  have. The handback path is printed in the `review` and `fix` steps; `next` names builds and briefs, which have no handback.
- **Outside the listed files:** `warscape/claims.py` (the "one small helper"; `jobq.py` is 1,199 lines) and `.githooks/pre-push`, so a claim push never fails on
  an unrelated gate.
- **The report was not written by the builder:** the harness refused the builder subagent's Write of `report.md`, so the orchestrating session wrote it from the
  hand-back (R10).
- **VERSION and C number:** main took 0.33.0 and C28 while this was being built (W25, W38), so this job took 0.34.0 and C29, merged in (no rebase); then W33 took 0.34.0 and C29 on main,
  so on the second merge of `origin/main` (60ba80e) this job takes 0.35.0 and C30.

## Open questions
1. **Make rule A an error?** The scan found 32 merged branches where a reviewer's commits under `merge` changed files outside the job folder, so the rule catches
   the practice it is meant to stop. Recommended: once the new Output wording in `docs/REVIEW.md` has been in use for a while, a small job turns it into an
   error, or adds a `[policy]` key a game can set.
2. **Kill-criterion counting** was taken across both repositories, and per sub-rule of D (run folders separately from branch cites). Read per rule only, D's run
   folders (3 beyond) would still stay an error.
3. **What a game does:** napoleon's pin bump sets `[policy] decisions_cite_job = true` (its row; J1 and J3 would have failed it); check that its J76 hook allows
   `git push origin <sha>:refs/claims/...` and deleting `refs/claims/...` (it denies deleting only `main`, `plan/`, `meta/`, `job/` and `brief/`); use
   `jobs/<id>/handback.md` when a builder subagent cannot write the report; stub `print_claims` and `take_claim` in any test that runs `jobs review` against a
   real origin.

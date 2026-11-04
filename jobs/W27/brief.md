# W27: Review integrity: reviewer code, fresh rounds, append-only rounds, cited evidence

Model: Opus, reason: enforcement code in `policy.py` and `jobq.py` where a mistake is a bypass of the one gate that decides what reaches `main` (D52: builds on Opus). Budget about 170 tool calls: about 40 for reading and the red tests, 70 for the rules, 20 for the claim and handback, 15 for CI and docs, 25 for gates and the report. At the cap, stop, commit, and report what is left.

## Goal
Audit 2026-11-03 (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`, read-only): R5, R6, R7, R8, R10, the rule rows "never review your own job" and "earlier review rounds never edited", and the thin-`merge`-review note (J62, J57). Today `policy` compares the report's trailers with the review's only (the `if sessions and trailer` block in `warscape/policy.py` `check`). It cannot see that a reviewer wrote code, that round 2 was the round 1 reviewer, that round 1 was edited, that evidence sits on an unmerged branch, or that a merge verdict cites nothing. This job adds those rules. It also removes W23's bootstrap trigger.

## What exists (read before building; checked 2026-11-04 against `origin/main` ea98a96, VERSION 0.30.0)
- **Rules and docs:** `CLAUDE.md`, `docs/DECISIONS.md` (C18, C22, C24 judged with the base), `docs/REVIEW.md` ("Rounds", "Output", "Merging"), `docs/CONSUMING.md` "The job pipeline", `jobs/W23/report.md` ("After the merge") and `jobs/W23/brief.md` decisions 1-12.
- **`warscape/policy.py`:**
  - `check()` is pure: `base_file`/`head_file` callables, `sessions(path)` returning one trailer set per commit that touched the path, `hook`, `base_ref`.
  - `run_check()` builds `sessions` from `git log mb..h`. Every git read is at `repo` by sha; nothing runs git in `ctx.root`; `JUDGE_API = 1` stays on a line of its own.
  - `verdict()` reads the first `Verdict:` line.
- **`warscape/jobq.py`:**
  - `review_rounds`, `round_problems`, `round_status_problems` (lines 183-250): the round format, numbering, one verdict per round, row agreement.
  - `RUN_CITE` and `failed_results_problems` (line 154): how a report's run citations are found.
  - `Server.start()` (about line 981): the live guard keys on session names `<id>-<action>` from `claude agents --json`; `LIVE_STATES`; `not_ready`.
  - `review_steps()` (about line 1128): the text a fix session is told.
  - `brief_problems`, `report_problems`: the shape checks `wsc jobs check` runs.
- **W23's bootstrap trigger:** `ci/policy.yml.in` keeps `pull_request` with `paths: ['jobs/W23/report.md']` beside `pull_request_target`; `ci_render` warns until it goes.
- **A `pull_request_target` run of `policy` is recorded** (the condition W23's report set for removal): run 41871905211 (success, 2026-11-04, branch `plan/c27-tags-by-workflow`). Its log shows `policy: judged with the rules of origin/main at cc1491ebfba0 (core 0.30.0)` and `policy: plan/c27-tags-by-workflow: ok (1 files changed)`. Runs 41861334562 (`plan/W38`), 41852875674 (`job/W22`) and 41849236263 (`job/W10`) are `pull_request_target` too.
- **Evidence of the gaps** (audit): reviewer-written code merged unreviewed in J9 `2e6a75d`, J24 round 2 `192170c`, J46 `3d6ed72`, J66 `08a7a7c` and W2's `hooks.cpp` `649c290`; round 2 by the round 1 reviewer in J4, J20 and J52; two round 1 reviewers at once on J10; W2 merged on evidence on napoleon's unmerged `job/J30`, built from an unpushed core commit; thin merges on J62 and J57; reports written by the orchestrator from a hand-back in J11, J24, J33, J34, J38, J46, J57, J62, J65, W1 and W2.

## Decisions already made (follow them; a deviation goes in the report with its reason)
1. **Everything is judged by the base's code.** The new rules live in `warscape/policy.py` (and `jobq.py` for the handback and claim rules `wsc jobs` runs), read git by sha at `ctx.facts['repo']`, and keep `check()` pure. Do not bump `JUDGE_API` unless a child argument changes (it should not). A branch that edits these rules proves them with host tests, not with its own `policy` run (C24).
2. **Rule A, reviewer code needs a fresh round.** On a `job/` branch, take each review round's own commits: the commits that touch `review.md` plus the commits between them, authored by a session that is not in the report's trailer set. If any of them changes a file outside `jobs/<id>/` (the `[jobs] dir`) and outside the row file `registries/jobs/<id>.json`, that round's verdict must be `merge after fixes` (or `do not merge`), never `merge`. Reason: a `merge` that follows reviewer-written code has no independent review of that code. The message names the commit shas and paths and says "write the verdict `merge after fixes`; a fresh round reviews your change".
   - The builder chooses the exact split of commits into rounds (simple and testable beats clever) and says which in the report.
   - A reviewer's edit of `review.md` or the row alone never trips the rule.
3. **Rule B, trailers differ across rounds.** Every round's commits carry session trailers disjoint from the builder's (report's) set and from every earlier round's set. A round whose trailers meet an earlier round's is refused ("round 2 was written by a session that wrote round 1: a fresh session per round, docs/REVIEW.md"). Fail closed on a missing trailer exactly as today's report/review rule does. A fix session's `## Fix round N` commits to `report.md` count on the builder side: a fix session is never a reviewer.
4. **Rule C, review rounds are append-only.** Every earlier round's section (heading line through its last line) stays byte-identical on every later commit; only a new round on top, or edits inside the newest round by the session that wrote it, are allowed. Once a newer round exists, the older one is frozen. Check it two ways: at the head against the base, and commit by commit over `mb..h` for `review.md`, so a rewrite followed by a restore cannot pass. Use `jobq.review_rounds` on each commit's blob (`git log --format=%H -- <review.md>` and `cat-file --batch`).
5. **Rule D, cited evidence resolves on a main branch or a pushed tag.** In `report.md` and `review.md` at the head:
   - a cited run folder (`RUN_CITE`, a `.../runs/<id>` path) must exist in the head's tree or the base's. A cite that exists in neither is an error naming the path.
   - a cited `job/<id>` or `brief/<id>` branch other than the branch itself, or an `origin/...` ref, is evidence only if it is an ancestor of the base or a pushed tag. A ref that exists in the clone and is not merged is an error ("evidence on an unmerged branch cannot be opened from main: merge it, tag it, or copy it into the repo"). A ref the clone does not have is a warning (it may be another repository's).
   - a cited commit sha (7-40 hex in backticks, after "commit", "sha" or `@`) must be reachable from the base or the head, or be a tag's target in this clone; otherwise a warning that says "a commit that is not pushed cannot be opened".
   - Errors only for what the clone can prove; warnings for what it cannot. The builder lists the exact patterns in the docstring and tests each.
   - Warnings print as `policy: warning: ...` lines before the verdict line and never change the exit code. `check()` returns them apart from errors (the builder chooses the shape and updates every caller and test).
6. **Rule E, a thin `merge` is a warning.** A `merge` verdict on a diff of more than 500 changed lines or 20 changed files outside `jobs/` and the registries (`git diff --numstat`), whose newest round cites no run id, no `runs/` path, no CI run (an actions URL or `run <digits>`) and no test name, warns: `policy: warning: merge verdict on a large diff cites no evidence (J62, J57)`. The thresholds are `[policy]` keys with those defaults so a game can tune them.
7. **Rule F, a decision row added on a `job/` branch cites its brief.** New `[policy] decisions_cite_job` (default `false`; the core's own `wsc.toml` sets it `true`; Napoleon turns it on in its pin bump). When true, every new row of the decisions file on `job/<id>` must contain `<id>` (for example `W27`) in its cells: the brief that required it. Message: "decision row <C|D><n> on job/<id> must name the brief that required it (add `<id>` to the row, or move it to a plan/ branch)". `plan/` and `meta/` branches are unchanged. The policy-stage facts gain `added_decision_rows` (a list of `{id, text}`) so a game's own module can be stricter; document it in `docs/CONSUMING.md` "Game gates".
8. **A branch-level review claim, so two reviewers cannot start round N at once (R7).**
   - A claim is a remote ref `refs/claims/<id>/round-<n>` that points at the branch head at claim time, with the claimer's session name and the time in the commit message.
   - `wsc jobs review` (and the autopilot's `Server.start()` for the `review` action) creates it with `git push origin <sha>:refs/claims/<id>/round-<n>`. Git refuses a second creator of the same ref, so the push is the lock.
   - A refused push means "round n is claimed by <session>": `jobs review` prints it and exits 1; the autopilot returns 409 naming the claimer and never launches.
   - A claim older than `[jobs] claim_hours` (default 4) is stale and may be taken over after deleting the ref. A claim for a round the branch already has is released by the next `jobs next|review` run. `jobs next|review|view` print live claims; `jobs check` ignores them (they are not files).
   - Fail closed on an unreadable remote (the claim cannot be proved), except with `--offline` for local-only tests.
   - Keep it in `jobq.py` plus one small helper; no new verb unless `jobq.py` passes about 1,300 lines (say so).
9. **`handback.md` (R10).** A job may carry `jobs/<id>/handback.md`: the builder subagent's own words when a subagent cannot write the report (a game's hook refuses a subagent's Write of `report.md`). In `jobq.py` and the `jobs` check:
   - a `report.md` beside a `handback.md` must carry a section `## Orchestrator additions` naming what the orchestrator added or checked itself (it may say "none"); without it `wsc jobs check` fails with "report.md sits beside a handback: say what the orchestrator added".
   - `docs/REVIEW.md` Setup tells the reviewer to read `handback.md` after the report, and `jobs next|review` print its path when a job has one.
   - A handback needs no change in `check()`: a `job/` branch may already change any file.
10. **Bootstrap removal.** Delete the `pull_request:` trigger and its comment from `ci/policy.yml.in` and re-render `.github/workflows/policy.yml` (`python3 wsc.py ci render`). Update `tests/test_ci.py`: the W23 test that expects the bootstrap trigger becomes a test that the core's workflow has `pull_request_target` and no `pull_request`; `GOLDEN` hashes change deliberately, with a comment saying W27 changed them. Cite run 41871905211 in the report (and W27's own `pull_request_target` run id once it exists). If a later pull request shows no `policy` check, a `meta/` revert of the trigger is the recovery (W23's note).
11. **Decision line.** Append the next free `C<n>` to `docs/DECISIONS.md` as `proposed (Claude, core W27)`, reversible yes, recording rules A-F, the claim, `handback.md` and the bootstrap removal. Re-read `origin/main` `DECISIONS.md` before the last commit: other open jobs take numbers too (renumber, never rebase).

Out of scope (other rows): hook hardening (napoleon J76); `later` row kinds and default-if-unanswered questions (W32); release tags (W29); gate fixes (W28); main health (W22, merged); changing `MAX_ROUNDS`.

## Scope: files this job touches
- **Library:**
  - `warscape/policy.py`: rules A-F, warnings, facts, docstring.
  - `warscape/jobq.py`: claim, handback, `review_steps` text, view lines.
  - `warscape/repo.py` `DEFAULTS`: `[policy] decisions_cite_job` and the thresholds; `[jobs] claim_hours`.
  - `warscape/verbs/policy.py` and `warscape/verbs/jobs.py`: warning and claim output; refresh the headers and the tools rows (`python3 wsc.py reg add tools <path>`).
  - `warscape/policy_base.py` only if the child's output relay needs the warning lines.
- **CI:** `ci/policy.yml.in`, `.github/workflows/policy.yml` (render). `warscape/ci_render.py`: the both-triggers warning may stay, since it fires only when a template has both.
- **Tests:**
  - `tests/test_policy.py` (pure `check()` cases) and `tests/test_policy_base.py` (git-backed: reviewer code, rounds, evidence).
  - `tests/test_jobs.py` (claim against a local bare remote, handback).
  - `tests/test_ci.py`, and `tests/test_gatemods.py` if the facts change it.
  - The core's `wsc.toml` and `tests/fixture_game/wsc.toml` for the new keys.
- **Rows and docs:**
  - row W27 and `registries/tools.jsonl`.
  - `docs/REVIEW.md` (Rounds, Setup, Output), `docs/CONSUMING.md` (new keys, facts, warnings; stay under 30 KB), `docs/DECISIONS.md`, `CLAUDE.md` Jobs (one sentence), `VERSION`.
- **Not touched:** `proxy/`, `harness/`, `discovery/`, `saves/`, any Napoleon file, `empire-remastered`. No game names in core files.

## Steps
1. Read "What exists". Note the commit you start from.
2. **Failing tests first, committed red** against the current code (name the sha in the report). Use the throwaway core clones from `tests/_util.py` `core_source()` and the fixture game, driving `wsc policy` as CI does and `check()` directly where pure.
   - A: a `job/W1` whose round 1 reviewer commit also edits `warscape/x.py` and says `merge` is refused; the same with `merge after fixes` passes; a reviewer commit touching only `review.md` and the row passes.
   - B: round 2 carrying round 1's session is refused; the builder's session in a round is refused; a fix session reviewing a later round is refused; a missing trailer is refused.
   - C: round 2 added on top passes; an edit inside round 1 after round 2 exists is refused; a rewrite-and-restore across two commits is refused; the newest round's own author may edit it before another round exists.
   - D: a cited `runs/` folder that exists nowhere is an error; one in the head passes; a cited unmerged `job/J9` is an error, a merged one is fine; an unresolvable sha warns; each pattern in the docstring has a case.
   - E: a 600-line `merge` with no evidence warns; the same with a run id does not; a small diff does not.
   - F: `job/W1` adding row `C99` without `W1` in it is refused when `decisions_cite_job = true`, passes with it, and passes on `plan/`.
   - Claim: with a local bare repo as `origin`, the first claimer wins and the second is refused naming the first; a stale claim (back-dated) is taken over; a round the branch already has releases it; an unreadable remote refuses; `Server.start()` returns 409 for a claimed round.
   - Handback: a `report.md` beside a `handback.md` without `## Orchestrator additions` fails `jobs check`; with it passes; no handback changes nothing.
   - Bootstrap: `.github/workflows/policy.yml` has `pull_request_target` and no `pull_request`.
   - No regression: every existing test stays green, and none of the new code imports or executes a head file (C24).
3. Implement the rules in `policy.py` one per commit (A, B, C, D, E, F), each commit green for its own tests. Keep `check()` pure: pass the new git reads in as callables (`round_commits(path)` returning `[(sha, trailers, text)]`, `numstat()`, `reachable(rev)`), built in `run_check`.
4. The claim and `handback.md` in `jobq.py` and the verbs; update `review_steps` so a fix session is told never to touch `review.md` or earlier report sections.
5. CI: remove the bootstrap trigger, `python3 wsc.py ci render`, update `tests/test_ci.py` deliberately.
6. Docs, the C row, the tools rows, `VERSION`. Then `python3 wsc.py gates` (full) and `python3 wsc.py policy --branch job/W27 --base origin/main` (it prints the "changes a rule input" note: the old rules judge this branch).

## Tests and acceptance (what done looks like)
- Every test in step 2 is red at its commit on the starting code and green at the end, on Linux and Windows CI. Every existing test is green; the `GOLDEN` hashes change in one commit that says why.
- Rules A-C stop the audit's repros: a reviewer commit that edits code under a `merge` verdict, round 2 by round 1's session, and a rewritten round 1 each end `REFUSED` with a message that names the fix.
- Rule D refuses a report that cites a run folder missing from the repo and a cite of an unmerged `job/` branch.
- The claim: two `wsc jobs review` runs for the same round against one bare remote leave exactly one winner and one refusal that names the winner.
- `.github/workflows/policy.yml` has `pull_request_target` only; `ci_render` and `gates` print no bootstrap warning; the report cites run 41871905211 and, if W27's own pull request produced one, its `pull_request_target` run id.
- `docs/REVIEW.md`, `CONSUMING.md` and the tools rows say what the code does (grep the old claims: "never edit an earlier round" now names the check).

## VERSION
A minor bump. Re-read `origin/main` `VERSION` and the open `job/*` branches before the last commit (W26, W28, W29, W35 and the builds W15, W16, W25, W33 may merge first). Take the next free minor and C number, merge `main` (never rebase), and say what you took. Tags are Liam's.

## Kill criteria
- A rule needs a head file on disk or the head's code: stop and report which rule and what it needs. Rules read git objects at shas only.
- GitHub refuses `refs/claims/*` pushes, or a bare-remote test cannot express the claim lock within about 15 calls: stop the claim, finish the other rules, report the git error and take open question 3.
- A rule refuses more than 3 merged job branches of `main` beyond the audit's listed ones (run each rule over them with a throwaway script in the scratchpad): make that rule a warning, and say so.
- The `check()` signature change breaks more than 10 callers or tests: stop and report; use a wrapper instead of a wide change.
- Core CI red after three fix attempts for a cause in this change: stop and report. Version or C-number collision as in VERSION; never rebase a pushed branch.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **Warning or error for an unresolvable cited sha?** Recommended: a warning (another repository's sha cannot be proved here); errors only for what this clone can prove.
2. **Rule A's file set.** Recommended: any change outside `jobs/<id>/` and the job's own row counts as code, including docs and `DECISIONS.md` (a reviewer-written decision is exactly R5). A reviewer who needs a doc typo fixed writes `merge after fixes` and the fresh round merges it.
3. **If a ref-based claim is impossible** (GitHub refuses it, or a remote is not writable by reviewers). Recommended: a file `jobs/<id>/review.claim` committed on `job/<id>` by `jobs review` with the session name and time, so the push race is the lock, with the same staleness. Rule C then ignores that file.

## Finish
Write the report in `jobs/W27/report.md`. It covers:
- the rules as built (A-F), the claim and `handback.md`;
- the test list, red then green, with the red sha;
- a run of each rule over the merged job branches of `main` (the false-positive check) and the result;
- the bootstrap removal and the `pull_request_target` run id(s);
- the version and C number taken, deviations, open questions, and what game repos do (Napoleon's row for `decisions_cite_job`, the claim, the handback).

Then run `wsc reg set jobs W27 status=review report=jobs/W27/report.md` (`python3 wsc.py`). Push `job/W27`, open the draft pull request, and stop. An independent reviewer merges (C18), and Liam tags.

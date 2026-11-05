# Reviewing a job branch

The generic review procedure of the job pipeline (`wsc jobs`, `wsc policy`; C18). A game repo keeps a short addendum of its own (its check names and
extra steps) beside this file in `core/docs/REVIEW.md`. Commands below are written for a game repo (`python3 core/wsc.py`); inside the core itself the
prefix is `python3 wsc.py`, and the job ids are `W<n>`.

Every job branch gets an independent review before it merges; with a `merge` verdict the reviewer merges it on green CI. The reviewer is a fresh chat that
did not build the branch (a stronger model is allowed for independent checks). It starts cold from this file, the job's brief and the job's report.

## Starting a review
`wsc jobs review` names the branch (`--id <id>` for a named one) and claims the round first: the remote ref `refs/claims/<id>/round-<n>` (core W27). A round
another session claimed within `[jobs] claim_hours` is refused naming it, so two reviewers never start one round; an unreadable origin refuses too. You must not
have built it: CI's `policy` check refuses a review written by a session that also wrote the report. The job's own brief is `jobs/<id>/brief.md` on that branch: it is what you check the work against, so nothing needs pasting.

## Rounds
A job gets at most 3 review rounds. Each round is a **fresh** session (never the builder, never a fixer, never an earlier round's reviewer: CI's `policy`
refuses a round whose session trailers meet the report's or an earlier round's, W27 rule B): `wsc jobs view --serve --auto`
starts one whenever a job branch's row says `review`, and `wsc jobs review` names the round. A non-merge verdict in round 1 or 2 hands the branch to a fix
session (`wsc jobs fix`), which appends `## Fix round N` to `report.md` and sets `review` again; the loop then starts the next round. Round 3 without
`merge` blocks the job for the owner.

## Setup
A **new** Claude Code session in the repo folder (never the one that built the branch): `git fetch`, check out the job branch, `git submodule update --init`
in a game repo. Follow the repo's `CLAUDE.md`. Read, in this order: `jobs/<id>/brief.md`, `jobs/<id>/report.md`, `jobs/<id>/handback.md` when there is one (the builder
subagent's own words; the report's `## Orchestrator additions` says what the orchestrator added, and `wsc jobs check` requires it), the repo's decisions file, then
`git diff --stat main...HEAD`. You did not build this branch: do not trust its report. Budget about 60 tool calls.

## Steps
1. **Run the machines first.** `wsc gates` and `wsc policy --branch job/<id> --base origin/main` (CI's `policy` check, run locally), plus any build or host
   tests the branch adds. Note failures, and any red check `wsc jobs review` lists for the pull request. Do not spend calls re-checking anything a gate covers.
   `policy` judges with the base's rules, never the branch's (C24): `git fetch` first; a branch that changes the rules gets a note, and its new rule is
   proven by its host tests, not by its own `policy` run.
2. **Claims against evidence.** Every claim in the report needs evidence you can open from `main`: a run report, a log, test output, a registry row with a
   date and run id. A claim with no evidence is a finding, however plausible. `policy` refuses a cited `runs/` folder that is in neither the head nor the base,
   and warns on a cited unmerged branch or unpushed commit (W27 rule D); a `merge` on a large diff whose round cites no run, CI run or test warns (rule E).
3. **The brief.** Every deliverable present, every stated decision followed, kill criteria respected, nothing outside scope. A deviation is fine only if the
   report names it and says why.
4. **Risk-first reading.** Pick the code where a mistake costs most (anything touching persistent data, install or uninstall, the PC, engine memory), say what
   you picked and why, and read it in depth. Skim the rest.
5. **Repeats.** Anything left as prose (a timing, a trap, a rule) that could be a default, a guard or a gate is a finding.

## Output
A verdict line, exactly `**Verdict: merge.**`, `**Verdict: merge after fixes.**` or `**Verdict: do not merge.**` (CI's `policy` check reads it: only `merge` lets
the branch merge), and findings ranked **blocker**, **should-fix**, **later**, each with `file:line`, what fails, and how to see it fail.

- Fix small should-fix items yourself on the branch only with the verdict `merge after fixes`: one commit each, with a test where the code allows, listed in
  the review; a fresh round then reviews your change. Under the core's rules `policy` refuses a `merge` round whose own commits change a file outside
  `jobs/<id>/` and the job's row (W27 rule A, W40; a game's `[policy] reviewer_code` may still warn). The fix: the round's own session changes its verdict
  to `merge after fixes`; once that session is gone, a fresh round goes on top, and its review clears the commits before it (an old round is never edited).
- A job that touches a workflow: check that its brief on the base named each file. `policy` only warns when it did not (W36), so clear that warning yourself: an unnamed workflow is a blocker unless you read it and it posts no check.
- Leave blockers and larger items as findings for the job chat.
- **Later** items for the core go to warscape-core `docs/BACKLOG.md` through a warscape-core pull request; for the repo itself, into the review.
- Write the review into `jobs/<id>/review.md` on the branch as a round section at the **top** of the file:
  `## Round N (YYYY-MM-DD, branch job/<id> at <sha>)`, with exactly one verdict line inside it. Rounds are newest first, numbered from 1 with no gap, at most 3;
  never edit an earlier round (in round 2 and 3, read it and check its findings were answered in `## Fix round N-1` of the report). `wsc jobs check`
  enforces the shape, and CI's `policy` check reads the newest verdict and refuses an earlier round changed on any commit of the branch, even if restored
  later (W27 rule C); only the newest round's own session edits it, until a newer round exists.
- Then set the row (`wsc reg set jobs <id> ...`), which `wsc jobs check` checks against the newest round:
  - `merge`: `status=done review=jobs/<id>/review.md`, then merge (below).
  - `merge after fixes` or `do not merge` in round 1 or 2: `status=fix review=jobs/<id>/review.md`. A fix session answers it.
  - the same in round 3: `status=blocked blocked_by="3 review rounds without merge" review=jobs/<id>/review.md`. The owner decides.
  - Any verdict but `merge` leaves the job's draft pull request open and a draft (never `gh pr ready`): its push-run checks stay on it.
- Before the verdict, read the branch's CI: `wsc jobs review` prints every check on its head that failed or is still running; a red required check is a
  blocker for a `merge` verdict.

## Merging (`merge` verdict only)
Commit the review and the row **locally, do not push yet**, then in this order:
1. `wsc policy --branch job/<id> --base origin/main` on the local branch (it must say ok);
2. `gh pr view job/<id>` (the builder opened it as a draft when the job reached review; if there is none: `gh pr create --draft --base main --head job/<id>
   --title "<id>: <title>"`, body = the review's verdict and findings);
3. `gh pr ready job/<id>`: a draft skips CI's `policy` and a skipped check counts as passed, so the pull request is marked ready **before** the push; the
   pushed head then gets a real `policy` run (`synchronize` on a non-draft pull request) and auto-merge cannot land on a skipped one. The `ready_for_review` run
   on the old head has no merge verdict and is red by design: the push usually cancels it, and the `notify` job does not comment on it;
4. `git push`;
5. `gh pr merge job/<id> --auto --squash`. GitHub merges only when every required check is green on that commit: do not wait or poll. A check that fails leaves the
   pull request open: CI comments on the pull request (`wsc ci notify`) and `wsc jobs next|review|view` list it first, so the next session sees it. Any other
   verdict is never merged. A `brief/` branch merges the same way without a review; `plan/` and `meta/` branches still wait for the owner.

The required checks are the job names the rendered workflows define: `gates`, `policy` and any slow job the repo keeps (`docs/CONSUMING.md`, "The job pipeline").

## Keeping this file useful
When a review finds something a gate could have caught, the fix is a new gate, not a longer checklist here.

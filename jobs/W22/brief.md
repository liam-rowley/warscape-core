# W22: Main health: a red required check on main is rerun and reported

Model: Sonnet, reason: none needed (Sonnet is the default). Workflow render blocks, one new library module, one verb action and a readiness line, all
standard-library Python with host tests; no DLL input changes, no PC. Budget about 90 tool calls (CI round trips included: a workflow change is proved
only by pushes, and the issue calls only by a push to `main`, which the builder cannot make; see "Tests and acceptance"). At the cap, stop, commit, and
report what is left.

## Goal
Audit 2026-11-03 (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`), finding **P1 (blocker): a red required check on `main` is permanent and
silent**, and automation item 6 ("Main health"). Today a set that fails on `main` is never run again and nobody is told:
- A push to `main` diffs against `$BEFORE` (`.github/workflows/gates.yml` line 45, from `warscape/ci_render.py` `block_changes`). A set whose inputs did not
  change since the previous `main` commit is skipped, and a skipped job counts as passed, so `main` shows green on top of a red tip.
- Pass markers are saved only on success (`ci_render.py` lines 84-93, `block_pass_marker`), and a skip never looks for one on `main`.
- `notify` skips `main` (`ci_render.py` lines 131-132: `github.ref != 'refs/heads/main'`), and `jobs next|review|view` read open pull requests only
  (`warscape/jobq.py` lines 365-379, `red_prs`), so a red `main` reaches no one.
- Seen three times, all a `www.lua.org` download timeout in `proxy/tools/build.sh all`: napoleon's proxy on `main` went red at J24's merge (run
  41664906781) and every later `main` push skipped it; the core's went red at v0.16.0 (run 41716930333) and at W19's merge (run 41736312172). A rerun of
  41664906781 on 2026-11-04 was green: the code was fine, only the red was invisible. (W21 added the fetch retry that makes the timeout rarer; this job
  makes any red on `main` loud and self-healing.)

Three changes, one per place the signal is lost:
1. **Rerun:** a push to `main` runs a set whenever there is no pass marker for its input tree in `main`'s scope.
2. **Report:** a workflow job on `main` opens or updates one issue per red required job, and closes it once the job is green.
3. **Read:** `jobs next`, `jobs review` and `jobs view` print `main`'s state first.

## What exists (read before building)
- `docs/CONSUMING.md` "The job pipeline" (the `[ci]` keys, the render blocks, "Settings only the owner can make"); `jobs/W21/brief.md` and `report.md`
  (the push-only pipeline, `changes`, pass markers, `check-settings`, `required_checks`: this job extends them); `docs/REVIEW.md`.
- `warscape/ci_render.py`: `block_changes` (the `diff` step picks `base` at lines 49-51 of the file as rendered: `base=$BEFORE` on `main`, the merge base
  elsewhere), `block_pass_marker`, `block_notify` (lines 125-141), `expand`. `ci/gates.yml.in` ends with `{{wsc notify gates needs=changes,gates,proxy,harness-windows}}`;
  `ci/policy.yml.in` owns `pull_request` and is untouched. The rendered `.github/workflows/gates.yml` is a gate: `ci_render` fails when it differs.
- `warscape/ci.py`: `notify` (the PR comment; `MARK`, `failed(jobs)`, `gh(args, run=...)` the injectable runner), `tree_hashes` (an empty hash means "no
  marker can match: the job runs"), `classify` (`files is None` means the base is unknown: everything changed).
- `warscape/ci_settings.py` (`workflow_jobs`, `read_jobs`, `SKIP = ('changes', 'notify')`, the expected-check derivation) and `[ci] required_checks`
  (`wsc.toml`, `warscape/repo.py` `DEFAULTS`): the list of check names this job reuses as "the required jobs".
- `warscape/jobq.py`: `red_prs`, `print_red_prs`, `failed_prs`, `check_lines`, `branch_checks`, `render_view(..., root=, ctx=)`; `warscape/verbs/jobs.py`
  line 100 (`J.print_red_prs` runs before `next`, `review`, `fix` and the static `view`; `view --serve` builds its page in `JobServer.page`).
- Tests: `tests/test_ci.py` (the golden render hashes at `GOLDEN`, line 308; the workflow-block tests; check-settings on recorded JSON),
  `tests/test_jobs.py` (`red_prs`, `branch_checks` with an injected `run`, lines 385-463).
- Citations checked against the tree at 0.22.0 on 2026-11-04: `gates.yml:45`, `ci_render.py:84-93`, `ci_render.py:131-132` and `jobq.py:365-379` all
  still point at what the row says. (The audit's own line numbers for `ci.py`/`ci_render.py` are older, napoleon's pin; use these.)

## Decisions already made (follow them; a deviation goes in the report with its reason)
### 1. Rerun: a push to main is judged by markers, not by the previous commit
1. **On `main`, `changes` forgets the base.** In `block_changes` the `diff` step uses `base=''` when `$GITHUB_REF` is `refs/heads/main` (so `wsc ci inputs`
   reports every set as changed, its existing "base unknown" path), and the marker lookup then decides. `$BEFORE` stays for nothing: remove the env line and
   fix the block's comment. Branch pushes are unchanged (merge base with `origin/main`).
   - Reason: the one rule "a set runs unless a marker proves its tree passed" needs no new input. A marker is an `actions/cache` entry, and a cache entry
     saved on `main` is visible to later `main` runs; entries saved on a branch are not visible to `main` (GitHub scopes a cache to its own ref and to its
     base ref and default branch, not the other way round). So the lookup on `main` is "in `main`'s scope" with no extra key.
   - Consequence, accepted: a squash merge is a tree `main` has not passed, so it runs, as it does today. A docs-only push to `main` finds its predecessor's
     marker and skips, and the step summary names the run that passed the tree (existing `decide()` text).
2. **A skip counts as passed only when such a marker exists.** After decision 1 this is true by construction (`decide()` writes `<set>=false` only when
   the cache hit and the marker file's `run=` line are both there; otherwise the set runs). A host test must prove it from the rendered text: on `main`
   the only route to `false` is the marker branch, and a set with an empty tree hash or no `cache-hit` runs.
3. **A failed run saves no marker** (unchanged: `pass_marker` is `success()` only), so the next push to `main` reruns the set. That is the "rerun". A
   cache eviction (GitHub drops entries unused for 7 days) costs one extra run of a slow job on `main`, never a wrong skip. Nothing else is added to
   rerun a red run that has no later push (open question 1).
4. **Fail-safe stays:** each slow job's `if:` keeps `!cancelled()` and runs when `changes` did not succeed.
5. **Render blocks other than `changes` and `notify` stay byte for byte** (`if`, `pass_marker`, `fetch_cache`, `policy`). The `changes` text changes on
   purpose (decision 1); the `notify gates` branch-comment job keeps its exact text (decision 7). Say so in the report; the golden hashes at `GOLDEN` are
   updated for the intended change only, and a new test pins the `notify` job, `if`, `pass_marker`, `fetch_cache` and `policy` text separately so no
   other part moved.

### 2. Report: `wsc ci main-health`, run by a workflow job on main
6. **A new action of the `ci` verb**, `wsc ci main-health --run-id N [--attempt A] [--repo owner/name] [--dry-run]` (`warscape/verbs/ci.py`, its header lines;
   logic in a new `warscape/ci_main.py`, `gh` through `ci.gh(args, run=...)` so tests inject answers). It reads the run's jobs
   (`GET repos/{r}/actions/runs/{id}/attempts/{a}/jobs?per_page=100`), keeps the **required jobs**, and for each one opens, updates or closes its issue.
   - **Required jobs** = the names in `[ci] required_checks` that the run produced (a check no push run makes, like `policy`, is ignored); when
     `required_checks` is empty, every job of the run but `changes`, `notify` and `main_health`. One function in `warscape/ci_settings.py` or `ci.py`
     answers it for both this verb and the readiness line (decision 10): do not write the rule twice.
   - **State per job:** `failure`, `timed_out`, `startup_failure` are red; `success` and `skipped` are green (a skip on `main` means a marker proved the
     tree, decision 2); anything else (cancelled, still running, no conclusion) is left alone: neither opens nor closes.
   - **One issue per job name.** Title `CI is red on main: <job name>`; the body starts with the hidden mark `<!-- ci_main job <job name> -->` and the first
     red run's link, commit, failed step (first failed step name, as `ci.failed`) and the hint for the job (`ci.class_hint`, the same `[ci] hints` as the PR
     comment, with the branch `main`), then one line telling the reader to rerun the failed jobs of the run (`gh run rerun <id> --failed`) or push to `main`,
     and that the issue closes itself once the job is green.
   - **Open issues are found by the hidden mark** in `gh issue list --state open --limit 200 --json number,title,body` (never by title search: GitHub's
     search is fuzzy), not by a label, so no label has to exist. Match the whole mark.
   - **Idempotent.** Red with no open issue: `gh issue create`. Red with an open issue: add one comment per `(run, attempt)` carrying
     `<!-- ci_main run N attempt A -->`, and skip when a comment with that mark exists (a rerun of the job step must not double-post). Green with an open
     issue: one comment "green in run N (commit)" and `gh issue close`. Green with none: nothing. The verb prints one line per job and what it did.
   - **A stale run does nothing.** Before acting it reads `GET repos/{r}/commits/main` (`sha`) and the run's `head_sha`; when `main` has moved on, it prints
     "main moved to <sha7>; the newer run decides" and exits 0, so an older run that finishes late cannot reopen or close an issue out of order.
   - **Never fails the workflow for a gh problem** it can explain (no issue permission, issues disabled, rate limit): print the reason and exit 0 for
     those, exit 2 only for bad arguments. The job is also `continue-on-error: true` (decision 7), so a fault here never turns `main` red.
7. **The render block `notify gates needs=...` emits a second job, `main_health`**, after the existing `notify` job (whose text does not change). The
   consumers' templates do not change: they re-render. `main_health`:
   `needs: [<the same needs>]`, `if: always() && github.event_name == 'push' && github.ref == 'refs/heads/main'` (**not** `failure()`: closing needs green
   runs; `always()` also runs when a needed job failed, and a cancelled run is handled by the verb), `continue-on-error: true`, `runs-on: ubuntu-latest`,
   `timeout-minutes: 5`, `permissions: contents: read, issues: write, actions: read`, the same checkout (with `submodules: true` and the token for a game),
   and one step with `GH_TOKEN: ${{ github.token }}` running `<wsc> ci main-health --run-id ${{ github.run_id }} --attempt ${{ github.run_attempt }}
   --repo "${{ github.repository }}"`. Its job id `main_health` is excluded from the required-job derivation and from `check-settings`' notes (add it to
   `SKIP`). It is not a required check (a game's ruleset names the checks; `main_health` is not among them).
   - Reason for a second job and not a widened `notify`: the two have different permissions (`pull-requests: write` vs `issues: write`) and different
     triggers, and the PR job's text must not move (decision 5).
   - `notify policy` (the pull-request workflow) is unchanged.
8. **`check-settings` gains one line:** `has_issues` false in `GET repos/{r}` (already read) is a `problem` ("issues are disabled: `main_health` cannot
   open an issue for a red main"). No other settings change; the verb stays read-only. Add the case to the recorded-JSON tests.

### 3. Read: jobs next, review and view show main first
9. **`jobq.main_health(ctx_or_cfg, root, offline, run=subprocess.run)`** returns a list of lines, never raises, and never makes a command fail:
   - `offline` returns `[]` quietly (as `red_prs`); no `gh`, not logged in, any error, bad JSON: **one** line
     `(main's CI state is unknown: <why>; --offline skips this)`. "Unknown" is the only report when it cannot be read.
   - Otherwise, for each workflow in `[ci] workflows`: `gh api "repos/{owner}/{repo}/actions/workflows/<name>/runs?branch=main&event=push&status=completed&per_page=1"`
     (the latest **completed** push run on `main`; a workflow with no such run, like the pull-request-only `policy.yml`, is skipped), then
     `gh api repos/{owner}/{repo}/actions/runs/<id>/jobs?per_page=100`. The required jobs of decision 6 that are red give one line each:
     `main is RED: <job> failed in run <id> (<html_url>), commit <sha7>, <date>: rerun it or push to main; an issue tracks it`. The latest completed run
     is the one that counts for every job of its workflow.
   - A run that is newer but still in progress is not read; the line may be a run behind. That is deliberate (the issue and the next push decide).
10. **Where it prints:** `warscape/verbs/jobs.py` calls it before `print_red_prs` (line 100), so a red `main` is the first thing `next`, `review`, `fix` and
    the static `view` print: `Main CI is red (fix or rerun before a merge verdict):\n  <lines>`; the "unknown" line prints as it is; green prints
    nothing in the terminal. `view` (static and served) also puts one line in the page head: red lines in the page's existing warning style, or "main CI:
    green (run N)" / "unknown". `view --serve` memoises the answer for 60 seconds so a page refresh costs no extra `gh` call. `--offline` skips every call.
    Nothing here refuses, blocks or reorders a job: it prints, because "the next job is the fix" is the owner's call.
11. The legacy case (a skip on a tip that a pre-W22 run left red) cannot be detected from the API: do not try. The first `main` push after this merges
    reruns the sets anyway (the workflow files are inputs of both sets), which is the first honest answer.

### 4. Consumers
12. Everything renders for a consumer game: `core` prefix (`python3 core/wsc.py`), the token for a private core, `[ci] required_checks` or the derived
    list. The napoleon fixture (`tests/fixture_game/ci/gates.yml.in`, a game with `core = 'core'`) must render `main_health` with the core prefix and the
    checkout `submodules: true`. A game's `wsc.toml` needs no new key; a game's template needs no new placeholder (the `notify gates` block grows).
    `ci.py`/`ci_main.py` must name no game and no game path.
13. **No DLL input changes.** `proxy/tools/build_id.py --inputs` (with `WSP_GAME_ROOT=proxy/tests/null_game`) must print the same object ids as `main`;
    this job edits nothing under `proxy/`.

## Scope: files this job touches
`warscape/ci_render.py` (`block_changes`, `block_notify`, docstring), `ci/gates.yml.in` (header comment only; the placeholders already exist),
`.github/workflows/gates.yml` (rendered), `warscape/ci_main.py` (new), `warscape/ci.py` or `warscape/ci_settings.py` (the shared required-jobs rule),
`warscape/ci_settings.py` (`SKIP`, `has_issues`), `warscape/verbs/ci.py` (the action and its header lines), `warscape/jobq.py` (`main_health`,
`print_main_health`, the page line), `warscape/verbs/jobs.py` (the call; header text), `registries/tools.jsonl` (the `wsc.ci` and `wsc.jobs` rows after
their headers change), `tests/test_ci.py`, `tests/test_jobs.py`, `tests/test_ci_main.py` (new), `docs/CONSUMING.md` ("The job pipeline": a main-health
bullet, the `main_health` job and `issues: write`, the settings bullet), `VERSION`. Not `proxy/`, not `policy.yml.in`, not `registries/jobs/`.

## Steps
1. Read "What exists". Run `python3 wsc.py gates --fast` once for a baseline.
2. **Failing tests first**, committed red:
   - `tests/test_ci.py`: on a `main` push the rendered `changes` step passes no `$BEFORE` base (`base=''`) and the only route to `<set>=false` is the
     marker branch; on any other branch the merge-base logic is unchanged; the render pins for `notify`, `if`, `pass_marker`, `fetch_cache` and `policy`
     (decision 5); `notify gates` renders both jobs with the exact `if`, `continue-on-error`, `permissions` and the core prefix for a game
     (`core = 'core'`) and without it for the core; `check-settings` with `has_issues` false (a problem) and true.
   - `tests/test_ci_main.py` on recorded `gh` answers (an injected runner, like `test_ci.py`): red with no issue opens exactly one (`gh issue create` argv
     has the title and the hidden mark); red with an open issue comments once and a second call with the same `(run, attempt)` posts nothing; two red jobs
     open two issues; green closes the open issue with one comment and leaves others open; green with none does nothing; cancelled and in-progress jobs
     change nothing; a job named in `required_checks` that the run did not produce is ignored; empty `required_checks` derives; a stale run (main's sha
     differs from the run's) does nothing; issues disabled / permission denied / no `gh` print the reason and return 0; `--dry-run` posts nothing.
   - `tests/test_jobs.py`: `main_health` on recorded answers: red (one line per red required job, run id, URL, commit), green (`[]`), a workflow with no
     completed run skipped, offline (`[]`, no call), no `gh`, not logged in, bad JSON (each exactly one "unknown" line, no exception), a newer in-progress
     run ignored; the lines print before the pull-request lines in `jobs next`, `review` and the static `view` (stub `run`).
3. Build decision 1 (the render), `python3 wsc.py ci render`, commit template and workflow together. Then `ci_main.py` and its verb action (2), then the
   job block (7) and `check-settings` (8), `ci render` again. Then `main_health` and its prints (3). Each its own commit.
4. Push early (the first push of the new workflow is the proof). Read the run on the branch: it must be a normal branch run (the new `main_health` job is
   `skipped`, not red; `notify` unchanged). Show with `gh run view` that `main_health`'s `if` skipped on a branch push.
5. **The main-side proof the builder cannot make** (a push to `main` is the reviewer's merge): run the verb by hand against recorded answers and, read-only,
   against live ones: `python3 wsc.py ci main-health --run-id <the latest completed gates run on main> --repo <this repo> --dry-run` prints what it would do
   and posts nothing; run `python3 wsc.py jobs next` and `jobs view --no-open --offline` and without `--offline` and paste the main-health lines. Put the
   `--dry-run` output in the report. The real first push to `main` after the merge is the reviewer's check (list below).
6. Docs, `VERSION`; `python3 wsc.py gates` (full) and `python3 wsc.py policy --branch job/W22 --base origin/main`.

## Tests and acceptance
- New host tests red first, then green; `python3 wsc.py gates` green (the `ci_render` gate proves the committed workflow equals its render).
- The branch's CI run id, with `main_health` skipped, and the `build_id.py --inputs` comparison with `main` (decision 13).
- What cannot be run in CI and is covered by the recorded-answer tests: the issue calls and the `main` push route. Say in the report what was and was not
  run live. **For the reviewer, after the merge:** (a) the first push to `main` runs `proxy` and `harness-windows` (the workflows changed) and writes
  their markers; (b) a docs-only push to `main` after it skips both, naming the run that passed the tree; (c) `gh issue list` shows no issue while
  `main` is green; to see the open/close path once, re-run a failed `main` job or push a deliberately failing commit only if Liam asks (not part of this
  job's proof).

## VERSION
A minor bump (a new verb action, a new render job, a new readiness line). `origin/main` says 0.22.0 when this brief was written, so 0.23.0 if nothing
else has bumped; the job rows W23 to W35 may also bump. Re-read `origin/main` `VERSION` and the open `job/*` branches before the last commit; the second
to merge takes the next free number and merges `main` (never rebase). Say which number you took. Tags are Liam's.

## What consumers must do after the tag (napoleon-remastered)
- Bump the pin (the audit sequences it with J78), then `python3 core/wsc.py ci render` and commit the rendered `gates.yml` with the pin and
  `wsc.toml` `[core] version` in one commit (B9). Nothing in the template changes by hand: the `changes` step and the `notify` block render differently.
- No acceptance run for this tag alone: no DLL input changes (decision 13).
- **For Liam (settings, his to change):** issues must be enabled in the repository (`wsc ci check-settings` now says when they are not); the workflow
  asks for `issues: write` per job, so no repository-wide token setting changes. The job changes no setting.

## Kill criteria
- The `changes` edit changes a branch push's decision (a docs-only branch push runs a slow job, or a changed set is skipped without a marker): stop and fix
  before anything else; branch behaviour must be byte-identical in the rendered text apart from the `main` branch of the `diff` step.
- A step needs a DLL input (`proxy/`): stop; there is none by design.
- `main_health` can turn a run red or block a merge (not `continue-on-error`, or listed as a required check): stop.
- The verb can open a second issue for the same job, or close an issue it did not open: stop and report with the recorded answers that show it.
- Core CI red after three fix attempts for a cause in this change, or about 90 calls: stop and report. Version collision as in VERSION; never rebase a
  pushed branch.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **Should `main_health` also rerun a red run once by itself** (`gh run rerun <id> --failed`, needs `actions: write`)? The three known reds were download
   timeouts a rerun fixed. Recommended: no. W21's retry removes most of them, an automatic rerun can hide a real flake rate and loops on a real failure,
   and the issue plus the next push already rerun the set. Revisit if issues for download timeouts keep arriving after W21.
2. **Labels or assignees on the issue?** Recommended: none (a label must exist first; the hidden mark is the key). The title prefix `CI is red on main`
   is searchable.
3. **Should `jobs next` refuse to hand out work while `main` is red?** Recommended: no, print only (the audit asks for "print a red `main` first"). A
   queue that stops on a transient red stalls every other job; the owner decides.
4. **Required set from `required_checks` or from the run?** Recommended: `required_checks` when set (it is what the ruleset requires, decision 6), the run's
   jobs otherwise; the two agree after `check-settings` is clean.
5. **File overlap with the other core rows**, for whoever merges second (merge `main`, never rebase): rows touching `warscape/ci.py`, `ci_render.py`,
   `ci_settings.py`, `jobq.py`, `verbs/jobs.py` or `verbs/ci.py` (W23 to W35: re-read `docs/BACKLOG.md` and the open `job/*` branches before the last
   commit); W20 may add packages to the `proxy` job in `ci/gates.yml.in`: re-apply to the template and re-render. All rows: `docs/CONSUMING.md`, `VERSION`.

## Finish
Report in `jobs/W22/report.md` (what was built per decision, tests red then green and where they ran, the branch run id and the skipped `main_health`, the
`--dry-run` and live `jobs` outputs, the `build_id.py --inputs` comparison, the version taken, deviations, open questions, what napoleon and Liam must
do and what the reviewer checks on the first `main` push), then `wsc reg set jobs W22 status=review report=jobs/W22/report.md` (`python3 wsc.py`).
Push `job/W22`, open the draft pull request, and stop: an independent reviewer merges (C18); Liam tags.

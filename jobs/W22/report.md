# W22 report: Main health: a red required check on main is rerun and reported

Written by the orchestrator from the builder subagent's hand-back, because the harness refuses a subagent's write of a report file. The
text is the builder's own, apart from this note and two notes marked "orchestrator note". Branch `job/W22`, VERSION 0.23.0.

## What was built
1. **A red set on `main` is rerun.**
   - `warscape/ci_render.py` `block_changes`: on `refs/heads/main` the `diff` step now passes `base=''`. `wsc ci inputs` then reports
     every set as changed through its existing "base unknown" path, and the marker lookup decides.
   - The `BEFORE` env line is gone and the block comment is rewritten. Branch pushes still use the merge base with `origin/main`.
   - `decide()` writes `<set>=false` only when both the cache hit and a `run=<digits>` marker line are present; a host test runs the
     rendered function in bash to show it.
   - A failed run saves no marker, so the next push to `main` reruns the set.
   - The `if`, `pass_marker`, `fetch_cache` and `policy` text is unchanged.
2. **Red jobs on `main` are reported.** New `warscape/ci_main.py`, and the `main-health` action of `wsc ci` (`--run-id`, `--attempt`,
   `--repo`, `--dry-run`; exit 2 without `--run-id`).
   - **Opening.** One issue per red required job, titled `CI is red on main: <job>`, whose body starts with the hidden mark
     `<!-- ci_main job <job> -->`. The body carries the run link, the commit, the first failed step, `ci.class_hint` (branch `main`)
     and the lines on rerunning and self-closing.
   - **Matching.** Open issues come from `gh issue list --state open --limit 200 --json number,title,body`. A match is the whole mark at
     the start of the body, not a substring: `gates` never matches `gates (windows)`, and an issue that merely quotes the mark is not
     ours.
   - **Updating and closing.**
     - Still red with an issue open: one comment per (run, attempt), marked `<!-- ci_main run N attempt A -->`.
     - Green with an issue open: one comment, also marked, so a retry after a failed close does not double-post; then `gh issue close`.
   - **No-ops.**
     - A cancelled, in-progress or neutral job changes nothing.
     - A run that is not `main`'s tip prints "main moved to <sha7>; the newer run decides" and does nothing.
     - Every `gh` problem it can explain (issues disabled, 403, rate limit, no `gh`, an unexpected answer) prints the reason and exits 0.
   - **Which jobs count.** One function decides: `ci.required_jobs(cfg, jobs)`. It returns the `required_checks` names the run produced,
     or else every job but `changes`, `notify` and `main_health`. `ci.SKIP`, `ci.RED` and `ci.GREEN` are shared, and
     `ci_settings.SKIP = ci.SKIP`.
3. **The `main_health` job.** `block_notify` for `gates` now renders the unchanged `notify` job, then `main_health`:
   - `needs`: the same list;
   - `if: always() && github.event_name == 'push' && github.ref == 'refs/heads/main'`;
   - `continue-on-error: true`, with a 5-minute timeout;
   - permissions `contents: read, issues: write, actions: read`;
   - the same checkout (`submodules: true`, plus the token for a game), and one step with `GH_TOKEN` that runs
     `<wsc> ci main-health --run-id ... --attempt ... --repo ...`. The core prefix comes from `_wsc(cfg)`.
   - `notify policy` is unchanged. `main_health` is in `SKIP`, so `check-settings` never expects it, requires it or notes it.
   - The rendered `.github/workflows/gates.yml` and the `ci/gates.yml.in` header comment are updated.
4. **check-settings.** `has_issues: false` in `GET repos/{r}` is a problem ("issues are disabled: `main_health` cannot open an issue
   for a red main ..."). An absent or true value is fine, which keeps the recorded answers that carry no `has_issues` valid.
   Orchestrator note: both repos had `has_issues: true` on 2026-11-04.
5. **Reading `main`'s state.**
   - `jobq.main_state`, `main_health`, `print_main_health` and `main_html` read, for each workflow in `[ci] workflows`, the latest
     completed push run on `main` and that run's jobs.
   - A red required job prints `main is RED: <job> failed in run <id> (<url>), commit <sha7>, <date>: rerun it or push to main; an issue tracks it`.
   - Any failure to read prints exactly one line, `(main's CI state is unknown: <why>; --offline skips this)`. `--offline` makes no
     call.
   - `verbs/jobs.py` prints this before `print_red_prs` for `next`, `review`, `fix` and the static `view`.
   - The page head gets one warning line per red job, or "main CI: green (run N)", or "unknown". `JobServer(main_line=, clock=)`
     memoises the answer for 60 s.

## Evidence
- **Tests, red first.** Commit 322423e had 6 failures and 11 errors across `test_ci`, `test_ci_main` and `test_jobs`, because the code did
  not exist yet. After the build commits, `tests.test_ci`, `tests.test_ci_main` and `tests.test_jobs` pass together: 143 tests.
- **Full gates.** `python3 wsc.py gates`: 13 ok, 1 warn, 0 failed in 89.6 s. The warn is the `tests` gate: 609 passed and 5 skipped (the
  POSIX hook test, and 4 capstone cases with capstone not installed here).
- **The verb, live and read-only.** `python3 wsc.py ci main-health --run-id 41794226903 --repo liam-rowley/warscape-core --dry-run`,
  against the latest completed `gates` push run on `main`, printed green with no open issue for `gates (windows-latest)`,
  `gates (ubuntu-latest)`, `proxy` and `harness-windows`. `policy` was ignored, because that run did not produce it.
- **The readiness line.**
  - `python3 wsc.py jobs view --no-open --offline` printed no `main` line.
  - Without `--offline`, the page head shows `main CI: green (run 41794226903)`.
  - `jobs next` printed nothing for `main` (green), and the pull-request lines as before.
- **DLL inputs untouched (decision 13).** `git diff --name-only origin/main -- proxy` is empty. `build_id.py --inputs` itself reported
  "proxy/null (adapter) is not tracked at HEAD" for the null game here, so there is no id comparison.
- **Not run live.** The issue calls (`create`, `comment`, `close`) and the main-push route. Recorded-answer tests cover them.
- **Orchestrator note.** This branch's CI run, where `main_health` should show as skipped, is the first run on the pull request.

## Deviations from the brief, and why
- **Commits.** Commits 2 and 3 of step 3 are one commit (d190a9b): the `changes` render and the `main_health` job block touch the same
  rendered file. The verb, the readiness line and the docs are separate commits.
- **Step 4 not done here.** Pushing early and reading the branch run (the `gh run view` proof) fell to the orchestrator, who pushes the
  branch.
- **Golden hashes retaken.** The `GOLDEN` hashes for `fixture_game gates.yml`, "all blocks, a game" and "all blocks, the core" were
  retaken for the intended change: the `changes` diff step and the `main_health` job. `fixture_game policy.yml` is unchanged.
  - A new test pins, separately for a game and for the core, the `if`, `pass_marker`, `fetch_cache`, `policy` and `notify policy` text
    and the old `notify` job, so nothing else moved.
- **`print_main_health` is called with `ctx.config['ci']`.** The existing review and fix print test now stubs it, and its ctx gains
  `ci`. No behaviour change.
- **Comment wording.** The texts of the `main-health` comments and the green-comment mark are the builder's wording. The brief fixes the
  open, comment and close behaviour, not the text.
- **VERSION 0.23.0, as the brief says.** `origin/main` is 0.22.0, and W20 and W30 also hold 0.23.0 on their branches, so the
  orchestrator renumbers at merge.

## Open questions
- **The brief's open questions**, answered by following its recommendations:
  1. No automatic rerun.
  2. No labels or assignees.
  3. Print only: `jobs next` does not refuse work while `main` is red.
  4. Use `required_checks` when it is set, else the run's jobs.
  5. Merge `main` (never rebase) when overlapping rows W23 to W35, or W20's `proxy` packages, change the template.
- **New.** More than 200 open issues would hide an older one from `issue list --limit 200`. That is not expected.

## What napoleon and Liam must do
- **napoleon:** bump the pin, run `python3 core/wsc.py ci render`, and commit the rendered `gates.yml` together with the pin and
  `wsc.toml` `[core] version`, in one commit (B9).
- **Liam:** Issues must be on in each repository; `wsc ci check-settings` now says when they are off. No other setting changes, and the
  job asks for `issues: write` per job.

## For the reviewer, on the first push to main after the merge
- (a) `proxy` and `harness-windows` run and write markers, because the workflows changed.
- (b) A docs-only push to `main` after that skips both, and its step summary names the passing run.
- (c) `main_health` is green or skipped, never red, and `gh issue list` shows no `CI is red on main` issue while `main` is green.

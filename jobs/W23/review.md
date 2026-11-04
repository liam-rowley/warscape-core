# W23 review

## Round 1 (2026-11-04, branch job/W23 at 0b647ca)

**Verdict: merge.**

Reviewer: a fresh session (not the builder, session 3815a970 on every branch commit), against `jobs/W23/brief.md`.

### Machines
- `python3 wsc.py gates` on this PC (Windows, 2026-11-04, at 0b647ca): 12 ok, 3 warn, 0 failed in 156.2 s.
  - 625 host tests passed, 5 skipped (the POSIX-sh hook test and four capstone tests).
  - `ci_render` warns about the bootstrap trigger, as the brief intends (decision 9; W27 removes it).
  - `hooks` warns only because this review worktree's `core.hooksPath` is absolute.
- `python3 wsc.py policy --branch job/W23 --base origin/main` before this review gave the three expected refusals (review, `done`), then the fallback
  note "no JUDGE_API at dcf2f84de392", then `REFUSED (23 files changed)`. That is decision 6 working: main predates W23.
- CI on 0b647ca: `changes`, `gates (ubuntu-latest)`, `gates (windows-latest)` and `proxy` are green. `harness-windows` was still running at verdict
  time, so the auto-merge waits on it.
- The bootstrap trigger works. PR #69 has one `policy` run, event `pull_request` (run 41802161474), skipped while the PR is a draft. There is no
  `pull_request_target` run, as main's file has none. The `gh pr ready` + push in the merge steps give it the real run that kill criterion 5 asks for.

### Brief against the work
- Every deliverable is present: the judge (`warscape/policy.py`), the parent (`warscape/policy_base.py`), the verb flags, the CI blocks and the render
  guard, both templates, the tests, docs, C24 and VERSION 0.26.0.
- Each deviation is named in the report with a reason:
  - the split into `policy_base.py`;
  - `--no-renames -z`, which closes a rename bypass the report proves red on f879196;
  - `-X utf8`;
  - a verdict needs both the exit code and the verdict line;
  - the segment-glob change to `test_plan_and_meta_scopes`.
- The red commit is e1d7fb3. I did not re-run it.

### Risk-first reading
I read `warscape/policy_base.py` and the rendered `.github/workflows/policy.yml` in full, and the diffs of `policy.py`, `verbs/policy.py` and
`ci_render.py`. These are where a mistake is a bypass or a privileged-code-execution hole. What I checked:
- **The parent never runs the head.** The core that judges is the base sha, or the base gitlink's pin, read from the submodule's object store. In a
  game, `--show-toplevel` must equal `core/`. `JUDGE_API` is read from that pin, and the child is `-I` from the extracted tree. In CI, the parent itself
  is the base checkout (`pull_request_target`), so a head `[cli] verb_dirs` module never loads.
- **A forged verdict line is refused.** The parent accepts only `(0, ['ok'])` or `(1, ['REFUSED'])` from the child. If head text echoed into a message
  forged an `ok` line beside a real `REFUSED`, the parent sees two verdicts and refuses.
- **The workflow.** No `${{ }}` sits in any `run:` line; the head's names arrive through `env:`. There is no checkout of the head, no cache, and
  `permissions: contents: read`. The `notify` job runs the base's code with the branch name through `env:`.
- **Fails closed.** Each failure path in `judge` ends in `refuse`, and `CalledProcessError` is caught as a refusal. Tests cover a base without a
  gitlink, a missing pin, an unparsable `wsc.toml`, a raising `check` and a bad base.
- **The tests are adversarial.** The repointed-gitlink test plants a sentinel that would appear only if the head's core ran. The `ctx.root` test runs
  inside an enclosing repo, which proves the ceiling.

### Findings
No blockers and no should-fix items.

**Later** (for the core's BACKLOG through the orchestrator's next core plan branch, beside open question 2. `docs/BACKLOG.md` is at 29.5 KB of the
30 KB `doc_size` limit, so that branch needs to prune first):
1. `warscape/ci_render.py:213` `guard` looks for the word `pull_request_target` anywhere outside comments, not as a key under `on:`.
   - What fails: a template with `on: pull_request` and a step `if: github.event_name == 'pull_request_target'` passes the guard.
   - How to see it fail: `guard('on:\n  pull_request:\njobs:\n  x:\n    if: github.event_name == \'pull_request_target\'\n{{wsc policy}}\n', 't')`
     returns no error, only the bootstrap warning (checked 2026-11-04 on 0b647ca).
   - Cost: low. A template change is itself judged by the base, and the rendered file is reviewed.
2. The bootstrap `pull_request` trigger (`ci/policy.yml.in`) is the cheapest form of the accepted forged-check residual while it stays on main.
   - What fails: a head can drop its own copy's path filter and get a second, head-controlled `policy` check beside main's `pull_request_target` one.
     No new workflow file is needed.
   - Both triggers also share one `concurrency` group with `cancel-in-progress`, so a pull request that fires both cancels one of them.
   - Fix: W27 removing it soon closes both.
3. `docs/CONSUMING.md` is 29.4 KB of 30 KB: the next consumer-facing change will need a split or trim.
4. VERSION 0.26.0 and C24 are also held by `job/W10` (checked: W10's VERSION reads 0.26.0). W23 merging first means W10 renumbers to 0.27.0 and
   C25, as the report's open question 4 says.

### The report's open questions
These are for Liam and the orchestrator; none blocks the merge.
- Question 1 (non-main bases): pinning the judge to the default branch is the safer later row.
- Question 3 (about 65 s of test time): acceptable for now. The full tests gate took 155 s here.

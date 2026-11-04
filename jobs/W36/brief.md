# W36: Policy and hook follow-ups: workflow edits on job branches, global-option-aware commit match, non-main bases

Model: Opus, reason: policy enforcement (napoleon D52). This job adds a refusal to the check that decides what reaches `main` unreviewed, and changes
the judge's parent, which every consumer's `policy` job runs; a hole or a false refusal is a bypass or a blocked pull request. Budget about 110 tool
calls: about 15 for reading and the false-positive scan, 25 for the red tests, 30 for the three changes, 20 for docs, rows and gates, 20 for CI round
trips. At the cap, stop, commit, and report what is left.

## Goal
Three follow-ups raised by the audit (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`, P2 and the bypass-5 neighbourhood) and by the W23 and
napoleon J76 builders. W23 and W27 are `done`; this builds on `warscape/policy.py`, `warscape/policy_base.py` and `warscape/trailer.py`.
1. **Forged status (W23 report, open question 2; Liam accepted the residual on 2026-11-04 with this follow-up).** Any write token can post a status named
   `policy`. A job branch that adds a workflow posting a fake check would defeat it. A `job/` branch may not add, change, delete or rename a file under
   `.github/workflows/` or `ci/` unless its brief **on the base** names that file.
2. **The hook's COMMIT match (napoleon J76 report).** `warscape/trailer.py` `COMMIT` knows `git -c k=v` and `git -C dir` only; a game hook must normalise
   `git --no-pager commit`, `git -P commit`, `git --git-dir=x commit` or an alias before it asks. After this job it does not.
3. **A pull request into a branch other than main (W23 report, open question 1).** Under `pull_request_target` the base's rules judge, so a base that is a
   feature branch runs that branch's code with the base's privileges.

## What exists (read before building; checked 2026-11-04 against `origin/main` f1dbb13)
- **Rules:** `docs/DECISIONS.md` C18, C24, C27; `docs/CONSUMING.md` ("The job pipeline", "What the `policy` check does not prove", the `[policy]` keys);
  `jobs/W23/report.md` (open questions 1 and 2) and `jobs/W27/report.md` (its false-positive scan and kill criterion are the model for decision 1 below).
- **`warscape/policy.py`:** `check()` is pure; the `job` branch arm (`if m and m.group(1) == 'job'`) already holds the VERSION rule and `other_rows_changed`;
  `changed` is the set of paths (renames are a delete and an add: `diff_base` uses `--no-renames`); `base_file(path)` reads a file at the base by sha.
  `settings()` builds `cfg` from `[policy]`; `JUDGE_API = 1` (a later core may only add optional arguments). `rule_input_note` already lists
  `.github/workflows/policy.yml` and `<template_dir>/policy.yml.in` as rule inputs.
- **`warscape/policy_base.py`:** `judge(ctx, branch, base, head)` resolves `base` (a ref string such as `origin/main`, passed as `--base` by the workflow
  as `"origin/$BASE_REF"`) and prints the verdict; the refusals there are `Refusal`s that name the fix.
- **`warscape/trailer.py`:** `COMMIT` (one regex) and `commit_lacks_trailer(cmd, session_id, trailer)`. `tests/test_trailer.py` has the existing cases
  (`git -C /r commit`, `git -c core.hooksPath=/dev/null commit -q`, `git commit-tree` is no commit, `echo git commit` is no commit).
- **`wsc.toml` / `warscape/repo.py` `DEFAULTS`:** the `[policy]` table and its type checks (:186-198 style); `ci/policy.yml.in` and `.github/workflows/policy.yml`.
- **Not available:** a game's own hook (its JSON protocol stays in the game repo). This job changes only what the core exposes.

## Decisions already made (follow them; a deviation goes in the report with its reason)
### 1. Workflow files on a job branch
- New `[policy]` key `workflow_paths` (list of globs, matched with `repo.matches`; default `[".github/workflows/**", "ci/**"]`; `[]` switches the rule off). Add
  the type check beside `decisions_cite_job`'s, document it in `docs/CONSUMING.md`, and spell it out in the core's `wsc.toml` and `tests/fixture_game/wsc.toml`.
- In `check()`, in the `job` arm: for every changed path that matches `workflow_paths`, the base's `<jobs dir>/<id>/brief.md` must contain that exact path
  (a plain substring test; a path in backticks is the convention). Otherwise one error per path: "`<path>` is a workflow input and `<id>`'s brief on the
  base does not name it: a job cannot quietly add a check that posts a fake `policy` status (W36); name the file in the brief (briefs are merged before
  the job starts) or use a `meta/` branch".
- A rendered workflow comes from a template: a job that edits `ci/gates.yml.in` must name `.github/workflows/gates.yml` too, because the re-render
  changes both. Say so in the refusal text when the missing path has a `<template_dir>` sibling.
- Deletions and renames count (the diff is `--no-renames`). `brief/`, `plan/`, `meta/` and `release/` are out of scope (the brief and plan kinds cannot
  touch these paths already, `meta/` is the sanctioned route for infrastructure, `release/` changes VERSION only); say that in the docstring and docs.
- **False-positive scan, as W27 did (scratch script, not committed):** judge every merged `job/*` pull request of this repo (and napoleon-remastered's, read
  only with `git -C <path> ...`) at its head against its merge commit's first parent, with the rule on, and list those that touch `workflow_paths` and whose
  brief does not name the file. Cite the counts in the report.

### 2. COMMIT knows git's global options
- Rewrite `COMMIT` and its helper so that between `git` (or `git.exe`) and the subcommand any of these may appear, each with its argument in
  `"..."`, `'...'` or bare form: `-c k=v`, `-C dir`, `--git-dir=P` and `--git-dir P`, `--work-tree=P` and `--work-tree P`, `--namespace=N` and `--namespace N`,
  `--exec-path[=P]`, `--super-prefix=P`, `--config-env=k=ENV`, and the flags `-p`, `-P`, `--paginate`, `--no-pager`, `--no-replace-objects`, `--bare`,
  `--literal-pathspecs`, `--glob-pathspecs`, `--noglob-pathspecs`, `--icase-pathspecs`, `--no-optional-locks`.
- **Aliases defined in the command:** `git -c alias.ci=commit ci ...` (and `alias.X="commit -q"`, and an alias that names `commit` first) is a commit.
  Aliases from the user's gitconfig cannot be known from the command string and stay unseen (fail open, as today); say that in the docstring.
- No false positives: `git commit-tree`, `git status`, `echo git commit`, `git log --grep commit`, `git -c alias.ci=status ci`, `git config alias.ci commit`
  and `git help commit` are not commits. A path-qualified git (`/usr/bin/git commit`) is out of scope unless the builder finds it costs nothing: if added,
  it needs its own tests.
- `commit_lacks_trailer` keeps its signature and its `--trailer` rule; the existing `tests/test_trailer.py` cases stay green unchanged.

### 3. A non-default base: refuse, do not pin
- **Refuse.** Pinning the judge to main while diffing against another base would make "the brief on the base" and "rows on the base" mean two different
  commits, and C18 says every change merges to `main` through the queue. Stacked pull requests are not part of the pipeline.
- New `[policy]` key `bases` (list of branch names, default `["main"]`; `[]` accepts any base, for a game whose default branch is not `main`). In
  `policy_base.judge`, before any git work on the head: when `base` has the form `origin/<name>` and `<name>` is not in `bases`, return a refusal that
  names the fix ("retarget the pull request to main, or list the branch in `[policy] bases`"). A `base` that is not an `origin/<name>` ref (a sha, `HEAD~3`)
  is not judged by this rule: local and test use stay as they are.
- The rule is read from the **base's** `wsc.toml` like every other (C24): the parent that runs in CI is the base's code. A base that predates this job
  does not know the key; in that case the rule is silently absent (fail open), which `docs/CONSUMING.md` states under "Moving to base-judged policy".
- Keep `JUDGE_API` at 1 unless the child needs a new argument; if it does, it is optional (W23's rule).

## Steps
1. Read the two reports named above, `check()`'s job arm and `judge`, run the false-positive scan of decision 1 on the merged job branches, and keep the
   output in the run folder.
2. **Red tests first, committed alone** (cite the commit and the failure counts in the report):
   - `tests/test_policy.py`: a new class `W36WorkflowFiles` (pure `check()`): a job branch that adds `.github/workflows/x.yml` with a brief naming it
     passes and one without the name is refused; a change to `ci/gates.yml.in` naming only the template is refused for the rendered file; a delete and a
     rename each refused; `workflow_paths = []` passes; `brief/`, `plan/`, `meta/` unchanged.
   - `tests/test_policy_base.py` (CoreMode, the CLI as CI runs it): the base's brief names no workflow and the head adds one: refused, exit 1, naming the
     path; a head that edits `workflow_paths` in its own `wsc.toml` to `[]` is still refused (the base's config judges). Same for `--base origin/feature`:
     refused naming `bases`; `--base origin/main` unchanged; a sha base unchanged; `bases = []` accepts.
   - `tests/test_trailer.py`: every option in decision 2 in front of `commit` (lacks the trailer, so True), with the trailer (False), the no-commit
     cases of decision 2 (False), and the alias cases.
3. Build decisions 1, 2 and 3. Update `warscape/policy.py`'s docstring (the branch-kind list and rules), the `wsc.policy` tools row and the `wsc.toml`
   `[policy]` keys. `python3 wsc.py gates --fast` after each change, `python3 wsc.py gates` once at the end.
4. Docs, short and in the doc that owns the topic: `docs/CONSUMING.md` ("The job pipeline": the workflow rule, the base rule; "What the `policy` check does
   not prove": the forged status is now closed for `job/` branches, still open for a token holder and for `meta/` branches, which Liam reviews; the keys;
   "Moving to base-judged policy": the fail-open note); `docs/REVIEW.md` one sentence (a reviewer of a job that touches a workflow checks the brief named
   it). A decision row only if the builder deviates from this brief. Check the 30 KB `doc_size` gate before pushing.
5. Re-render workflows if the template changes (`python3 wsc.py ci render`); it should not need to.

## VERSION
W36 is below `[jobs] semver_from` (40), so it is a legacy job (W29): it bumps `VERSION` by hand to the next free minor above `main` and every open
`job/*` branch at the time (the orchestrator renumbers at merge). The row says `semver: minor` so the release workflow's re-derived version matches the
hand bump. Consumers must bump to get the new rule and the hook match.

## Proof
- The red commit and the green commit; `python3 wsc.py gates` (full) green, with the count of host tests; `python3 wsc.py policy --branch job/W36 --base origin/main`
  run from the branch and read (it is refused only for what a job in review lacks).
- The false-positive scan counts of decision 1 (merged job branches that would have been refused) and what was done about them.
- The three behaviours demonstrated through the CLI, not only through `check()`: a head that adds a workflow, a head into `origin/feature`, and
  `commit_lacks_trailer("git --no-pager commit -m x", sid)`.
- CI run ids for `gates` and `policy` on the pull request.

## Open questions (only where Liam must choose)
- None expected. If the scan shows the workflow rule would have refused more than three merged job branches that legitimately edited `ci/` or
  `.github/` without naming it in the brief, apply the kill criterion rather than ask.

## Kill criteria
- The false-positive scan of decision 1 finds more than 3 merged job branches (beyond any the audit lists) that the rule would have refused: make the rule
  a warning (as W27 did for rule A), say so in the report, and ask for a later row to harden it.
- A change would need a game's hook or a game repo to change: stop and report; the core's function is the deliverable.
- The base judging in CI (`pull_request_target`) cannot be proved with the host tests for decision 3: stop, commit what is done, and report.
- CI still red after three fix attempts, or more than about 110 tool calls: stop, commit, and report what is left.

## Finish
Report in `jobs/W36/report.md` (what was built, the red and green evidence, the scan counts, the version taken, deviations, open questions), then
`wsc reg set jobs W36 status=review report=jobs/W36/report.md` (`python3 wsc.py`). Push `job/W36`, open the draft pull request, and stop: an
independent reviewer merges (C18).

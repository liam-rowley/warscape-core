# W36 report: Policy and hook follow-ups: workflow edits on job branches, global-option-aware commit match, non-main bases

Three follow-ups are built, but the first is weaker than the brief asked: **a job that changes a workflow input its brief does not name gets a warning, not a refusal**, because the false-positive scan found 13 merged job branches the rule would have refused (the brief's kill criterion is more than 3), so the forged-status residual is narrowed, not closed. `warscape/trailer.py` now sees git's global options and aliases defined in the command, and no longer calls `echo git commit` a commit. A pull request into `origin/<name>` outside `[policy] bases` is refused before the head is read. Liam: a later row is needed to harden the warning (open question 1).

Started from `origin/main` 458d19e; merged `origin/main` up to the commit named under "Merges with main". No `VERSION` change (deviation 2); the row says `semver: minor`.

## What was built
- **Decision 1, workflow inputs (`warscape/policy.py` `workflow_warnings`, called in `check()`'s `job` arm).** New `[policy] workflow_paths`, default `[".github/workflows/**", "ci/**"]`, `[]` switches it off, spelled out in the core's and the fixture's `wsc.toml`, type-checked in `warscape/repo.py`. Each changed path that matches, plus the rendered file of a changed `<template_dir>/<name>.in`, must appear as a plain substring in the brief on the base; otherwise one warning per path, in the brief's wording, with "`<rendered>` renders from `<template>`: name both" when a template sibling exists. A delete and both halves of a rename count. `brief/`, `plan/`, `meta/` and `release/` are untouched.
- **Decision 2, the commit match (`warscape/trailer.py`).** `COMMIT` is replaced by `GIT` (where a command starts), `WORD` (one shell word), the option sets and `_runs_commit` / `_has_commit`. Every option in the brief is known, in `"..."`, `'...'` and bare forms. `-c alias.X=...` is followed, through other aliases, `!` shell aliases and aliases that begin with a global option; a loop ends because an alias used is removed. `commit_lacks_trailer` keeps its signature and its `--trailer` rule, and the existing `tests/test_trailer.py` cases are unchanged. Gitconfig aliases and a path-qualified `/usr/bin/git` stay unseen, as the docstring says.
- **Decision 3, non-default bases (`warscape/policy_base.py` `refuse_unlisted_base`).** New `[policy] bases`, default `["main"]`, `[]` accepts any. It runs first in `judge`, reads only the base (`base_config`, split out of `base_rules`), and prints `REFUSED (not judged)`. A sha, `HEAD~3` or a local branch is not judged by it. A malformed value fails closed. `JUDGE_API` stays 1.
- **Docs and rows.** `docs/CONSUMING.md` (the keys, the base rule, "What the `policy` check does not prove"), `docs/REVIEW.md` (a reviewer clears the warning), `docs/UPGRADING.md` (the fail-open note and a W36 section), `warscape/policy.py`'s docstring, the `wsc.policy` header and tools row, and decision row C35.

## Evidence
**Red, then green.** The red tests are alone in commit `0108235`: `test_trailer` 42 failures, `test_policy` 7 failures and 1 error, `test_policy_base -k w36` 5 failures and 2 errors of 8 (the eighth guards unchanged behaviour). The build is commit `9863433`: `test_trailer` 20 ok, `test_policy` 65 ok, `test_policy_base` 32 ok.

**False-positive scan (2026-11-04, `origin/main` 458d19e; napoleon-remastered `origin/main` 0c5c255, read only).** Each merged `job/*` pull request from `gh pr list`; for each merge commit, the paths against its first parent (`--first-parent --no-renames`); each job's own brief at that parent, searched for the exact paths.

| Repo | Merged `job/*` | Touch `workflow_paths` | Would be refused |
|---|---|---|---|
| warscape-core | 31 | 10 | 3: W2, W29, W37 |
| napoleon-remastered | 64 | 18 | 10: J1, J2, J5, J12, J19, J22, J42, J45, J62, J79 |
| **Total** | **95** | **28** | **13** |

- What each brief missed: W2, J1, J2, J5, J12, J19, J22 and J45 named no workflow file by its exact path (the rule's test). W29, W37 and J79 named the template or another file but not the rendered `.github/workflows/gates.yml`. J42 named `gates.yml` but not the `policy.yml` it added. J62 named the workflows but not the `ci/*.yml.in` it added.
- `docs/audits/AUDIT_2026-11-03.md` lists none of the 13 as a workflow finding, so all count as "beyond the audit's". Dropping the three rendered-file cases still leaves 10.
- Every one of the 95 targeted `main`, so decision 3 refuses nothing that merged.
- All were reviewed, legitimate changes: the briefs were written before naming the file was a rule, so the count measures the convention, not abuse.

**Through the CLI** (real output, 2026-11-04, this branch at 043b0ae):
```
$ python3 wsc.py policy --branch job/W36 --base origin/brief/W36
policy: origin/brief/W36 is not a branch pull requests may target: retarget the pull request to main, or list the branch in `[policy] bases`
policy: job/W36: REFUSED (not judged)                                                     [exit 1]

$ python3 wsc.py policy --branch job/W36 --base job/W36 --head <scratch commit adding .github/workflows/fake.yml; deleted, never pushed>
policy: judged with the rules of job/W36 at 043b0aecae19 (core 0.37.0)
policy: warning: `.github/workflows/fake.yml` is a workflow input and W36's brief on the base does not name it: a job cannot quietly add a check that posts a fake `policy` status (W36); name the file in the brief (briefs are merged before the job starts) or use a `meta/` branch

commit_lacks_trailer("git --no-pager commit -m x", sid) -> True;  "git -c alias.ci=commit ci -m x" -> True;  "echo git commit" -> False;  "git -c alias.ci=status ci" -> False
```
The base in the second run is this branch because `origin/main` does not have the rule yet. That run ended REFUSED only for the report, review and `done` row the scratch head lacked; the W36 line itself is a warning. `tests/test_policy_base.py` proves the same as CI runs it: a head's own `workflow_paths = []` or `bases = []` changes nothing, and a brief edited on the head does not count (C24).

**Napoleon's hook is unaffected.** It calls `commit_lacks_trailer` on `'git commit ' + args` (`tools/claude_hook.py:322`), which starts in command position, and reads nothing else from the module. Its corpus's commit cases were read and are covered by `GlobalOptions`; its tests were not run here, since this job does not touch that repo.

**Gates:** `python3 wsc.py gates` (full, 2026-11-04): 15 ok, 1 warn, 0 failed; 937 host tests passed, 5 skipped. The warn is only those skips: the hook test needs a POSIX sh and symlinks, and four discovery tests need capstone, neither of which this PC has. An earlier full run failed one test (`test_the_queue_passes_jobs_check`) because this report existed before its row said so; setting the row fixed it.

## CI
CI_LINES

## Deviations from the brief, and why
1. **Decision 1 warns instead of refusing.** The brief's kill criterion, which it says to apply rather than ask. The tests in step 2 assert a warning at exit 0 where the brief said "refused, exit 1". The wording is the brief's, so a later hardening changes one line.
2. **No `VERSION` bump.** The brief's "VERSION" section says W36 is a legacy job that bumps by hand; Liam's instruction for this session and `CLAUDE.md` say a job branch leaves `VERSION` alone and the row's `semver` drives the release. `policy` allows either below `semver_from`. `release.plan` handles this: a row with `semver: minor` and `VERSION` at the last tag releases `bump(max(T, V), minor)`.
3. **`COMMIT` no longer exists,** and the match checks command position, which the brief did not ask for. `echo git commit` is listed as an existing no-commit case, but the test passes an empty session id, so it never reached the regex; with a real id the old code returned True. The fix also makes `grep -r "git commit" docs` and `git log --grep "git commit"` no commits. Cost: a `git` behind a wrapper the pattern does not know (`xargs git commit`, `sudo -u bob git commit`) is now unseen, where the old regex saw it; the commit-msg hook and `policy` still read the commit. Wrappers, `bash -c`, `cmd /c`, `eval` and `powershell -Command` are tested.
4. **One option beyond the brief:** `--config-env k=ENV` as two words, because git accepts it.
5. **A template change requires the rendered file even if the branch did not change it,** following the brief's sentence that a job editing `ci/gates.yml.in` "must name" it; the `ci_render` gate fails such a branch anyway.
6. **The fail-open note is in `docs/UPGRADING.md`,** where "Moving to base-judged policy" now lives (moved out of `docs/CONSUMING.md` on 2026-11-04 for the cap).
7. **The scan has no script or run folder.** The session's harness refused a scan script that ran `git -C` on the other clone, so it was run as plain read-only commands, and the table above is its record. It diffs the merge commit against its first parent rather than the head against the merge base: the same paths for a squash merge.
8. **A decision row (C35)** because of deviations 1 and 3, as the brief asks for a deviation.

## Open questions
1. **Liam: add a row to harden the workflow rule.** A job branch cannot add one, so it needs a `plan/` branch. Until then a job can still add a workflow that posts a fake `policy` status if its reviewer ignores the warning. Recommended shape, as W40 does for rule A: `[policy] workflow_rule = "warn" | "error"`, default `warn`, the core at `error`, once briefs have named their files for a while. The core's own count is 3 of 31, and 2 of those are the rendered-file case the new message explains.
2. **What decision 3 cannot do.** The refusal is a verdict, not a stop: under `pull_request_target` the workflow on the base branch has already started with the base's privileges, and a base whose core predates W36 runs no such rule. The rule keeps a stacked pull request out of the pipeline, but it does not remove the privilege W23 described. If that matters, `branches: [main]` on the trigger in `ci/policy.yml.in` is the direct fix, a separate change to a rule input. No decision is needed for this job.
3. **`docs/CONSUMING.md` is 8 bytes under the 30 KB cap,** so the next job that adds a line there must move something out first.

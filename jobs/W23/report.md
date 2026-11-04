# W23 report: Policy judged with the base's rules

Written by the orchestrator from the builder subagent's hand-back, because the harness refuses a subagent's write of a report file. The
text is the builder's own apart from this note and the notes marked "orchestrator".

Branch `job/W23` was built on f879196 (main at 0.24.0). The orchestrator merged `main` (0.25.0, W30): the only conflict was `VERSION`. W23
takes VERSION 0.26.0 and decision C24 (proposed). W10 holds the same numbers on its branch; whichever of the two merges second renumbers,
because decision rows number from the base (a C25 directly after C23 is refused: "new row C25 should be C24").

## What was built
A pull request is now judged by the base's code, with the base's configuration and the base's gate modules. The head reaches the judge only
as git objects. This closes:
- the audit's four bypasses (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`, P2);
- a repointed core gitlink;
- the head owning `policy.yml` (bypass 5);
- a rename bypass found while building (see Tests).

### 1. The judge, in process: `warscape/policy.py`
- `run_check(ctx, branch, base, head, repo, extra_facts=None, base_ref=None)` reads git at `repo` by sha, through `git_env()`.
  - It never runs git in `ctx.root` and never uses `'HEAD'`; refs are resolved to shas first.
  - The policy-stage `ctx.facts` keep `root`, `branch`, `kind`, `jid`, `changed` and `merge_base`. `base` and `head` are now shas, and
    `base_ref` and `repo` are new.
- `check()` is still pure. It gains a `base_ref` keyword for messages.
- `JUDGE_API = 1` sits on a line of its own.
- `diff_base()` resolves both refs, finds the merge base and diffs with `--no-renames -z`. Each failure is a `Refusal` that names the fix.
- `rule_input_note()` lists what counts as a rule input, taken from the base's config:
  - the core (`wsc.py` and `warscape/**`, or the gitlink in a game);
  - `wsc.toml`, `[gates] dirs/**` and the legacy file;
  - `.github/workflows/policy.yml` and `<template_dir>/policy.yml.in`.
  - The child prints the note as: `policy: note: this branch changes <paths>: they judge pull requests after this one merges; this one was
    judged with <base-ref>'s`.
- `allowed()` uses `repo.matches`, so globs match by path segment.
- `decisions_problems()`: when the head's rows are a strict prefix of the base's, it says
  `merge <base-ref>: the base has rows this branch lacks (<ids>)`.

### 2. The parent: `warscape/policy_base.py` (new library module, split out because `policy.py` reached 402 lines)
- **`judge(ctx, branch, base, head)`** resolves both shas and reads the base's `wsc.toml` from git.
- **Which core judges:**
  - inside the core, the base commit;
  - in a game, the pin of the base's gitlink at `[ci] core`, read from `<repo>/<core>`'s object store. The submodule's `--show-toplevel`
    must equal that folder, so an empty `core/` cannot fall through to the game repo.
- **A base whose core has `JUDGE_API`** (read with `^JUDGE_API = (\d+)\r?$`):
  - The base's rule inputs are extracted into `tempfile.mkdtemp(prefix='wsc-policy-')` with `git archive` and `tarfile` (`filter='data'`):
    in the core the whole base tree; in a game the pinned core at `<core>/`, plus whichever of `wsc.toml`, the `[gates] dirs` folders and
    the `[jobs] legacy` file exist at the base.
  - The parent prints `policy: judged with the rules of <base-ref> at <sha12> (core <VERSION>)`.
  - It runs `<sys.executable> -I -X utf8 <tmp>/<core>/wsc.py --root <tmp> policy --judge --repo=... --branch=... --base=<sha> --head=<sha> --base-ref=...`.
    The working directory is `<tmp>`; the environment is `git_env()` plus `GIT_CEILING_DIRECTORIES` set to the folder's parent; the
    timeout is 240 s.
  - It relays the child's output and deletes the folder.
  - Exit 0 is ok only together with the child's `ok` line, and exit 1 is refused only together with its `REFUSED` line. Anything else is a
    refusal: `policy: the base's rules gave no verdict (exit N | timed out after 240 s): <last stderr line>`.
- **A base without `JUDGE_API`** is judged in process by the checkout's code and config, after a note:
  `policy: note: the base's core predates base-judged policy (no JUDGE_API at <sha12>): judged with this checkout's rules, as before W23`.
- **Fail-closed refusals, each naming the fix:**
  - an unresolved base or head (`git fetch`), or no merge base;
  - no `wsc.toml` at the base, or one that is unparsable or wrongly typed;
  - no gitlink at the base's `[ci] core`;
  - a submodule that is not initialised (`git submodule update --init core`);
  - a missing pin (`git -C core fetch origin <pin>`);
  - an extraction error, or any git failure.
- The parent never uses `git worktree` and never runs anything from the head.

### 3. The verb: `warscape/verbs/policy.py`
- `--head` (default `HEAD`) is new, along with the internal `--judge`, `--repo` and `--base-ref`, which are hidden from `--help` and
  described in the docstring.
- The `usage:` line is updated and the `wsc.policy` tools row refreshed.
- `--commit-msg` is unchanged.

### 4. CI
- **`block_policy`** renders these steps, in order:
  - the default checkout, which is the base under `pull_request_target`: `fetch-depth: 0`, plus `submodules: true` and the token in a game;
  - setup-python;
  - `git fetch --no-tags origin "+refs/pull/$PR/head:refs/remotes/pull/$PR/head"`;
  - `[ci] policy_extra_steps`;
  - `wsc policy --branch "$HEAD_REF" --base "origin/$BASE_REF" --head "$HEAD_SHA"`.
  - `PR`, `HEAD_REF`, `BASE_REF` and `HEAD_SHA` reach the scripts only through `env:`. `notify policy` passes the branch through `env:` and
    uses the `GITHUB_*` variables.
  - No step checks out, builds, caches or runs the head.
- **The render guard** (`ci_render.guard`, `guards`):
  - `wsc ci render` and the `ci_render` gate refuse a template that has the `policy` block but no `pull_request_target` trigger. Comment
    text does not count, and `wsc ci render` refuses before writing anything.
  - Both warn while a `pull_request` trigger sits beside it.
- **The templates:**
  - `ci/policy.yml.in` triggers on `pull_request_target`. It also keeps the W23 bootstrap trigger: `pull_request`, with the same types and
    `paths: ['jobs/W23/report.md']`. A comment says why, and that W27 removes it. `.github/workflows/policy.yml` is re-rendered.
  - `tests/fixture_game/ci/policy.yml.in` switches to `pull_request_target`, with no bootstrap trigger.

### 5. Docs
- `docs/CONSUMING.md`:
  - "The job pipeline": base-judged policy, `git fetch` first, the note, fail closed, the fallback, "What the `policy` check does not
    prove" (the forged-status residual) and the render guard;
  - "Game gates": the policy stage's new contract;
  - a new section, "Moving to base-judged policy (0.26.0, core W23, C24)".
- The policy-stage docstring in `warscape/gatemods.py`.
- One sentence each in `docs/REVIEW.md` (Steps 1) and `CLAUDE.md` (Jobs).
- C24 in `docs/DECISIONS.md`, and `VERSION` 0.26.0.

## Tests, red then green
The red commit is e1d7fb3, on f879196's code: 21 failures and 1 error among the 22 new tests, with every existing test green. Each failed
because the old code passed the bypass, or because it lacked the new interface (`--head`, the env-form render, the guard). All are green
from e7ff3c8 and 220cce8 on.

- **How the tests run the judge.**
  - `ci()` in `tests/test_policy_base.py` runs what CI's `policy` job runs, chosen by the base's rendered `policy.yml`:
    - with `pull_request_target`: the base checkout, the base's `wsc.py`, and `--head`;
    - before W23: the head checkout, running the head's `wsc.py`.
  - `local()` runs from the head checkout, with this checkout's code as the (honest) parent.
- **`tests/test_policy_base.py`, `CoreMode`** (a clone of the throwaway core from `tests/_util.py` `core_source()`):
  - the four bypasses, each under both CI and local:
    - `test_bypass_1_a_bootstrap_entry_on_the_head_exempts_nothing`
    - `test_bypass_2_an_empty_session_trailer_on_the_head_keeps_the_own_review_rule`
    - `test_bypass_3_the_heads_own_check_returning_nothing_is_never_run`
    - `test_bypass_4_an_empty_decisions_key_on_the_head_keeps_the_file_append_only`
  - `test_a_head_verb_module_that_patches_check_at_import_changes_nothing` (CI and local);
  - `test_a_meta_head_that_narrows_or_widens_its_own_globs_is_judged_by_the_bases`, where both runs get the note;
  - `test_the_head_checkout_and_the_base_checkout_with_head_print_the_same`;
  - `test_a_base_without_judge_api_is_judged_by_this_checkout_with_a_note`;
  - `test_a_base_whose_check_raises_is_a_refusal_naming_the_exit_and_the_error`;
  - `test_a_base_that_does_not_resolve_is_a_refusal_naming_the_fetch`;
  - `test_a_base_whose_wsc_toml_does_not_parse_is_a_refusal`;
  - `test_a_policy_module_runs_in_the_base_tree_and_reads_the_head_only_through_git`:
    - the temp folder sits inside a throwaway repo (with TMP, TEMP and TMPDIR set);
    - `git -C ctx.root show HEAD:x` crashes the module;
    - the facts are shas, with `base_ref` and `repo`;
    - `show()` reads a head blob;
    - the folder is gone afterwards.
  - `test_a_rename_counts_as_a_delete_and_an_add`, added in e7ff3c8 after the red commit. Red evidence: f879196's own `wsc.py` on a
    `plan/move` branch printed `policy: plan/move: ok (1 files changed)`; W23's prints `REFUSED (2 files changed)` and names
    `warscape/jobq.py`.
- **The ceiling, checked by hand.** Without it, `git -C <tmp>/wsc-policy-x show HEAD:x` printed the enclosing repo's `ENCLOSING`. With the
  Windows-form path in `GIT_CEILING_DIRECTORIES` it printed `fatal: not a git repository`.
- **`tests/test_policy_base.py`, `GameMode`** (the fixture game, with that core as its submodule):
  - `test_a_head_that_edits_or_drops_the_bases_gate_modules_is_still_judged_by_them` (the `_policy` edit and `[gates] dirs = []`; CI and
    local);
  - `test_a_head_that_repoints_the_core_gitlink_never_runs_that_commit`: the sentinel never appears (CI and local, with the evil pin on
    disk);
  - `test_a_base_pin_missing_from_the_submodule_is_a_refusal_naming_the_fetch`;
  - `test_a_base_with_no_core_gitlink_is_a_refusal`;
  - `test_the_base_tree_holds_the_pinned_core_the_config_the_gate_modules_and_the_legacy_file` (top level `core,gates,jobs,wsc.toml`).
- **`tests/test_policy.py`:** `test_w23_globs_match_by_path_segment` and
  `test_w23_a_branch_behind_the_base_on_the_decisions_file_is_told_to_merge`.
- **`tests/test_ci.py` `Render`:**
  - `test_w23_the_policy_job_runs_base_code_and_names_the_head_only_as_data`: no `${{` in any `run:` script; `--head` passed; the env names
    present; no `ref:`; no `git checkout`, `switch` or `worktree`; no `actions/cache`.
  - `test_w23_the_render_guard_refuses_a_policy_template_without_pull_request_target`: it refuses, warns, then passes; a comment does not
    count.
  - `test_w23_this_repos_policy_workflow_is_pull_request_target_with_the_bootstrap_trigger`.
- **Existing tests changed in the commit that changed the code:**
  - The `GOLDEN` hashes of the fixture's `policy.yml` and of the two all-blocks renders changed in 220cce8, with a comment saying so. The
    fixture's `gates.yml` hash is unchanged.
  - The `head_ref` assertion now expects the env form, and checks that the head fetch comes before the extra steps.
  - The fixture game gains a real core submodule. Its setup moved into `tests/_util.py` `fixture_game()` (f060f37), so that no test module
    imports another. The fixture's own assertions are unchanged.

## Gates and the policy run (this PC, Windows, 2026-11-04)
- **`python3 wsc.py gates` at f060f37:** 13 ok, 2 warn, 0 failed in 155.2 s.
  - `ci_render` warns: "ci/policy.yml.in also has a pull_request trigger beside pull_request_target: the bootstrap of the pull request that
    switched (W23); remove it in the next change to the template". This stays until W27.
  - `tests`: 617 host tests passed, 5 skipped (the existing POSIX-sh hook test and four capstone tests).
- **`python3 wsc.py policy --branch job/W23 --base origin/main`:** the three expected refusals (report, review, `done`), then the fallback
  note (no `JUDGE_API` at origin/main), then `REFUSED`. This is the fallback the brief predicts, because origin/main predates W23.
- **Orchestrator:**
  - After the merge of `main`, `policy` gives the same output. A C25 attempt gave "new row C25 should be C24" and was reverted.
  - The branch's push runs and the pull request's bootstrap `policy` run are recorded on the pull request.

## The bootstrap: what to check on the first push and on the pull request
1. **The first push of `job/W23`.** The `gates` workflow runs on the push event, from the branch's own `gates.yml`:
   - `changes`, `gates (ubuntu-latest)` and `gates (windows-latest)` run;
   - `proxy` and `harness-windows` also run, because their inputs include `.github/workflows/`, `ci/` and `warscape/`;
   - both `gates` logs must end with `0 failed`, and `test_policy_base` must be among the tests run;
   - no `policy` run is expected on a push.
2. **The draft pull request,** opened after `report.md` is committed so that the path filter matches:
   - expect exactly one run of the `policy` workflow, with event `pull_request`, from W23's own `policy.yml` on the merge ref, through the
     bootstrap trigger;
   - expect no `pull_request_target` run, because main's file has no such trigger;
   - the `policy` job is skipped while the pull request is a draft.
   - To check: `gh run list --workflow policy.yml --branch job/W23 --json databaseId,event,headSha,conclusion`, and `gh pr checks` shows one
     `policy`.
3. **After the reviewer's `gh pr ready` and the push of the review commit:**
   - the `pull_request` run on the review head must be green;
   - the `git fetch ... refs/pull/<n>/head` step must succeed;
   - `gh run view <id> --log | grep 'policy:'` must show the fallback note, then `policy: job/W23: ok (<n> files changed)`.
4. **Kill criterion:** if no `policy` run appears after `gh pr ready`, stop and report. The fallback is the brief's open question 3: an
   admin merge after the review.

## After the merge (handed on; not part of this job)
- The next pull request's `policy` run must show the event `pull_request_target` and `policy: judged with the rules of origin/main at
  <sha12> (core <VERSION>)`.
- It must get exactly one `policy` check: the bootstrap trigger runs only when a pull request changes `jobs/W23/report.md`.
- That run id goes into W27's brief, and W27 removes the bootstrap trigger.
- If no `policy` check appears on that pull request, a `meta/` revert of the trigger restores the old one.

## What consumers must do
This is in `docs/CONSUMING.md`, "Moving to base-judged policy" (napoleon J78):
- the template switch, plus the bootstrap trigger for the bump's own report;
- `policy_extra_steps` run in the base checkout, with the head sha taken from `env:`;
- the policy-stage module reads git at `ctx.facts['repo']` by sha, and never runs the head's `build_id.py`;
- a branch behind main on the decisions file must merge main;
- globs match by path segment.

## Deviations from the brief, and why
- **VERSION 0.26.0, not 0.25.0, and C24, not C23.** `main` moved to 0.25.0 (W30) and W12 took C23. W10 holds the same numbers; the
  orchestrator renumbers whichever merges second.
- **`warscape/policy_base.py` is a separate module.** `policy.py` reached 402 lines, and the brief allows a split past about 350.
- **`--no-renames -z` in the judge's diff.** This is not in the brief.
  - `git diff --name-only` hides a renamed file's old path (diff.renames is on by default), so a `plan/` or `meta/` branch could move code
    into an allowed folder.
  - `-z` makes the output independent of `core.quotePath`.
- **`-X utf8` in the child's command.** `-I` ignores `PYTHONUTF8` and `PYTHONIOENCODING`.
- **A verdict also needs the child's verdict line**, not only exit 0 or 1, which is stricter than decision 4.
- **One existing assertion changed.** `test_plan_and_meta_scopes` expected the default `meta` globs to allow
  `registries/tools/wsc.jobs.json`. With segment globs, `registries/*` no longer reaches a per-row file: decision 11's intended effect.
- **Some test setups now set `[ci] core = ""`** (`tests/test_policy.py` `PolicyOnGit`, `tests/test_gatemods.py` `PolicyStage`). These repos
  have no core, and would otherwise refuse with "no gitlink".
- **More tests than step 2 lists:** no gitlink, the base tree's scope, the facts module, and the rename test.
- **The `ci_render` gate's error summary** reads "N workflow problems (render or guard)".
- **No change to `warscape/cli.py`.**
- **Steps 3 and 4 are one commit** (e7ff3c8).

## Open questions
1. **A pull request into a branch other than main** is judged with that branch's rules, so the `pull_request_target` job runs that
   branch's code. That is the same trust as a push workflow. Should a later row refuse non-main bases, or pin the judge to the default
   branch?
2. **The forged-check residual** is accepted and documented, as Liam answered. The follow-up (a `job/` branch that adds or changes
   `.github/workflows/` is refused unless its brief on the base names the file) needs a BACKLOG line. Orchestrator: it is filed in the next
   core plan branch.
3. **Test time.** The new tests add about 65 s to the tests gate on this Windows PC. Acceptable, or should a later row share one base tree
   across cases?
4. **Renumbering.** Re-check VERSION and C24 against W10 at merge.

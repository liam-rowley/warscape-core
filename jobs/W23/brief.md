# W23: Policy judged with the base's rules

Model: Opus, reason: enforcement code, where a mistake is a bypass. `policy` is the one check that decides whether unreviewed work reaches `main`. This
job changes where its code, its configuration and its workflow come from, and it moves the workflow to `pull_request_target`, where running one byte of
the head's content would give the head the base's privileges. Budget about 160 tool calls: about 50 for the judge and the base tree, 60 for the regression
tests and the fixture game's core submodule, 20 for the workflow and the render guard, 30 for docs, gates and the report. At the cap, stop, commit, and
report what is left.

## Goal
Audit 2026-11-03 (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`, read-only): P2, and the core half of P3. Today a branch is judged by its own rules:
- `run_check` takes `[policy]` and `[jobs]` from the head's `wsc.toml` (`warscape/policy.py:198`) and loads the head's policy-stage gate modules (`:209`).
- CI checks out the pull request and runs that tree's `wsc.py` (`.github/workflows/policy.yml:26-32`).

The audit reproduced four bypasses in a scratch clone:
1. `[policy] bootstrap = ["foo"]` passes code on a `foo` branch (`policy.py:123-124` returns before the branch-kind rules).
2. `session_trailer = ""` passes a self-reviewed job (`:144`, `if sessions and trailer`).
3. A policy rule that returns nothing passes anything. In the core that is the head's own `warscape/policy.py` `check`. In a game it is the head's
   policy-stage module returning an `ok` Result, deleted, or dropped from `[gates] dirs`.
4. `decisions = ""` ends append-only (`:118`).

In a game, a `job/` branch can also repoint the `core` gitlink at any pushed commit, and CI then runs that commit's policy.

There is a fifth bypass the audit did not list. Under `on: pull_request`, GitHub runs the workflow file from the pull request's merge commit, so the head also
owns `policy.yml`. A `job/` branch that edits the `policy` job to `run: true` passes, and `gh pr merge --auto` merges it with no review.

After this job, the base's code computes the verdict, using the base's configuration and the base's gate modules. The head reaches the judge only as git
objects: the diff being judged. `policy.allowed` matches globs by path segment. Each bypass, and a repointed gitlink, has a regression test.

## What exists (read before building; citations checked 2026-11-04 against `origin/main` bc77ee5)
- **The rules.** `CLAUDE.md`, `docs/DECISIONS.md` C18 (the pipeline; workflows are rendered, not called) and C22 (gate modules), `docs/CONSUMING.md` "The job
  pipeline" and "Game gates" (line 211 says the policy module "runs from the branch's own head"), `docs/REVIEW.md` (the merge order: `gh pr ready` before the
  push, because a skipped `policy` counts as passed), `jobs/W13/brief.md` (open question 5 left policy modules on the head) and `jobs/W13/report.md`.
- **`warscape/policy.py`** (216 lines; read it whole):
  - `git()` at :33-34 runs git with the inherited environment, not `repo.git_env()` (C12).
  - `allowed()` at :107-108 uses `fnmatchcase`, so `*` crosses `/`.
  - `check()` at :111-179 is pure: two callables give the base's and the head's file text, and `hook` runs the policy-stage modules.
  - `collect_facts()` at :187-192 uses `ctx.root` as the git cwd and `'HEAD'` as the head.
  - `run_check()` at :195-216 compares rows at the merge base, file text at the `base` tip and at `HEAD`, and the trailers of `mb..HEAD`.
- **The verb.** `warscape/verbs/policy.py` (26 lines): `--branch` and `--base` only. Its header is the source of the `wsc.policy` tools row.
- **`warscape/gatemods.py`.**
  - The policy stage is documented at :16-17.
  - `_files()` at :49-56 loads modules from `ctx.root`, and `load()` at :70-108 executes them in the calling process.
  - `tests/test_gatemods.py:237` calls `run_check(..., extra_facts=...)`.
- **`warscape/cli.py`.** `_load_verbs()` (:16-31) executes every `[cli] verb_dirs` module of the repo before any verb runs (`main`, :45). An in-process
  judge therefore always runs the repo's code first: a head verb module can patch `warscape.policy` at import.
- **`warscape/repo.py`.**
  - `DEFAULTS` `[policy]` is at :70-81 and `[ci] core` at :90 (`''` inside the core).
  - `git_env()` is at :106-108.
  - `glob_to_re()`/`matches()` at :210-227 are the segment-aware matcher the gates already use.
- **`warscape/ci_render.py`.**
  - `block_policy()` at :112-122 checks out the pull request and puts `${{ github.head_ref }}` inside a `run:` script.
  - `block_notify()` at :125-141 does the same for the policy kind.
  - The template `ci/policy.yml.in` has `on: pull_request` (:10-12).
  - `tests/test_ci.py` asserts the `head_ref` line (:289) and byte-for-byte render hashes (`GOLDEN`, :307-322).
- **The fixture game.**
  - `tests/fixture_game/` is the second consumer. It has `[ci] core = "core"` but no core submodule; the tests run the core's `wsc.py --root <fixture>`.
  - `tests/test_fixture_game.py:145-197` drives `policy` on fixture branches. `gates/rules.py` `_policy` is the fixture's policy rule.
- **Napoleon's rule 79** (read-only, `C:\Users\liamr\repos\napoleon-remastered\tools\jobs_hooks.py`, napoleon main 5a76c0d, pinned at v0.10.0):
  - `acceptance_active()` (:263-276) runs the BASE's `acceptance.py`. It is the one check already judged with the base's code.
  - `show()` (:217-231) reads `core/...` inside the submodule at the commit a ref's gitlink pins.
  - `core_pin_diff()` (:284-297) compares the two pins.
  - `collect_acceptance()` (:339-346) uses `'HEAD'` and `root` for git, and `dll_build_id()` (:243-254) runs the head's `build_id.py`.
  - Napoleon's `wsc.toml` `policy_extra_steps` (:75-80) fetches the base pin into `core/` in CI.
- **Measured 2026-11-04.**
  - Napoleon's meta globs match 564 of 5,976 tracked files with `fnmatch` and 232 by segment. The 332 extra are per-row files under `registries/<name>/`.
    The audit counted 533 of 5,723.
  - The core's own `plan`/`meta` globs and the `DEFAULTS` match the same files either way.
  - Napoleon's tracked tree is 135 MiB. The core's is 3 MiB (378 files).
- **GitHub facts** (docs read 2026-11-04):
  - `pull_request_target` runs the workflow file from the default branch, and "only ... if the workflow file exists on the default branch".
  - Its checks count for required status checks: it is in the eligible-event list of "Troubleshooting required status checks".
  - "Running untrusted code on the `pull_request_target` trigger may lead to security vulnerabilities", cache poisoning among them.
  - "A job is skipped by a conditional" reports Success.
  - A workflow skipped by a path filter reports no check at all.
  - "Using the same job name in multiple workflows can cause ambiguous status check results".
  - "Any person or integration with write permissions to a repository can set the state of any status check".

## Decisions already made (follow them; a deviation goes in the report with its reason)
1. **The base judges and the head is data.** The verdict is computed by the base's code, with the base's configuration and gate modules. Nothing from the head is
   imported, executed or parsed as configuration: not its `warscape/`, its gitlink, its `wsc.toml`, its gate modules or its verbs. Reason: all four reproduced
   bypasses and the gitlink are edits to the judge's inputs. Rule 79 already reads its checker from the base for this reason.
   We rejected the audit's other option, refusing changes to those files outside `meta/`. It would still run the head's code to enforce the refusal, and
   real jobs change the policy (W13, W21, this job, W27).
2. **What comes from the base, exactly:**
   - The core:
     - Inside the core, the base commit's tree.
     - In a game, the core commit that the base's gitlink pins, at the base's `[ci] core` path. It is extracted from the submodule's object store
       (`<repo>/<core>`), never from `core/` on disk and never from the head's gitlink.
   - The base's `wsc.toml`: every table, including `[policy]`, `[jobs]` with `[jobs.text]`, `[gates]` and `registries_dir`.
   - Every `[gates] dirs` folder, whole.
   - The `[jobs] legacy` file. W27's round rules will read it, so a head cannot exempt itself by adding its own id.

   What comes from the head, as git objects only:
   - The changed paths (merge base `...` head).
   - The blobs the rules read: `report.md`, `review.md`, the job rows, the decisions file text, and the gitlink sha.
   - The trailers of the head's commits.

   In a game, the base tree holds no other game files and no `[cli] verb_dirs`. The judge loads no game verbs, and Napoleon's tree is 135 MiB.
   A policy module reads anything else from git, at the sha it means.
3. **How the base's rules get onto disk: `wsc policy` itself, not the workflow.**
   - The verb writes the base tree into a fresh temporary folder outside every repository, with `tempfile.mkdtemp`.
   - Use `git archive <sha> [-- paths]` read by `tarfile` with `filter='data'`, or `ls-tree` + `cat-file --batch` as `rows_at` already does. The
     submodule's `git -C <repo>/<core> archive <pin>` covers a game.
   - Delete the folder afterwards.
   - The verb never uses `git worktree`, for three reasons:
     - A worktree is registered in the repo and leaks when the process dies. W26 exists to prune 125 and 47 stale ones.
     - It checks out the whole tree through the checkout machinery (Napoleon's 135 MiB on Windows; the post-checkout hook).
     - It is a git work tree, so a module's `git -C ctx.root show HEAD:x` would quietly read the base instead of failing.
   - A second checkout step in `policy.yml` is also refused. Under `pull_request` that step lives in the head's file (bypass 5). A local run would differ
     from CI. A game's pinned core would need a second submodule init.
   - **A git command run in the base tree must fail and never find an enclosing repository.** The project PC has a `.git` above every clone (audit, PC
     state). Use `GIT_CEILING_DIRECTORIES` in the child's environment, or a `.git` file in the tree that points nowhere; choose one and test it.
4. **The base's code runs in a child process.**
   - The command: `<sys.executable> -I <tmp>/<core>/wsc.py --root <tmp> policy --judge --repo <clone> --branch B --base <sha> --head <sha> --base-ref <name>`.
   - `-I` isolates the interpreter. `wsc.py` puts its own folder on `sys.path`, so the base's `warscape` is the one imported.
   - The environment is `git_env()` plus the ceiling.
   - The timeout is 240 s, under the CI job's 5 minutes, so a hang is a refusal with a message.
   - Exit codes: 0 means ok and 1 means refused. Any other exit, a crash or a timeout is a refusal that names the exit code and the last stderr line.
   - The child prints the existing lines (`policy: <error>`, `policy: <branch>: ok|REFUSED (n files changed)`). The parent adds one line before them:
     `policy: judged with the rules of <base-ref> at <sha12> (core <VERSION>)`.
   - `--judge` is internal. Hide it from `--help` and describe it in the verb's docstring.
   - **The interface is versioned:** `JUDGE_API = 1` in `warscape/policy.py`, on a line of its own. The parent reads it from the base tree's text with
     `^JUDGE_API = (\d+)$`. A later job may only add optional arguments, which the parent passes when the base's number allows them. A newer head's verb
     therefore always speaks the base's version.
5. **Fails closed.** Each of the following is a refusal (exit 1) that names the fix, never a pass:
   - a base or head that does not resolve, or no merge base;
   - an unreadable `wsc.toml` at the base;
   - in a game, no gitlink at the base's `[ci] core`;
   - a submodule that is not initialised, or a pin missing from it (name `git -C <core> fetch origin <pin>`);
   - an extraction error;
   - any child failure in decision 4.
6. **The transition, bounded.** A base tree without the `JUDGE_API` line is every base from before this job: W23's own pull request, and Napoleon's until
   its pin bump merges. Such a base is judged in-process by the checkout's own code and configuration, as before W23, with one note line:
   `policy: note: the base's core predates base-judged policy (no JUDGE_API at <sha12>): judged with this checkout's rules, as before W23`.
   A base that has the line is never judged this way: if its child fails, the result is a refusal. Reason: without the fallback, W23's own pull request and
   Napoleon's J78 could merge only by an admin bypass. A branch cannot make `main` predate W23.
7. **A branch that changes the rules is judged by the old ones.**
   - The child prints a note when the diff touches a rule input:
     - the core (`wsc.py`, `warscape/**` inside the core; the gitlink in a game);
     - `wsc.toml`, `[gates] dirs/**` and the legacy file;
     - `.github/workflows/policy.yml` and `<template_dir>/policy.yml.in`.
   - The note reads: `policy: note: this branch changes <paths>: they judge pull requests after this one merges; this one was judged with <base-ref>'s`.
   - The child decides which paths count, from the base's configuration.
   - A W job that edits `warscape/policy.py` (W27, W28) proves its new rule with host tests, not with its own `policy` run.
   - A check that is already green keeps the verdict of the rules at its run. A rule merged later judges only later runs.
8. **CI: `pull_request_target`, base code only.**
   - `ci/policy.yml.in` switches its trigger. `block_policy` renders the following steps:
     - the default checkout, which is the base under this event, with `fetch-depth: 0` and, in a game, `submodules: true` and the token;
     - setup-python;
     - `git fetch --no-tags origin "+refs/pull/$PR/head:refs/remotes/pull/$PR/head"` (forks too);
     - `wsc policy --branch "$HEAD_REF" --base "origin/$BASE_REF" --head "$HEAD_SHA"`.
   - `github.head_ref`, `github.base_ref`, the head sha and the pull request number reach scripts only through `env:`. A branch name may contain `$(...)`,
     which is script injection in a privileged job. `block_notify` policy changes the same way.
   - No step checks out, builds, caches or runs the head. The policy workflow has no cache step: `pull_request_target` shares the base's cache scope.
   - **The render guard:** `wsc ci render` and the `ci_render` gate refuse a template that has `{{wsc policy}}` and no `pull_request_target`. A game that
     bumps the core is then made to switch in the bump commit. They warn while a template also has a `pull_request:` trigger.
9. **The bootstrap for W23's own pull request.**
   - `main`'s `policy.yml` has no `pull_request_target`, and the head's file has no plain `pull_request`. On W23's pull request neither event would run
     `policy`, and the required check would wait forever.
   - The core's template therefore keeps a second trigger: `pull_request` with the same types and `paths: ['jobs/W23/report.md']`, plus a comment saying why
     and that W27 removes it.
   - A path-filtered workflow creates no check, so other pull requests get exactly one `policy` check, from `main`'s file. W23's pull request gets one from
     its own copy. That run is judged by the head's code under decision 6.
   - If the new trigger never reports, recovery is a `meta/` revert of the trigger, whose pull request gets a run from its own copy. There is no deadlock.
   - The fixture's template switches with no bootstrap trigger.
10. **CI and a local run see the same diff.** The judge compares the head commit with the base tip and their merge base, in CI too. It no longer uses GitHub's
    merge commit (today's CI `HEAD`), so the same two shas give the same output anywhere. `decisions_problems` gains a clearer message for a branch behind the
    base: when the head's rows are a strict prefix of the base's, say "merge <base-ref>: the base has rows this branch lacks" instead of "rows changed".
11. **`policy.allowed` uses `repo.matches`.** In `matches`, `*` and `?` stay inside one segment and `**` spans folders. The core's and the defaults'
    globs are unchanged in effect (measured above). For Napoleon this is P3's matcher fix; J73 does the rest of P3 there.
12. **The policy-stage contract (amends C22).**
    - `ctx.root` and `ctx.config` are the base tree and the base's `wsc.toml`. `ctx.files()` lists the base tree.
    - `ctx.facts` keeps `branch`, `kind`, `jid`, `changed` and `merge_base`. `base` and `head` become shas (`head` was `'HEAD'`), and `facts` gains
      `base_ref` and `repo` (the clone's absolute path: run git there; a game's submodule is `<repo>/<[ci] core>`).
    - A module never uses `'HEAD'`, never runs git in `ctx.root`, and never executes or imports the head's content. Blobs are data.
    - `from warscape.policy import show` is the reader: `show(sha, path, cwd=repo)`.
    - The `jobs`, `view` and `gates` stages are unchanged: they run on the working tree, locally.
13. **A local run is the same verb.**
    - `wsc policy --branch X --base origin/main [--head <rev>]` (head default `HEAD`) builds the same base tree and runs the same child as CI, so a run on the
      same two shas prints the same lines.
    - The parent differs: locally it is your checkout's code, in CI the base's. CI is the authority.
    - Say in CONSUMING.md: `git fetch` first, because a stale `origin/main` judges with stale rules.
    - `--commit-msg`, if W12 has merged by then, stays a head-local check of the message being written, not a pull-request judgment.
14. **Decision line:** append the next free `C<n>` (C23 when written) to `docs/DECISIONS.md` as `proposed (Claude, core W23)`. It records:
    - a pull request is judged with its base's rules (decisions 1-6);
    - CI's `policy` runs on `pull_request_target`, which amends C18;
    - policy-stage modules run from the base tree and read the head only through git at the shas in `ctx.facts`, which amends C22.

    Reversible: yes.

Out of scope (other rows): round trailers, append-only rounds, cited evidence, `handback.md` (W27); dates, strict JSON, skipped gates, the serve page, stale
doc paths (W28); a `release/` kind and tags (W29); rule 79 on every kind and Napoleon's meta globs (napoleon J73); the C19 hint and the commit-msg hook (W12).

## Scope: files this job touches
- **Library and verb.**
  - `warscape/policy.py`: the in-process judge reads git at `repo` with shas via `git_env()`; `JUDGE_API`; the base tree and the child; the rule-input note;
    `allowed`; the decisions message; the docstring.
  - `warscape/verbs/policy.py`: `--head`, plus `--judge`, `--repo` and `--base-ref` as internal flags; the header `usage:` line.
  - `warscape/gatemods.py`: the docstring for the policy stage.
  - `warscape/ci_render.py`: `block_policy`, `block_notify` policy, the render guard, the docstring.
  - `warscape/gates.py`: `gate_ci_render` warns.
  - Split the base-tree code into a new library module only if `policy.py` passes about 350 lines, and say so.
- **CI.** `ci/policy.yml.in` and `.github/workflows/policy.yml` (`python3 wsc.py ci render`); `tests/fixture_game/ci/policy.yml.in`.
- **Tests.**
  - `tests/test_policy.py`; a new `tests/test_policy_base.py` for the bypasses and the base tree (your choice of split; say which).
  - `tests/test_fixture_game.py`, which gains a real core submodule.
  - `tests/test_ci.py`: the `head_ref` assertion and the `GOLDEN` hashes, updated deliberately in the commit that changes the blocks, with a comment saying W23
    changed them.
  - `tests/test_gatemods.py` if the facts change it.
- **Rows.** `registries/tools.jsonl` (`python3 wsc.py reg add tools warscape/verbs/policy.py` after the header change) and row W23.
- **Docs.**
  - `docs/CONSUMING.md`: "The job pipeline" and "Game gates", plus the migration below. Keep it under 30 KB; it is 23.5 KB now.
  - `docs/DECISIONS.md`, `docs/REVIEW.md` (one sentence in Steps 1), `CLAUDE.md` (Jobs, if a sentence helps), `VERSION`.
- **Not touched:** `proxy/`, `harness/`, `discovery/`, `saves/`, and any Napoleon file. No game names in core files.

## Steps
1. Read "What exists". Note the commit you start from.
2. **Failing tests first, committed red against the current code.** Each test must refuse what main's code passes.
   - **Core mode.** Use a throwaway core repo: copy `repo.list_files(ROOT)` of this checkout, commit it as `main`, and add `refs/remotes/origin/main`.
     - Bypass 1: `bootstrap = ["foo"]` plus a code change on `foo`.
     - Bypass 2: `session_trailer = ""` on a `job/W1` whose report and review commits carry one session.
     - Bypass 3: the head's `warscape/policy.py` `check` returns `[]`.
     - Bypass 4: `decisions = ""` plus an edited earlier row.
     - A head `[cli] verb_dirs` module that patches `warscape.policy.check` at import.
     - Run each in CI mode (the base checked out, `--head <branch>`). Where the parent is honest, also run it in local mode (the head checked out).
   - **Game mode.** The fixture gets a core submodule: the throwaway core added with `git -c protocol.file.allow=always submodule add`.
     - The head edits `gates/rules.py` `_policy` to return `ok`.
     - The head sets `[gates] dirs = []`.
     - The head repoints `core` at a throwaway core commit whose `check` returns `[]` and writes a sentinel file. Assert a refusal, and that the
       sentinel never appears.
   - **Fail closed.**
     - A bad `--base`.
     - A base whose `wsc.toml` does not parse.
     - A game base pin missing from the submodule; the message names the fetch.
     - A base whose `check` raises.
     - A policy module that runs `git -C ctx.root show HEAD:x` errors, with the temp folder placed inside a throwaway repo (set `TMP`, `TEMP` and `TMPDIR`
       for the subprocess).
   - **The rest.**
     - Local equals CI: the same output from the head checkout and from the base checkout with `--head`.
     - The rule-input note: a `meta/` head that narrows its own globs still passes by the base's globs, and one that widens them is still refused by the
       base's. Both get the note.
     - The fallback: a base without `JUDGE_API` is judged with the note, and a base with it whose child fails is refused.
     - Segment globs: `registries/*` does not match `registries/jobs/W1.json`, and `docs/**` matches `docs/a/b.md`.
     - Render: no checkout names the head; no `${{ github.` inside a `run:` line of the policy workflow; `--head` is passed; the guard refuses a template
       with no `pull_request_target` and warns on a `pull_request:` beside it.
3. Build the in-process judge: `run_check(ctx, branch, base, head, repo, extra_facts=None)`, git through `git_env()` at `repo`, the facts of decision 12, and
   `JUDGE_API`. Keep `check()` pure.
4. Build the base tree and the child (decisions 2-6), the verb flags, the note (decision 7), `allowed` (decision 11) and the decisions message (decision 10).
   Commit after each part works.
5. The fixture game becomes a submodule consumer in `setUpClass`. Every existing fixture assertion stays as it is; only the setup changes.
6. CI: the blocks, the guard, the core's template with the bootstrap trigger (decision 9), the fixture's template, and `python3 wsc.py ci render`.
7. Docs (decisions 12-14 in CONSUMING.md, with the migration below), C23, the tools row and `VERSION`. Then `python3 wsc.py gates` (full) and
   `python3 wsc.py policy --branch job/W23 --base origin/main`. The second prints the fallback note: the base predates W23.

## Tests and acceptance (what done looks like)
- Every test in step 2 is red at its commit on the starting code (name the sha in the report) and green at the end, in Linux and Windows CI. Every existing
  test is green. The `GOLDEN` hashes change in one commit, which says why.
- `grep` of the rendered `.github/workflows/policy.yml` shows `pull_request_target`, the bootstrap `pull_request` with its path filter, and no
  `${{ github.head_ref }}` inside a `run:` line. `warscape/policy.py` no longer runs git with `ctx.root` as its cwd.
- W23's pull request shows a `policy` run from the bootstrap trigger. It is green once the review says merge, and its log carries the fallback note.
- **After the merge (not part of this job; the report hands it on).** The next pull request's `policy` run must show event `pull_request_target` and the
  line `judged with the rules of origin/main at <sha>`. The orchestrator records that run id in W27's brief. If no `policy` check appears on that pull
  request, a `meta/` revert of the trigger restores the old one, and the report of that revert says what GitHub did.

## VERSION
A minor bump: a changed consumer contract (policy-stage facts and the base tree), a changed workflow render that every game must adopt in its bump commit (the
render guard), and a new verb flag. `origin/main` stood at 0.22.0 when this brief was written; `job/W20` holds 0.23.0 on its branch, and W22 and W24 also
bump. Take the next free minor at merge time: re-read `origin/main` `VERSION` and the open `job/*` branches before the last commit. If another job merges first,
take the next number and merge `main` (never rebase), and say which number you took. Tags are Liam's.

## What consumers must do after the tag (napoleon-remastered J78; also goes into `docs/CONSUMING.md`)
In the pin-bump commit, because the render guard and the new facts fail otherwise:
1. **`ci/policy.yml.in`.**
   - Use `on: pull_request_target`, with the same types.
   - For that bump's own pull request, add the bootstrap `pull_request` trigger with `paths: [jobs/J78/report.md]`. Remove it in the next change to the
     template; `ci_render` warns until then.
   - Run `wsc ci render`.
2. **`policy_extra_steps`.** It now runs in the base checkout, where `HEAD` is the base. Take the head's sha from an `env:` value
   (`github.event.pull_request.head.sha`), never from `${{ }}` inside `run:`. Make both pins present in `core/` for `core_pin_diff`.
3. **`tools/gates/pipeline.py`, the policy stage.**
   - Run git at `ctx.facts['repo']` with the `head`, `base` and `merge_base` shas: `show`, `show_first`, `core_pin_diff` and `collect_acceptance`.
   - Never use `ctx.root` (the base tree, not a repo) or `'HEAD'`. A module left as it is fails closed, as a crash.
   - `ctx.root/core/...` is now the base's core. `dll_build_id` must call the base's `build_id.py` over the head (`build_id(repo, head)`) and must not
     execute the head's copy.
   - When a bump changes `build_id.py` itself (W24 does), the base's algorithm cannot reproduce the head's build id. J78 needs a rule for that, and the
     default it gets is a refusal.
4. **Behaviour.**
   - CI judges the pull request's head against the base tip, not GitHub's merge commit. A branch behind `main` on `docs/DECISIONS.md` must merge `main`.
   - Meta globs match by segment: 232 files instead of 564 today. J73 also drops `core` and `registries/*`.
   - Until the bump merges, Napoleon's pull requests are judged as before W23, with the note.

## Kill criteria
- Any step would check out, build, import or run the head's content inside the `pull_request_target` job: stop and report. Never trade a bypass for a security
  hole.
- A rule cannot be judged from git objects plus the base tree, because it needs a head file on disk or the head's code: stop and report which rule and what it
  needs. Do not add a key or extract more of the head to make it work.
- A game's base pin cannot be extracted from the submodule's object store on one of the CI platforms within about 15 calls: stop and report the git error.
- The fixture game's existing assertions have to change beyond setup to stay green: stop and report, because the contract is leaking.
- W23's own pull request gets no `policy` run from the bootstrap trigger after the reviewer's `gh pr ready`: stop and report. The fallback is open question 3.
- Core CI red after three fix attempts for a cause in this change: stop and report. Version collision as in VERSION; never rebase a pushed branch.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
Answered 2026-11-04 by Liam: all three as recommended ("Yes, pull_request_target", "Accept and document it", "Yes, keep the fallback").

1. **`pull_request_target` for the policy workflow?** Recommended: yes (decision 8).
   - It is the only per-repository way to take the workflow from the base. The job never runs head content, and the head's names reach scripts through
     `env:` only.
   - Alternative: keep `pull_request` and only base-judge in the verb. That closes the four bypasses and the gitlink, but the head's own `policy.yml` still
     decides what CI runs, so one edit turns the check into `true`.
2. **The residual: a forged check.**
   - Any holder of a write token can post a status named `policy`, and GitHub calls same-named jobs in two workflows ambiguous. A head that adds a workflow
     with a `policy` job can blur the result. No code in a user-owned repository closes this.
   - Recommended: accept it for now and say so in CONSUMING.md ("what the policy check does not prove"). Then a later row refuses a `job/` branch that adds
     or changes `.github/workflows/` unless its brief on the base names the file. The rule would be judged by the base's code and would check text, not YAML.
   - Alternative: an organisation-owned repository with a "require workflows to pass" ruleset. That means moving the repositories.
3. **The transition fallback (decision 6).** Recommended: keep it, bounded to bases without `JUDGE_API`.
   - Alternative: refuse such bases. Then Liam merges W23, and later Napoleon's J78, with a ruleset bypass after their reviews.
   - The bootstrap trigger is removed by W27's brief either way. It is inert meanwhile, and `ci_render` warns about it.

## Finish
Write the report in `jobs/W23/report.md`. It covers:
- the design as built;
- the test list, red then green, with the red sha;
- the bootstrap run's id;
- the version and C number taken;
- deviations, open questions, and the consumer steps if they changed;
- the hand-on in "after the merge".

Then run `wsc reg set jobs W23 status=review report=jobs/W23/report.md` (`python3 wsc.py`). Push `job/W23`, open the draft pull request, and stop. An
independent reviewer merges (C18), and Liam tags.

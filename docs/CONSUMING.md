# Consuming the core from a game repo

How a game repo (napoleon-remastered first) uses warscape-core at a pinned version. **Proposal, 2026-10-28: nothing is wired into
a game repo until Liam approves.**

## Recommendation: a git submodule at `core/`, pinned to a release tag

The game repo carries the core as a submodule at `core/`, checked out at a tag (`v0.1.0`), and repeats the tag in its `wsc.toml`
(`[core] version = "v0.1.0"`). Commands run from the game repo root as `python3 core/wsc.py <verb>`.

Why this one: it is the only option where "a game repo never patches the core in place" (napoleon `PLAN.md` section 4) holds by
construction. An edit inside `core/` cannot be committed to the game repo; it can only be pushed to warscape-core, through a PR.
The `core_pin` gate adds the rest: it fails when the checkout has local changes, when its `VERSION` is not the pinned version, and,
when the pinned tag is in the checkout, when HEAD is not that tag's commit. A shallow checkout without the pinned tag (CI's depth-1
submodule brings only the core tip's tag) and a checkout with no tags are compared by `VERSION` only; a full checkout that has other
tags but not the pinned one fails and names the fix, `git -C core fetch --tags` (C21).

The options weighed against it (subtree, a vendored copy, `pip install`) and the costs of the recommendation: [CONSUMING_OPTIONS.md](CONSUMING_OPTIONS.md).

## Wiring a game repo (the steps, once approved)

```sh
git submodule add ../warscape-core.git core
git -C core checkout v0.1.0
git config core.hooksPath core/.githooks          # per clone, also on Liam's PC
# write wsc.toml (below), then:
python3 core/wsc.py reg render                    # creates the empty registries and their views
python3 core/wsc.py reg add tools --missing       # rows for every tool that has a header
python3 core/wsc.py gates
```

Minimal `wsc.toml` for a game repo:

```toml
registries_dir = "registries"

[registries]
tools = "core:tools"
scenarios = "core:scenarios"
assets = "core:assets"
ui_elements = "core:ui_elements"
engine_sites = "core:engine_sites"
config_keys = "core:config_keys"
hotkeys = "core:hotkeys"
engine_facts = "core:engine_facts"

[core]
version = "v0.1.0"

[tools]
exempt = ["tests/**", "**/runs/**"]

[docs]
max_kb = 30

[cli]
verb_dirs = []        # e.g. ["adapter/verbs"] for game-specific verbs (same contract; never a core verb's name: reg find gates jobs policy ci discovery crash agent-settings)
```

CI in the game repo (`.github/workflows/gates.yml`):

```yaml
name: gates
on: [push, pull_request]
permissions:
  contents: read
jobs:
  gates:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v5
        with:
          submodules: true
          token: ${{ secrets.WARSCAPE_CORE_TOKEN }}
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
      - run: python core/wsc.py gates
```

## Game proxy tests and the pin file schema (0.34.0, W16; [PROXY_HARNESS.md](PROXY_HARNESS.md))
- **Move the checks the core dropped:** `test_console.cpp` and `test_camera.cpp` no longer check a game's console and camera numbers. Add them to the
  game's own `proxy/tests/` (the text is in core `jobs/W16/report.md`, "Consumer test files"); `core/proxy/tools/build.sh tests` lists them as game tests.
- **Pin file:** `python3 core/proxy/tools/fetch_ui.py --check` must pass (add `stb_image_write` if missing; extra pins such as `emsdk_image` stay).
- **Rule 79:** `build_sh`, `build_id` and `fetch_ui` changed, so the build id changes with no `proxy/src` change: 20 passes on the new id.
  Optional: exempt `proxy/tests/` from the game's rule-79 path (not a DLL input). `--docker` from the game repo works as before.

## Upgrading and releasing

- **Releases (0.36.0, W29, C27):** the `release` workflow tags; nobody else does. After `gates` passes on `main` it computes the version from the
  rows done since the last tag (`semver` on each row; `[jobs] semver_from` on), opens `release/vX.Y.Z` (VERSION only), auto-merges it and puts an
  annotated tag on the merge commit; each `[release] consumers` adapter is compiled first (`warn`: a failure goes in the tag message and an issue).
  `python3 wsc.py release plan` says what the next run does. The secret, the tag ruleset and the manual 1.0.0 path: [RELEASES.md](RELEASES.md).
- **Game upgrade:** `python3 core/wsc.py core bump vX.Y.Z` (from 0.36.0 on; a bump to 0.36.0 itself is the hand steps: `git -C core fetch --tags`,
  check out the tag, set `[core] version`, `ci render`): one commit of `core`, `wsc.toml` and the workflows (B9); delete each verb it names. Then `gates`.
- **A change a game needs** is a PR here with host tests, then a release, then the upgrade above. Never a commit inside `core/`.
- **Upgrade notes** for a pin bump past 0.24.0 (the `commit-msg` hook, the `run_refs` gate), 0.26.0 (base-judged policy, C24), 0.27.0 (the build id, C25)
  0.34.0 (DLL changes, C29) or 0.38.0 (crash maps, guarded verbs, C35) are in [UPGRADING.md](UPGRADING.md).

## Registry storage and views (0.6.0, opt-in)
Moved to [CONSUMING_OPTIONS.md](CONSUMING_OPTIONS.md) "Registry storage and views" on 2026-11-04 (W28, the 30 KB cap): `[storage] dir`, `[views] commit`, `reg migrate`, `reg remove`.

## Tool retirement (0.37.0, core W15, C33; opt-in)
A tool's last use is the later of its row's `last_used` (the floor: the day the row was added, or `wsc reg set tools <id> last_used=<date>`)
and the newest `done` job whose `jobs/<id>/report.md` cites it, dated by the newest `## Round N (YYYY-MM-DD, ...)` heading of its `review.md`
(a legacy review: the first date in its first 5 lines). It is derived from the working tree at check time; nothing writes it into rows.
- **Citation:** the tool's `path` as a whole path (`core/` before it still counts; xharness/job.sh or harness/job.sh.bak does not), or,
  for a verb, `wsc <verb>`, `wsc.py <verb>` or `wsc.<verb>`.
- **Opt in:** `[tools] retire_after_days = 90` (default 0: off; the core keeps 0, its tools' uses are in its consumers' reports). Then
  `python3 core/wsc.py reg check tools` warns per stale live tool, naming where its date came from (the report's path in brackets, or `(row)`):
  supersede it, `reg remove` it after deleting the file, or cite it in the next report that uses it.

## Extending a core schema (0.17.0)
A game that needs a field a core schema lacks does not copy the schema (its copy would miss every later core change): its own schema
names the core one in `x-extends` and holds only what it adds, and `wsc.toml` points the registry at it.
```json
{"x-extends": "core:hotkeys", "required": ["owner"], "properties": {"owner": {"type": "string", "minLength": 1}}}
```
`hotkeys = "schemas/hotkeys.schema.json"` in `[registries]` then validates rows against the merged document: every core rule still
applies, `additionalProperties: false` now covers `owner` too, and `wsc reg render` writes `owner` after the core fields. The document
may add `properties`, `required`, `allOf` entries (to narrow a core property), `$defs` and `x-unique` tuples, and replace `title`,
`description`, `$id` and `x-view`; any other key, a core property redefined or a `$defs` name clash is a load error (merge rules:
`warscape/registry.py` docstring). A game that already copied a core schema can switch; its rows' key order may change once
(`wsc reg render`, a one-off diff).

## The job pipeline (0.9.0, napoleon J62, C18)
The queue, the pull-request policy and the CI helpers are core verbs (`wsc jobs`, `wsc policy`, `wsc ci`) that a repo configures; a repo with none of the
tables below behaves as a plain queue. Defaults and the exact keys: `warscape/repo.py` `DEFAULTS` (the loader refuses a key it does not know, so a new table
reaches a game only with a core release). Procedure for a reviewer: `docs/REVIEW.md`. The core itself is the reference consumer (`wsc.toml`, `ci/`,
`registries/jobs/`) and `tests/fixture_game/` is a second, minimal one that the host tests drive.

```toml
[registries]
jobs = "core:jobs"                 # the schema; ids are one capital letter and a number
[storage]
dir = ["jobs"]                     # one file per row: two job branches never conflict on the registry
[views]
commit = false                     # the queue and committed views do not mix (below)
[jobs]
id_prefix = "J"                    # job ids J<n>, branches job/J<n> and brief/J<n>
dir = "jobs"                       # jobs/<id>/brief.md, report.md, review.md
models = ["sonnet", "opus"]        # the Model line of a brief; models after the first need a stated reason
legacy = "jobs/legacy.json"        # {"round_rules": [ids], "brief_hooks": [ids]}: jobs written before a rule existed, exempt from that rule only
ledgers = "jobs/*/rules.md"        # optional: audit ledgers whose `CL` rows name a job the brief must cover
pc_state = "$LOCALAPPDATA/game_state"  # optional (W26): a needs_pc build is not ready where this folder is absent; WSC_PC_STATE overrides ("" = no PC here)
failed_results = "raw/**/*.json"   # optional, off when empty: a glob inside each run folder a report cites (any `runs/<name>` path in its text); a JSON with top-level status "failed" must be named (path or file name) in that report's `## Deviations`
claim_hours = 4                    # W27: a review claim (refs/claims/<id>/round-<n> on origin) older than this is taken over
[jobs.text]                        # every repo-specific string in the step texts: commands ({wsc}), doc paths, decision references
[policy]
decisions = "docs/DECISIONS.md"    # append-only rows | <prefix><n> | YYYY-MM-DD | who | decision | yes/no |
decision_prefix = "D"
bootstrap = []                     # exact branch names exempt from the branch-kind rules: only the one pull request that introduces the pipeline
session_trailer = "Claude-Session" # who wrote the report may not write the review; "" switches the rule off (and W27's rules A-E)
decisions_cite_job = false         # W27 rule F: a decision row added on job/<id> must contain <id>
thin_merge_lines = 500             # W27 rule E: a `merge` on more lines (or thin_merge_files = 20 files) outside jobs/ and the registries citing no evidence warns
plan = [...]                       # globs a plan/* branch may touch, by path segment (* in one folder, ** across); meta = [...] for meta/*
[ci]
inputs = { ... }                   # set name -> regex: the paths that make that slow job run (`wsc ci inputs`)
workflows = ["gates.yml", "policy.yml"]   # rendered from ci/<name>.in by `wsc ci render`; the `ci_render` gate fails on a difference
required_checks = ["gates", "policy"]  # what main must require (`wsc ci check-settings`); [] = every workflow job but changes and notify (0.22.0)
```
- **Committed views and the job queue do not mix (C19).** A `brief/<id>` branch may change only `<jobs dir>/<id>/brief.md` and its row, but a committed
  jobs view (`[views] commit = true`; the core's view is `_scratch/registries/jobs.md`, never committed) changes with every `reg set` (so `policy` refuses the branch), and the `registries` gate refuses a stale one (so `gates` fails the
  branch if the view is left alone): no brief can pass both. A repo with a jobs registry sets `[views] commit = false` and does not list a view in `[policy]
  plan`/`meta`. `wsc jobs check` and the `jobs` gate refuse the combination (`[views] commit = true` with a `jobs` registry, C19) and say what to change, and `policy` marks a committed registry view in its brief-branch refusal.
- **The `jobs view` page** loads marked 12.0.2 from cdnjs with its Subresource Integrity hash (`jobq.MARKED_SRI`), shows raw HTML in a brief, report or
  review as text (marked's `html` renderer escapes it), and carries a Content-Security-Policy: scripts from that one URL and the page's inline script by hash,
  styles by hash, `connect-src 'self'` (W28). A new marked version is a new URL, hash and test.
- **Claim and autopilot (core W26, C32).** `wsc jobs next` claims before it prints: a create-only push of `origin/main` to `job/<id>`
  (`brief/<id>`); a lost race moves on, any other failure exits 1. `--peek` and `--offline` claim nothing. Order is (phase, number). An empty claim
  older than 24 h is listed with its release command. `--auto` starts a review only on a green head, a fix once CI has finished, one `needs_pc` row
  at a time, and prunes dead worktrees each tick. A game: sets `[jobs] pc_state` and has its `setup` verb print
  `warscape.worktrees.report(root, rows, branches)`; `wsc jobs worktrees [--prune]` prints the same.
- **A game's own rules** are gate modules with the `jobs`, `policy` and `view` stages ("Game gates", below; `[jobs] hooks` is gone since 0.20.0).
- **A pull request is judged with its base's rules (0.26.0, W23, C24).** `wsc policy --branch B --base origin/main [--head REV]` (`--head` defaults to
  `HEAD`) writes the base's rule inputs into a temporary folder and runs the base's own code there in a child process: inside the core, the base
  commit's tree; in a game, the core commit the base's `core` gitlink pins (read from the submodule's object store: `git submodule update --init`),
  plus the base's `wsc.toml`, `[gates] dirs` and `[jobs] legacy` file. The head reaches it only as git objects: its diff, the blobs the rules read,
  its trailers. A branch that changes the core, `wsc.toml`, a gate module, the legacy file or the policy workflow is judged by the old ones, with a
  note. **`git fetch` first**: a stale `origin/main` judges with stale rules. The same two shas print the same lines anywhere; CI is the authority
  (its parent is the base's code, a local one your checkout's). It judges the head commit against the base tip, not GitHub's merge commit, so a
  branch behind the base on the decisions file is told to merge it. It fails closed, naming the fix: a ref that does not resolve, an unreadable base
  `wsc.toml`, no gitlink, an uninitialised submodule or a missing pin (`git -C core fetch origin <pin>`), or a child with no verdict. A base whose
  core predates W23 (no `JUDGE_API` line) is judged as before, with a note. `--commit-msg` stays a local check of the message being written.
- **What the `policy` check does not prove.** Anyone with a write token can post a status named `policy`, and GitHub calls same-named jobs in two
  workflows ambiguous, so a head that adds a workflow with a `policy` job can blur the result. No code in a user-owned repository closes this (an
  organisation's "require workflows to pass" ruleset would); it is accepted for now (W23), and the reviewer reads any `.github/workflows/` change.
- **Workflows are rendered, not called.** A reusable `workflow_call` workflow would rename the checks (`<caller job> / <called job>`), and branch protection
  waits for exact names. `ci/<name>.in` is the workflow with placeholder lines (`{{wsc changes}}`, `{{wsc if <set>}}`, `{{wsc pass_marker <set>}}`,
  `{{wsc fetch_cache}}`, `{{wsc policy}}`, `{{wsc notify ...}}`: `warscape/ci_render.py`); the slow jobs stay in the template. After a change: `wsc ci render`, commit both files.
  A template with `{{wsc policy}}` must trigger on `pull_request_target` (W23): GitHub then runs main's copy of the workflow, never the head's, so
  a branch cannot edit its own check. `wsc ci render` and the `ci_render` gate refuse one without it and warn while a `pull_request` trigger remains.
- **A job that builds the proxy** puts `{{wsc fetch_cache}}` after its checkout and before `build.sh all` (0.22.0; two steps from 0.27.0): the
  fetchers' raw downloads cached by the pins (`netfetch.py ci-cache`), so a warm cache builds offline. The fetchers retry their own network flakes
  (0.27.0) and their sha256 checks judge every byte; a cache fault never fails the job.
  Only for jobs that run `build.sh` (the fetchers write `<game root>/build/lua` and `build/ui/src`): a job whose own fetcher writes
  elsewhere (a review viewer fetching into `build/viewer/src`) gains nothing from it.
- **Main health (0.30.0, core W22).** A red required check on `main` is no longer permanent and silent. (1) *Rerun:* the `changes` job has no diff base on a
  push to `main` (`base=''`, the old `$BEFORE` is gone), so every set counts as changed and only a pass marker for its input tree skips it; a failed run saves
  no marker, so the next push reruns the set (a squash merge is a new tree and runs; a docs-only push finds its predecessor's marker and skips; an evicted
  cache costs one extra run, never a wrong skip). Branch pushes are unchanged. (2) *Report:* `{{wsc notify gates ...}}` also renders a `main_health` job
  (`always()` on a push to `main`, `continue-on-error`, `issues: write`, not a required check) that runs `wsc ci main-health`: one issue per red required job,
  titled `CI is red on main: <job>`, found by a hidden mark at the start of its body (no label), one comment per run and attempt, closed with a comment once the
  job is green; a run that is not main's tip does nothing; a problem it can explain prints and exits 0. Required jobs are `[ci] required_checks` that the run
  produced, else every job but `changes`, `notify` and `main_health`. (3) *Read:* `wsc jobs next|review|fix|view` print `main is RED: ...` lines first (the latest
  completed push run of each workflow), "unknown" when `gh` cannot say, nothing when green; `--offline` skips it. Consumers re-render after the pin bump
  (`python3 core/wsc.py ci render`; no template change) and enable Issues in the repository (`wsc ci check-settings` says when they are off).
- **The proxy job runs the smoke on your adapter** (`build.sh smoke`, 0.27.0): each step asserts what that game's build must do. A game without a
  `GestureAdapter` passes steps 6 and 7 on the inert path (the log says "no adapter"), and step 8 peeks the first engine site in the game's
  generated tables (a game with no engine sites checks the stale request only). The core proves both paths: the null game, and the fixture
  `proxy/tests/null_game_no_gesture`.
- **Settings only the owner can make** (no verb changes a repository setting): require the checks `gates` (and `proxy`, `harness-windows` or whatever slow
  jobs the repo has) and `policy` on `main`, allow auto-merge, require no approving review (one account cannot approve its own pull request), and set `WARSCAPE_CORE_TOKEN` (or the `[ci] token_secret` name) only if the core is private.
  Until required checks exist, `gh pr merge --auto` has nothing to wait for and merges at once. `wsc ci check-settings [--repo owner/name]` reads them
  (`gh api` GETs only) against the workflows and `[ci] required_checks` and names each one missing (exit 1; 2 when it cannot read them). A matrix job's
  checks are named per value (`gates (ubuntu-latest)`): list those in `required_checks`.
- **Upgrading from a repo that has its own pipeline** (napoleon J62): move the texts into `[jobs.text]`, the rules that are not generic into a gate module,
  turn each workflow into `ci/<name>.in`, run `wsc ci render`, delete the local copies in the same pull request as the pin bump (B9: the pin and `wsc.toml` version in one commit).

## Game gates (0.20.0, core W13, C22)
A game adds its own checks as **gate modules**: `wsc.toml` `[gates] dirs = ["tools/gates"]` (repo-relative folders), and every `*.py` in a listed folder whose
name does not start with `_` is loaded, in folder order, then file-name order. The contract is one docstring, `warscape/gatemods.py`; in short:

```python
"""<what it checks>
purpose: ...  usage: ...  when: ...
not-a-verb: a gate module, run by wsc gates
"""
NAME = 'no_todo'                        # [a-z][a-z0-9_]*; never a core gate's name nor another module's
STAGES = ('gates',)                     # optional, default ('gates',): any of gates, jobs, policy, view
FAST = True                             # optional: a gates-stage module is in --fast (or name it in [gates] fast)

def run(ctx):                           # ctx: the repo context, plus ctx.stage and that stage's inputs
    from warscape.gates import Result   # inside run if the game's own tests import the file without core/ on sys.path
    bad = [p for p in ctx.files() if p.startswith('docs/') and 'TODO' in (ctx.root / p).read_text(encoding='utf-8')]
    return Result(NAME, 'error' if bad else 'ok', f'{len(bad)} docs say TODO', bad)   # level ok | warn | error
```
- **Stages.** `gates`: its own line in `wsc gates`, after the core gates (`[gates] skip`, `fast` and `--only` take its name). `jobs`: the `jobs` gate and
  `wsc jobs check`, with `ctx.rows`, `ctx.read(path)` and `ctx.briefs()` (`(jid, row, text)` per brief, minus the legacy file's `brief_hooks` ids); an `error`
  Result's details are queue problems, a `warn` Result's print, a non-empty summary goes on the `jobs check` line. `policy`: `wsc policy` only, run from the
  **base tree** (W23): `ctx.root` and `ctx.config` are the base's rule inputs in a temporary folder, not a repository; `ctx.facts` has branch, kind, jid,
  changed, `added_decision_rows` ([{id, text}], W27), merge_base, `base` and `head` (shas), `base_ref` and `repo` (the clone: run git there). Read the head as data with `from warscape.policy import show`,
  `show(sha, path, cwd=repo)`; never `'HEAD'`, never git in `ctx.root`, never run the head's files. An `error` Result's details are policy errors. `view`: `wsc jobs view`,
  with `ctx.rows`; the Result's `html` is drawn as is at the top of the page, else its escaped summary and details. A crash is an `error`.
- A module is a tool like any script (header and a `tools` row). A listed folder that does not exist, a clashing or malformed `NAME`, an unknown stage, a missing
  `run`, and a module that still defines one of the old hook names are load errors (`wsc` exits 2 naming the file).
- **Moving off `[jobs] hooks`** (removed in 0.20.0 with no shim: the loader refuses the key and names this section). In the pin-bump commit itself (B9), because the
  new core refuses the old key; for napoleon-remastered (rehearsed on a copy, W13 report):
  1. `wsc.toml`: delete `hooks = [...]` from `[jobs]`; add `[gates]` with `dirs = ["tools/gates"]`.
  2. `git mv tools/jobs_hooks.py tools/gates/pipeline.py` (a folder of its own: every `*.py` in it is loaded). Rename the five old functions (napoleon:
     `brief_rule`, `gap_summary`, `queue_rule`, `policy_rule`; `view_panel` goes) and add `NAME = 'pipeline'`, `STAGES = ('jobs', 'policy', 'view')` and a `run(ctx)`
     that dispatches on `ctx.stage`: `jobs` returns the found-path problems from `ctx.briefs()` with the prefix the core used to add (`f'{jid}: brief: {e}'`) plus
     `queue_rule(ctx, ctx.rows, ctx.files())`, summary `gap_summary(ctx, ctx.rows, ctx.read)`, level `error` when any; `policy` returns `policy_rule(ctx, ctx.facts)`;
     `view` returns `Result('pipeline', 'ok', 'PC state' if pc else '', html=pc_block(pc))` with `pc = pc_state(ctx.root)` (an empty Result draws nothing off the PC).
     Paths relative to the file move one folder down: `_usage_reader`'s folder is `parents[1]` (tools/), `acceptance_active`'s default root `parents[2]`; the
     rule 76 message names `tools/gates/pipeline.py`.
  3. `python3 core/wsc.py reg add tools tools/gates/pipeline.py --id tools.jobs_hooks` (the row keeps its id) after updating the header (`[gates] dirs`, `not-a-verb:
     a gate module, run by wsc gates`), then `reg add tools` for the two headers that name the file (`tools/usage_reader.py`, `discovery/core/briefpaths.py`).
  4. Tests in the game's `tests/` that load the file by path or call the old names: `test_jobs_hooks.py` (module path, the three source-text reads, the
     renamed functions), `test_build_id.py`, `test_registry_merge.py`, `test_repo_rules.py` (`MOVED_ALLOWED` key and the loader), `test_usage_reader.py`
     (`sys.path` gains `tools/gates`, `import pipeline as hk`), `test_proxy_host.py`.
  5. Living docs: `git grep -n "jobs_hooks\|hook module\|policy_problems"` outside dated job folders (`CLAUDE.md`, `docs/REVIEW.md`, `harness/README.md`,
     `docs/plans/PLAN.md`, the `wsc.toml` comments).
  6. Run `python3 core/wsc.py gates`, `jobs check` and `policy --branch <the pin-bump branch>`: the `jobs check` line and the page's PC block read as before.

## Review integrity (0.35.0, core W27, C30)
`wsc policy` checks a job branch's review rounds and cited evidence (rules A-F: the `warscape/policy.py` docstring); warnings print as `policy: warning:`
lines and never refuse. `jobs review` and the autopilot claim the round on origin (`refs/claims/*`). A report beside `jobs/<id>/handback.md` needs
`## Orchestrator additions`. A game: opt in to `decisions_cite_job` in its pin bump; stub `print_claims`/`take_claim` in tests that run `jobs review`.

## Gate changes in 0.36.0 (W28, C31)
Moved to [UPGRADING.md](UPGRADING.md) on 2026-11-04 (the 30 KB cap): `[gates] skip` ids, `verified_dates`, strict `json`, `doc_paths`, `gen_tables.py`.

## The proxy, the harness and the save tools (0.4.0)
Moved to [PROXY_HARNESS.md](PROXY_HARNESS.md) on 2026-11-04 (the 30 KB cap): what the core carries for a game (the proxy core, the watcher
kit, the save tools), how the tools find a game's adapters, the UI pin file, and the contract doc of each proxy feature.

## The game lock is the session's (0.29.0, core W10, C26)
The holder of `game.lock` is the pair (owner, session); the default owner is the session id, so two sessions can no longer share a lock by a shared name.
Set `WSC_SESSION_ID` in the session (or pass `--session`; Claude Code's Bash tool already exports `CLAUDE_CODE_SESSION_ID`, which `ctl.py` and `acceptance.py` use
when `WSC_SESSION_ID` is unset) and drop `--owner`. With no session id and no `--owner` both tools refuse (exit 2) and say so. Scripts that name an owner
(`--owner claude-acceptance`) keep working and need only a session: the same owner with a different session is refused like another owner's until the lock is stale.
- `job.sh`: one owner rule `^[a-z0-9][a-z0-9_-]{0,39}$` everywhere (scratch was 32), exact-case in the watcher; `lock -` makes the owner the session id; `lock --wait S` polls (max 100);
  `touch <owner>` and `unlock <owner>` act only on the holder's lock (a bare `touch` is refused, 64); `holds <owner>` asks; `ctl` and `shot.sh` need the lock (take it with `job.sh lock` first).
- The watcher accepts the lock's `session=` as the request `owner=` too; update the PC's watcher to **1.4.0** (`update kit=`) before relying on that or on the exact-case compare.
- The stale age is `lock_stale_min` from `watcher.ini` (default 20) on both sides. Waits: `job.sh` and `job.sh ctl` default to 100 s (the Bash tool gives up at 120 s); a timed-out
  request is withdrawn (`.request.expired`), so a script that relied on it staying queued must pass a longer wait and run in the background.
- A ps1 job exits with its last statement's code, not an old native one: end a script with `exit 0` when a tool's non-zero code means success (robocopy 1 to 7).
- `kill` returns when `watcher.status` already says `not_running`; the prefs overlay sets every copy of a duplicated key; `pc_deploy set --state` waits up to `--wait-restore` (30 s) for a pending profile restore, else refuses.

## pc_deploy takes the lock; exe_check is a start-time setting (0.33.0, core W25, C28)
Moved to [UPGRADING.md](UPGRADING.md) on 2026-11-04 (the 30 KB cap).

## DLL changes from W34's tag (W34, C36)
- **`GameAdapter`:** the core asserts its size (`proxy/src/adapter.h`). A new field goes at the **end**, with a default. Initialise it by name: `.gameName = ...` compiles in the
  DLL's `-std=c++17` as a GNU extension, and a missing member still fails `-Wextra -Werror`. A positional list still compiles, but an inserted field shifts it silently.
- **ctl `lua`:** reads only under `luaDir` and the ctl folder ([PROXY_CTL.md](PROXY_CTL.md)). Move a chunk from anywhere else into one of the two.
- **The ctl folder is owner-only:** a driver running as another user cannot use it; say so in the pin-bump report.
- **System keys** always reach the game, with RmlUi text focus too ([PROXY_UI.md](PROXY_UI.md)).
- **`gen_tables.py --exe <staged copy>`:** add it to the exe-update checklist, after `exe_info.py`, before a PC run. The build id changes.

## Discovery (optional extras)
From 0.15.0 (napoleon J64, C20) the core carries the discovery passes (`discovery/`, the `discovery` verb, `proxy/tools/exe_info.py`; old-to-new paths in `discovery/README.md`).
- **Adapter files a game provides:** `wsc.toml` `[discovery] adapter = "<folder>"` (else the one `discovery/*/games.json`) holding `games.json` with `"target"` and `"reference"`
  (the two games' names, used for the result fields and README titles), `"extract"`, one entry per name (`root`, `exe`, `data`, `pack_order`, `mod_packs`; the reference also
  `repo`; the target optionally `captures`), plus `carry_over.json`, `gate.json`, `asset_roles.json`, `db_schema.json`, `console.json`, `engine_api.json`, `lua_cfuncs.json`,
  `probe_safe.json`, `exe_strings.tsv.gz`, `shader_catalog.json`, `frame_anatomy.md`, `shaders/`. Results stay in the game repo (`discovery/<area>/`, the registries). The identity
  (`exe_name`, `sha1`) for `gate --install` is the proxy adapter's `identity.json`. A game verb named `discovery` is a load error: delete it in the pin-bump commit.
- **Extras, PC side only; the gates never need them.** `sheets` needs Pillow (`python3 -m pip install --user -r core/discovery/requirements.txt`, pinned there). The static
  x86 tools (`x86re`, `console_cmds`, `exe_strings build`) need capstone and pefile in the RE environment: `python3 core/discovery/re_env.py <dir outside the repo>` downloads the
  wheels pinned by sha256 in that file and builds the venv, then run the tool with `<dir>/venv/.../python -I`. A tool that lacks its extra stops with a message that names this fix;
  the host tests skip the capstone cases without it.
- **`find` and the exe index (0.37.0, W15):** `python3 core/wsc.py find <word>` also searches the adapter's `exe_strings.tsv.gz` for exe-shaped
  words (4+ characters with an inner `_` or a lower-to-upper case change: `gfx_hardware_shadows`, `CampaignUI`; every word must appear, as literals,
  case-insensitively); `--exe` forces it for any word, `--in exe_strings` searches only it. Without the table `find` prints what it always did.
- **Re-run steps:** `python3 core/wsc.py discovery all` on the PC, then `discovery check` and `git diff --stat` (empty when nothing changed in the game); `discovery check` and
  `discovery gate` need only committed files and belong in the game's thin real-repo test.

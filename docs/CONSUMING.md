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

## Hooks and gate keys added in 0.24.0 (C23)

- **`.githooks/commit-msg`** refuses a commit whose message has no `Claude-Session:` trailer with a value (read with `git interpret-trailers --parse`, as `policy` reads
  pushed commits: git sees a trailer only in the last paragraph, with `Co-Authored-By:`). Opt in with `[policy] commit_msg_hook = true` (default `false`; it uses
  `[policy] session_trailer`, and an empty name switches it off). Merge commits are skipped; fix a refusal with `git commit --trailer "Claude-Session: <id>"`;
  a human commit bypasses once with `--no-verify`. Same wiring as the pre-push hook (`core.hooksPath core/.githooks`). It runs `wsc policy --commit-msg <file>`.
- **`run_refs` gate** (fast set): every repo path a tracked `**/runs/**/README.md` names (link targets and backticked paths) must exist: from the root, from the README's
  folder, as the tail of a tracked path, inside a submodule, or git-ignored. `[gates] run_refs_since = "YYYY-MM-DD"` skips run folders dated before it (default `""`:
  all checked); set it to the pin-bump date when old READMEs name moved paths.

## The build id names one DLL (0.27.0, W24, C25; [PROXY_BUILD.md](PROXY_BUILD.md))
- **Rule 79:** a new build id (`core`, `build_sh`, `build_id`, `fetch_lua`, `fetch_ui` changed, `toolchain` new) and new DLL bytes: 20 passes.
- **CI:** install `$(python3 core/proxy/tools/toolchain.py apt)` with `--no-install-recommends` instead of `g++-mingw-w64-i686` (else `build.sh`
  refuses once the archive moves), then `wsc ci render` (`{{wsc fetch_cache}}` is two steps). `build_id.py` test fixtures copy `toolchain.py`.
- **PC:** nothing; `--docker` installs the pins. Off the pin, `WSP_TOOLCHAIN=any` gives a `-dirty` DLL; an untracked source refuses the build.
- `proxy.log`'s second line is `self_hash: ...`; `ctl.py` `build_info()` returns `dll_sha256`.

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
verb_dirs = []        # e.g. ["adapter/verbs"] for game-specific verbs (same contract as warscape/verbs/)
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

## Upgrading and releasing

- **Core release:** a PR bumps `VERSION`; after Liam merges it, the tag `vX.Y.Z` is cut on that merge commit. Tags are never moved.
- **Game upgrade:** `git -C core fetch --tags && git -C core checkout vX.Y.Z`, set `[core] version` to the same tag, run
  `python3 core/wsc.py gates`, commit `core` and `wsc.toml` together on a branch.
- **A change a game needs** is a PR here with host tests, then a release, then the upgrade above. Never a commit inside `core/`.

## Registry storage and views (0.6.0, opt-in)
Two `wsc.toml` tables, both off by default (a repo that sets neither keeps one JSONL per registry and committed views):
```toml
[storage]
dir = ["jobs", "tools"]     # these keep one file per row: registries/<name>/<id_to_file(id)>.json
[views]
commit = false              # views go to the git-ignored dir (default "_scratch/registries"); a committed registries/<name>.md fails
```
- **Why:** two branches in flight that each add a row to one JSONL, or re-render one committed view, conflict on GitHub (it ignores
  `merge=union` on pull-request merges), so auto-merge stalls until someone merges `main` by hand. One file per row and uncommitted
  views remove both causes (napoleon J55).
- **Switching:** `python3 core/wsc.py reg migrate <name> --to dir` moves the rows and rewrites `[storage] dir`; `--to jsonl` goes back.
  With `commit = false`, `git rm` the committed `registries/*.md`, git-ignore the views dir, and drop `merge=union` for the moved
  registries. Read rows through `warscape.registry` (`load_all`, `Registry.rows`), never by opening the file, so a reader follows
  either storage. The file-name rule is `id_to_file` (percent-encoding; docstring in `warscape/registry.py`).

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
failed_results = "raw/**/*.json"   # optional, off when empty: a glob inside each run folder a report cites (any `runs/<name>` path in its text); a JSON with top-level status "failed" must be named (path or file name) in that report's `## Deviations`
[jobs.text]                        # every repo-specific string in the step texts: commands ({wsc}), doc paths, decision references
[policy]
decisions = "docs/DECISIONS.md"    # append-only rows | <prefix><n> | YYYY-MM-DD | who | decision | yes/no |
decision_prefix = "D"
bootstrap = []                     # exact branch names exempt from the branch-kind rules: only the one pull request that introduces the pipeline
session_trailer = "Claude-Session" # who wrote the report may not write the review; "" switches the rule off
plan = [...]                       # globs a plan/* branch may touch, by path segment (* in one folder, ** across); meta = [...] for meta/*
[ci]
inputs = { ... }                   # set name -> regex: the paths that make that slow job run (`wsc ci inputs`)
workflows = ["gates.yml", "policy.yml"]   # rendered from ci/<name>.in by `wsc ci render`; the `ci_render` gate fails on a difference
required_checks = ["gates", "policy"]  # what main must require (`wsc ci check-settings`); [] = every workflow job but changes and notify (0.22.0)
```
- **Committed views and the job queue do not mix (C19).** A `brief/<id>` branch may change only `<jobs dir>/<id>/brief.md` and its row, but a committed
  `registries/jobs.md` changes with every `reg set` (so `policy` refuses the branch), and the `registries` gate refuses a stale one (so `gates` fails the
  branch if the view is left alone): no brief can pass both. A repo with a jobs registry sets `[views] commit = false` and does not list a view in `[policy]
  plan`/`meta`. `wsc jobs check` and the `jobs` gate refuse the combination (`[views] commit = true` with a `jobs` registry, C19) and say what to change, and `policy` marks a committed registry view in its brief-branch refusal.
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
  changed, merge_base, `base` and `head` (shas), `base_ref` and `repo` (the clone: run git there). Read the head as data with `from warscape.policy import show`,
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
  4. Tests that load the file by path or call the old names: `tests/test_jobs_hooks.py` (module path, the three source-text reads, the renamed functions),
     `tests/test_build_id.py`, `tests/test_registry_merge.py`, `tests/test_repo_rules.py` (`MOVED_ALLOWED` key and the loader), `tests/test_usage_reader.py`
     (`sys.path` gains `tools/gates`, `import pipeline as hk`), `tests/test_proxy_host.py`.
  5. Living docs: `git grep -n "jobs_hooks\|hook module\|policy_problems"` outside dated job folders (`CLAUDE.md`, `docs/REVIEW.md`, `harness/README.md`,
     `docs/plans/PLAN.md`, the `wsc.toml` comments).
  6. Run `python3 core/wsc.py gates`, `jobs check` and `policy --branch <the pin-bump branch>`: the `jobs check` line and the page's PC block read as before.

## Moving to base-judged policy (0.26.0, core W23, C24)
In the pin-bump commit itself, because the render guard and the new facts fail otherwise (napoleon: J78):
1. **`ci/policy.yml.in`:** `on: pull_request_target` with the same types. For the bump's own pull request add a second trigger, `pull_request` with
   the same types and `paths: ['jobs/<bump id>/report.md']` (main's copy has no `pull_request_target` yet, so without it nothing would run `policy`
   on that pull request); remove it in the next change to the template (`ci_render` warns until then). Run `wsc ci render`.
2. **`[ci] policy_extra_steps`** now run in the base checkout, where `HEAD` is the base. Take the head's sha from an `env:` value
   (`${{ github.event.pull_request.head.sha }}`), never from an expression inside `run:`, and make both pins present in `core/` if a module compares them.
3. **The `policy`-stage module** (napoleon `tools/gates/pipeline.py`): run git at `ctx.facts['repo']` with the `head`, `base` and `merge_base` shas
   (`show`, `show_first`, `core_pin_diff`, `collect_acceptance`), never in `ctx.root` and never with `'HEAD'`; a module left as it is fails closed, as a
   crash. `ctx.root/core/...` is now the base's core: a build id must come from the base's `build_id.py` over the head's blobs, never by running the
   head's copy. When a bump changes `build_id.py` itself, the base's algorithm cannot reproduce the head's id: the game needs a rule for that, and the
   default is a refusal.
4. **Behaviour.** CI judges the pull request's head against the base tip, so a branch behind `main` on the decisions file must merge `main`. Globs
   match by path segment: `registries/*` no longer covers `registries/<name>/<row>.json`. Until the bump merges, the game's pull requests are judged
   as before, with the note.

## The proxy, the harness and the save tools (0.4.0)
From 0.4.0 the core carries the proxy DLL's core (`proxy/src`), its host tests and tools (`proxy/tests`, `proxy/tools`), the PC
watcher kit (`harness/`) and the ESF save tools (`saves/`). A game keeps its adapters: `proxy/<game>/` (adapter.cpp, identity.json,
the generated tables and config file, lua/) and `harness/<game>/` (adapter.json, profiles/), plus its registries. The tools find
them through `proxy/tools/layout.py`: the game root is the superproject that pins the core (or `$WSP_GAME_ROOT`), and the adapters
are `wsc.toml` `[proxy] adapter` / `[harness] adapter` when set, else the one `proxy/*/adapter.cpp` / `harness/*/adapter.json`.
Run them from the game repo as `core/proxy/tools/build.sh`, `core/harness/job.sh` and so on; `python3 core/proxy/tools/layout.py`
prints what they will use. The DLL build id hashes the inputs' content under role names, read through the gitlink for files in
the core, so moving them here kept every game build id (napoleon J12); the build contract (the roles, the toolchain pin and its check, tracked
sources only, the DLL's `self_hash` log line, the CI step summary) is [PROXY_BUILD.md](PROXY_BUILD.md). The core's CI builds and tests them against the null game
(`proxy/tests/null_game/README.md`); from 0.19.0 the tools' Python host tests run here too (`tests/test_pc_deploy.py`, `test_ctl.py`,
`test_acceptance.py`, `test_saves.py`, `test_job_sh.py`; W8), so a game keeps only the tests over its own data (its scenario rows and
battle presets for rule 78, its save map, recipes and staging, its real identity).
The Git Bash finder is core code from 0.19.0 (`warscape/gitbash.py`: `harness/ctl.py` no longer loads the game's `tools/verbs/setup.py`): a
game's setup verb imports it (`from warscape.gitbash import git_bash, bash_kind, bash_for_tests`; verbs run with the core on `sys.path`)
instead of keeping its own, and a host test that runs a shell script takes its bash from `bash_or_skip(self)` (a skip, or a failure under
`$WSC_REQUIRE_BASH`).
A pending virtual-display restore (`vdisplay_restore.json`) whose saved position can no longer apply restores the saved mode at the display's current origin
(watcher 1.3.0, 0.14.0, W5); a missing virtual display drops the record to `_to_deletedisplay_restore_<utc>.json.dropped` (D38 of the first consumer).

**The UI pin file** (`[proxy] ui_pins`, else `viewer/pins.json`; the `ui_pins` input) needs `rmlui`, `freetype`, `lua`, `stb_image` and
`stb_image_write` (the PNG dump, since 0.10.0); copy a missing entry from the null game's `proxy/tests/null_game/viewer/pins.json`.

Proxy features a game turns on through its adapter and its config_keys rows each have one contract doc: the RmlUi host
([PROXY_UI.md](PROXY_UI.md)), battle unit orders ([PROXY_ORDERS.md](PROXY_ORDERS.md)) and, from 0.13.0, the gesture layer
([PROXY_GESTURES.md](PROXY_GESTURES.md): a `GestureAdapter` in `GameAdapter::gesture`, the `controls.gestures` key, the ctl `gesture` verb;
`GameAdapter` gained that member, so an adapter's aggregate initialiser needs one more entry, `nullptr` for none).
The frame capture (`dev.capture`, the ctl `capture` verb, the `frame.txt` record lines) is [PROXY_CAPTURE.md](PROXY_CAPTURE.md): from 0.21.0 it hooks
37 device slots and 2 state-block slots, fails an abandoned or empty capture with a `state`, records only the thread that took the arm, and writes
`SBCREATE`, `SBCAPTURE`, `SBAPPLY` (with a `STATE` readback), `OTHERTHREAD` and `ABANDONED` lines; a game's own capture docs point there.
Engine sites and their config keys ([PROXY_SITES.md](PROXY_SITES.md)): from 0.16.0 a `patch` row may take its value from a numeric key
(`value_key`, `value_scale`, `value_floor_stock`) and a key may carry `type`, `min` and `max`. Nothing changes for existing rows (their
generated tables are byte-identical); after the pin bump run `python3 core/proxy/tools/gen_tables.py --check`.
The dev control channel ([PROXY_CTL.md](PROXY_CTL.md)): from 0.18.0 a request written before the game process started is refused as
`stale` (job.sh exit 2: resend it), never run; the read-only `peek <site>[+|-<off>] [*[+|-<off>] ...] <len>` reads from an accepted engine site.

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
- **Re-run steps:** `python3 core/wsc.py discovery all` on the PC, then `discovery check` and `git diff --stat` (empty when nothing changed in the game); `discovery check` and
  `discovery gate` need only committed files and belong in the game's thin real-repo test.

# Consuming the core from a game repo

How a game repo (napoleon-remastered first) uses warscape-core at a pinned version. **Proposal, 2026-10-28: nothing is wired into
a game repo until Liam approves.**

## Recommendation: a git submodule at `core/`, pinned to a release tag

The game repo carries the core as a submodule at `core/`, checked out at a tag (`v0.1.0`), and repeats the tag in its `wsc.toml`
(`[core] version = "v0.1.0"`). Commands run from the game repo root as `python3 core/wsc.py <verb>`.

Why this one: it is the only option where "a game repo never patches the core in place" (napoleon `PLAN.md` section 4) holds by
construction. An edit inside `core/` cannot be committed to the game repo; it can only be pushed to warscape-core, through a PR.
The `core_pin` gate adds the rest: it fails when the checkout is not the pinned version or has local changes.

## The options compared

| | Submodule at `core/`, tag-pinned (recommended) | Subtree (`git subtree add --squash`) | Vendored copy + `VERSION` | `pip install` from a git tag |
|---|---|---|---|---|
| The pin | the gitlink sha in the diff, plus `[core] version` | a squash commit message | the `VERSION` file | a requirements line |
| In-place patching | impossible to commit; `core_pin` fails on a dirty checkout | easy and silent; would need a tree-hash gate against the tag (network) | same as subtree | not possible, but edits in site-packages are invisible |
| CI on a private core | needs a read token secret (below; not while the core is public) | no auth | no auth | a token **and** an install step (breaks "no installs") |
| Fresh clone | `git clone --recurse-submodules`; forgetting it fails loudly (hook and CI say "core missing") | plain clone | plain clone | plain clone + pip |
| Agent sessions | attach both repos; `git submodule update --init` | nothing extra | nothing extra | pip through the proxy |
| Upgrade | three commands (below), one reviewable diff | `git subtree pull --squash` (merge noise) | copy and commit (large diff) | bump one line |
| History cost | none | the core duplicated in game history | same | none |

Costs of the recommendation, and what covers them:
- **CI token.** Only while the core is private (it is public since at least 2026-10-29, so checkout needs no token): the default
  `GITHUB_TOKEN` of a game repo cannot read another private repo. Liam creates a fine-grained personal
  access token with **Contents: read** on `warscape-core` (and the game repo), stored as the secret `WARSCAPE_CORE_TOKEN` in each game
  repo. A deploy key on warscape-core is the alternative (read-only, one per game repo).
- **Clone discipline.** The submodule URL is relative (`../warscape-core.git`), so it follows whatever remote the game repo was cloned
  from: HTTPS through the agent proxy, HTTPS or SSH on Liam's PC. The pre-push hook refuses with "git submodule update --init" when
  `core/` is empty.
- **Agent sessions** attach `liam-rowley/warscape-core` (read) next to the game repo; one extra `add_repo`.

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
[jobs.text]                        # every repo-specific string in the step texts: commands ({wsc}), doc paths, decision references
[policy]
decisions = "docs/DECISIONS.md"    # append-only rows | <prefix><n> | YYYY-MM-DD | who | decision | yes/no |
decision_prefix = "D"
bootstrap = []                     # exact branch names exempt from the branch-kind rules: only the one pull request that introduces the pipeline
session_trailer = "Claude-Session" # who wrote the report may not write the review; "" switches the rule off
plan = [...]                       # globs a plan/* branch may touch; meta = [...] for a meta/* branch
[ci]
inputs = { ... }                   # set name -> regex: the paths that make that slow job run (`wsc ci inputs`)
workflows = ["gates.yml", "policy.yml"]   # rendered from ci/<name>.in by `wsc ci render`; the `ci_render` gate fails on a difference
```
- **Committed views and the job queue do not mix (C19).** A `brief/<id>` branch may change only `<jobs dir>/<id>/brief.md` and its row, but a committed
  `registries/jobs.md` changes with every `reg set` (so `policy` refuses the branch), and the `registries` gate refuses a stale one (so `gates` fails the
  branch if the view is left alone): no brief can pass both. A repo with a jobs registry sets `[views] commit = false` and does not list a view in `[policy]
  plan`/`meta`. Nothing refuses the combination yet (B49), so a repo would find out at its first brief.
- **A game's own rules** are gate modules with the `jobs`, `policy` and `view` stages ("Game gates", below; `[jobs] hooks` is gone since 0.20.0).
- **Workflows are rendered, not called.** A reusable `workflow_call` workflow would rename the checks (`<caller job> / <called job>`), and branch protection
  waits for exact names. `ci/<name>.in` is the workflow with placeholder lines (`{{wsc changes}}`, `{{wsc if <set>}}`, `{{wsc pass_marker <set>}}`,
  `{{wsc policy}}`, `{{wsc notify ...}}`: `warscape/ci_render.py`); the slow jobs stay in the template. After a change: `wsc ci render`, commit both files.
- **Settings only the owner can make** (this changes no repository setting): require the checks `gates` (and `proxy`, `harness-windows` or whatever slow
  jobs the repo has) and `policy` on `main`, allow auto-merge, and set `WARSCAPE_CORE_TOKEN` (or the `[ci] token_secret` name) only if the core is private.
  Until required checks exist, `gh pr merge --auto` has nothing to wait for and merges at once.
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
  Result's details are queue problems, a `warn` Result's print, a non-empty summary goes on the `jobs check` line. `policy`: `wsc policy` only, with `ctx.facts`
  (branch, kind, jid, changed, the merge base; the module runs from the branch's own head); an `error` Result's details are policy errors. `view`: `wsc jobs view`,
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

## The proxy, the harness and the save tools (0.4.0)
From 0.4.0 the core carries the proxy DLL's core (`proxy/src`), its host tests and tools (`proxy/tests`, `proxy/tools`), the PC
watcher kit (`harness/`) and the ESF save tools (`saves/`). A game keeps its adapters: `proxy/<game>/` (adapter.cpp, identity.json,
the generated tables and config file, lua/) and `harness/<game>/` (adapter.json, profiles/), plus its registries. The tools find
them through `proxy/tools/layout.py`: the game root is the superproject that pins the core (or `$WSP_GAME_ROOT`), and the adapters
are `wsc.toml` `[proxy] adapter` / `[harness] adapter` when set, else the one `proxy/*/adapter.cpp` / `harness/*/adapter.json`.
Run them from the game repo as `core/proxy/tools/build.sh`, `core/harness/job.sh` and so on; `python3 core/proxy/tools/layout.py`
prints what they will use. The DLL build id hashes the inputs' content under role names, read through the gitlink for files in
the core, so moving them here kept every game build id (napoleon J12). The core's CI builds and tests them against the null game
(`proxy/tests/null_game/README.md`).
A pending virtual-display restore (`vdisplay_restore.json`) whose saved position can no longer apply restores the saved mode at the display's current origin
(watcher 1.3.0, 0.14.0, W5); a missing virtual display drops the record to `_to_deletedisplay_restore_<utc>.json.dropped` (D38 of the first consumer).

Proxy features a game turns on through its adapter and its config_keys rows each have one contract doc: the RmlUi host
([PROXY_UI.md](PROXY_UI.md)), battle unit orders ([PROXY_ORDERS.md](PROXY_ORDERS.md)) and, from 0.13.0, the gesture layer
([PROXY_GESTURES.md](PROXY_GESTURES.md): a `GestureAdapter` in `GameAdapter::gesture`, the `controls.gestures` key, the ctl `gesture` verb;
`GameAdapter` gained that member, so an adapter's aggregate initialiser needs one more entry, `nullptr` for none).
Engine sites and their config keys ([PROXY_SITES.md](PROXY_SITES.md)): from 0.16.0 a `patch` row may take its value from a numeric key
(`value_key`, `value_scale`, `value_floor_stock`) and a key may carry `type`, `min` and `max`. Nothing changes for existing rows (their
generated tables are byte-identical); after the pin bump run `python3 core/proxy/tools/gen_tables.py --check`.

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

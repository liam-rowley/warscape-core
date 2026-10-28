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
| CI on a private core | needs a read token secret (below) | no auth | no auth | a token **and** an install step (breaks "no installs") |
| Fresh clone | `git clone --recurse-submodules`; forgetting it fails loudly (hook and CI say "core missing") | plain clone | plain clone | plain clone + pip |
| Agent sessions | attach both repos; `git submodule update --init` | nothing extra | nothing extra | pip through the proxy |
| Upgrade | three commands (below), one reviewable diff | `git subtree pull --squash` (merge noise) | copy and commit (large diff) | bump one line |
| History cost | none | the core duplicated in game history | same | none |

Costs of the recommendation, and what covers them:
- **CI token.** The default `GITHUB_TOKEN` of a game repo cannot read another private repo. Liam creates a fine-grained personal
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

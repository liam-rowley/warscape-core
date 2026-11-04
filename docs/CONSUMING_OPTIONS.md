# Consuming the core: the options compared

Why a game repo takes the core as a git submodule at `core/`, pinned to a release tag. Moved out of [CONSUMING.md](CONSUMING.md) on 2026-11-04 to keep that doc under the 30 KB cap; the recommendation itself is in CONSUMING.md "Recommendation".

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

## Registry storage and views (0.6.0, opt-in)
Moved here from [CONSUMING.md](CONSUMING.md) on 2026-11-04 (W28, the 30 KB cap).

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

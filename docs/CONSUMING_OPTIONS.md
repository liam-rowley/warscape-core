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
- **Removing a row (W15):** `python3 core/wsc.py reg remove <reg> <id>...` replaces `git rm registries/<name>/<file>.json`. It refuses, writing
  nothing, while an `x-ref` field, a tool's `superseded:<id>`, a tool file still in the repo or a `jobs/<id>/` folder points at a row, or when
  the removal adds a check problem; rows that only point at each other go in one call.

## Decisions as one file per row (core W43, opt-in)

`[policy] decisions` stays a Markdown path until a repo changes it, and the Markdown rule is unchanged. A table every branch appends to, with a next number each branch picks,
collides on every parallel branch; one file per row with a drawn id does not.
```toml
[registries]
decisions = "core:decisions"
[storage]
dir = ["jobs", "decisions"]
[policy]
decisions = "registry:decisions"             # a row file on the base never changes, moves or goes
decisions_retired = "docs/DECISIONS.md"      # between the two pull requests below
plan = [..., "registries/decisions/*"]       # and in meta, or a plan/ branch cannot add a row
```
- **Ids:** old rows keep their numbers. A new id is `<decision_prefix><yymmdd>-<4 hex>` from `wsc reg add decisions --mint who=... decision=... reversible=yes|no`; `policy` refuses a new number. A reversal is a new row whose `replaces` names the old one.
- **Moving takes two pull requests,** because a pull request is judged with its base's rules, and those refuse a head without the Markdown rows. First, after the pin bump: `wsc reg migrate decisions --from-md docs/DECISIONS.md`, `--check` the same way, the keys above, every row line of the file left as it is (its prose may change). While `decisions_retired` is set and the file exists, `policy` refuses a head that changes the file's table, on every branch and with the base's rules, so a branch cut before the key cannot land a row; the `registries` gate also fails on a row the row files lack. Second: a `meta/` branch deletes the file and the key.
- **`later` rows:** a job status for work recorded but not started. `jobs next`, `jobs review` and the autopilot ignore it, `jobs view` shows it, and status `needs_brief` promotes it. Pick them up batched by `area`, not one job each. `wsc jobs later --from-md FILE [--area NAME] [--check]` moves a `| # | Change | Why | Raised |` table into such rows, the old number in `backlog_id`, which `wsc find` resolves.

## The `tests` gate (core W139)

`[tests]` in `wsc.toml`. `wsc gates` and CI read the same keys, so a local run behaves as CI does.

| Key | Default | What it does |
| --- | --- | --- |
| `dirs` | `["tests"]` | The test folders, one after the other. |
| `timeout_s` | `600` | One deadline per folder, across all workers. Keep it under the CI job's own limit. |
| `workers` | `1` | Modules run at once. `1` is one process for the folder. Above 1, a queue of modules, each in its own `python -m unittest discover -p <module>.py`. |
| `first` | `[]` | Module names to start first, the long ones; the rest follow by name. A stale name is ignored. Read only above 1 worker. |
| `warn_at` | `0.75` | The gate warns when a folder took more than this share of `timeout_s`, never fails. `0` is off. |

Every run logs `timing: workers <n>, cpu_count <n>` and each folder's ten slowest modules. At `workers = 1` those seconds are summed test time, without imports or `setUpClass`; above 1 they are each process's wall time, so the two are not comparable.

Above 1 worker:
- The total is the sum of each module's own `Ran N tests` line. A module with no such line is an error, even at exit 0, and so is a module with no tests in it, which one process would pass over.
- At the deadline every running module is killed with its process tree, and the gate names what had not finished and what never started.
- Modules share the machine, so tests may not share anything fixed: a fixed path in the temp folder (`tests/test_acceptance.py` has one) is safe only while one module owns it, and a port or lock file the same.
- To opt in, read the timings of a green run, put its slowest modules in `first`, keep `workers` at or under the runner's `cpu_count`, and run the suite a few times: a collision shows up as a flake.

## What `--auto` starts (W46)

`wsc jobs view --serve --auto` starts reviews and fixes. A repo opts in to builds and briefs in `[jobs]`; a button and `jobs next` read none of these keys, as a person is looking.

| Key | Default | Meaning |
|---|---|---|
| `auto_actions` | `["review", "fix"]` | What a tick starts, any of `fix`, `review`, `build`, `brief`. `build` and `brief` need `max_sessions` (C41): the loader refuses them without it. |
| `auto_hold_phases` | `[]` | Phases never started, in any action. The phase is the main row's. One log line per id and reason. |
| `auto_phase_order` | `[]` | Inside one action, these phases first in this order, then the rest by (phase, number). |
| `auto_stop_finished` | `false` | At a full cap with a job waiting, the tick stops `done` rows that still hold a process, once, and uses the slots. Each stop is a log line; a dry run only logs. |

Each tick goes through fixes, reviews, builds, then briefs, so a finished job never waits behind a new one. The cap goes to the first in that order. A build or a brief:
- is read from `origin/main`, fetched each tick, never from the working tree; if that fails the tick starts neither, and goes on with fixes and reviews.
- waits while main's CI is red or unknown, which fixes and reviews do not: the fix for a red main may be one of them.
- is started once per pair of main's sha and the row's content. A session that ended without claiming is started again only when one of them moves, or by a restarted server.
- claims nothing from the tick: the session's first command, `jobs next --id`, claims its branch, and a person who takes the job first wins the push.

A build also obeys the `needs_pc` rules (one holder, `pc_state`, the acceptance lock), and waits while its brief has a question tagged `taste`, `risk` or `legal` under `## Open questions`, until the tag goes or a button starts it.
A brief obeys neither: writing about a `needs_pc` row needs no PC, so a `<id>-brief` session does not hold it. A `later`, `blocked` or `done` row is never started.

A `failed` or `stopped` row with a process counts against the cap and nothing stops it: a full cap names those rows in its log line and on the page. Stop them by hand with `claude stop <id>`.

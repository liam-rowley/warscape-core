# warscape-core

The shared core for the Total War remasters (Napoleon first; Empire moves onto it later, at a quiet time). It holds the
game-agnostic machinery; each game repo holds an **adapter** (its registry contents, paths, identity pins, screens) and pins
a released core version. A game repo never patches the core in place: it files the change here, and picks it up with a new tag.

Public (checked 2026-10-29 with the GitHub API). Python 3.12+, standard library only, so CI and a fresh clone need no installs.

## Core and adapter

What the core holds, split as in `napoleon-remastered` `docs/plans/PLAN.md` section 4 (state as of 0.9.0, 2026-11-02).

| Core (here) | Adapter (game repo) | State |
|---|---|---|
| Registry framework, CLI (`wsc`), gates, CI workflow, pre-push hook | registry contents, extra verbs, own schemas, own gates (**v0.20**, C22) | **v0.1** |
| Watcher, game lock, config profiles, headless display kit, sha-checked PC sync (`harness/`, `proxy/tools/pc_deploy.py`) | paths, launch arguments | **v0.4** (C14) |
| Proxy DLL skeleton: backend loading, log, crash capture, exe-identity guard, runtime patch engine, dev control channel, campaign console, battle camera (`proxy/src`) | identity pin, engine sites, scene detection, console and camera adapters | **v0.4** (C14) |
| Control API (`harness/ctl.py`: scene, cam, shot, perf, state, reset, pause, speed; `order` with napoleon J28) and contact sheets | scenario list, camera poses, openers | ctl **v0.4**; contact sheets later |
| Pack reader (`proxy/src/pack.h`, `proxy/tools/pack_list.py`), asset indexer, contact-sheet builder, texture upscaling pipeline | pack quirks, roles | pack reader **v0.4**; the rest later (napoleon J63, J64) |
| Job pipeline: the `jobs` verbs, pull-request policy, CI notifier and workflow templates | rows, branch kinds, decision numbering | **v0.9** (C18, napoleon J62); the core runs its own queue |
| RmlUi host, component library machinery, design tokens to RCSS, review viewer, fixture capture | design language, screens, data contracts | later (napoleon J30, J35, J63) |
| Frame-time and memory capture (`ctl perf`, `dev.capture`), A/B and regression diff | budgets, scenes | perf **v0.4**, capture **v0.7**; A/B diff later |
| ESF save tools (`saves/`) | record paths, recipes | **v0.4** (C14) |
| Discovery passes (`discovery/`, `wsc discovery`): pack, asset, db, loc, UI atlas, exe and Lua API readers and the discovery gate | `games.json` and the rules the tools read, every committed result | **v0.12** (C20, napoleon J64) |

## Use it

```sh
python3 wsc.py --help                      # verbs: reg, find, gates, jobs, policy, ci, discovery (+ a repo's own verbs)
python3 wsc.py find shadow resolution      # one search across every registry
python3 wsc.py reg add tools path/to/tool.py
python3 wsc.py reg set engine_facts some.fact state=verified date=2026-10-28 evidence=runs/20261028_a
python3 wsc.py gates --fast                # what the pre-push hook runs; `gates` alone adds the host tests (CI)
git config core.hooksPath .githooks        # once per clone
```
In a game repo the core sits at `core/` and the commands are `python3 core/wsc.py ...` from the game repo root (`docs/CONSUMING.md`).

## Registries

Each registry is its rows (one JSONL file, or one file per row: `[storage] dir`), a JSON Schema, a generated Markdown view
(committed, or written to a git-ignored folder: `[views] commit`) and a check, all behind `wsc reg` (`docs/CONSUMING.md`).
The core's own views are not committed (C19): `python3 wsc.py reg render` writes them to `_scratch/registries/`.
A repo declares its registries in `wsc.toml`; the core ships these schemas (`schemas/`):

| Registry | Holds |
|---|---|
| `tools` | every tool: a `wsc` verb, or a script whose header says why it is not one; rows come from file headers |
| `scenarios` | the battle, siege, naval and campaign library with pinned sky and weather, camera poses by id, launch recipe, load time |
| `assets` | pack, path, format, hash, role, used by, upscale state |
| `ui_elements` | screen, vanilla source, data contract, interactions, pipeline status |
| `engine_sites` | RVA, anchor and stock bytes, patch or hook, config key, `verified` (date, run) |
| `config_keys` | default, release value, owner, what it does |
| `hotkeys` | binding, action, context, source, how a bare key fires (`fires_with`); clashes fail the gate |
| `engine_facts` | claim, state (`verified`, `open`, `refuted`), evidence run, date |

`schemas/ui_pins.schema.json` is not a registry: it is the UI pin file's schema (`proxy/tools/fetch_ui.py --check`, [docs/PROXY_HARNESS.md](docs/PROXY_HARNESS.md)).

The schema subset and the registry extensions (`x-view`, `x-unique`, `x-wildcard`, `x-chord`, `x-ref`, `x-source`, `x-extends`) are
documented in the docstrings of `warscape/schema.py` and `warscape/registry.py`; the tool header format in `warscape/tools.py`.
Two of them in a sentence each: `x-chord` makes the `x-unique` check read a field as `Ctrl+Alt+Shift+Key` chords, so a bare key flagged
to fire with any modifier (or alone or with Shift) clashes with the chords it fires for (`hotkeys`: vanilla `Space` with
`fires_with: any_modifier` takes a mod `Alt+Space`). `x-extends: "core:<name>"` lets a game schema add fields to a core schema,
merged at load; canonical key order is then the core's fields first, then the game's (`docs/CONSUMING.md`, "Extending a core schema").

## Gates

`wsc gates` runs, deterministically and without network: `schemas`, `registries`, `tools` (header and row for every tool), `json`
(strict JSON and JSONL: no NaN or Infinity, no key twice in one object; the registry loader, `jobq` and `gen_tables.py` read repo data the same way, W28),
`windows_paths`, `doc_size` (living docs over `[docs] max_kb`, default 30 KB; dated records exempt),
`verified_dates` (a "verified" with no date or run id: only an ISO date, a compact `20YYMMDD` run id or a `reports/`, `runs/` or `records/` path dates it, W28),
`doc_paths` (a backticked repo path in a living doc that is not a tracked file or folder, from the root, the doc's folder or across `core/`; job folders,
the decisions file, fenced blocks, `(was <path>)` and `(moved)` lines, `../` paths and `[docs] path_ignore` are not checked), `conflict_markers`, `eol` (warning), `core_pin` (the core checkout is
unmodified, its `VERSION` is the pinned `vX.Y.Z`, and HEAD is that tag whenever the tag is in the checkout; a shallow checkout without
it is compared by `VERSION` only, C21; in the core, tags match `VERSION`), `hooks` (warning: the pre-push hook is wired in this clone), `jobs`, `ci_render`, `run_refs` (every repo path a run README names exists; `[gates] run_refs_since` grandfathers old runs) and `tests`
(host tests; the full set only). CI (`.github/workflows/gates.yml`) runs the full set on Linux and Windows on every push and PR.
`[gates] skip` entries are `"<gate>:<decision id>"`: the id must be a row of the `[policy] decisions` file, each skipped gate prints `skipped <gate>: <id>`
as a warning, and `--only <gate>` still runs it (W28). A rule inside a skippable gate (a game's host test inside `tests`) needs its own decision.
A game adds its own checks as gate modules (`wsc.toml` `[gates] dirs`, `NAME` and `run(ctx) -> Result`: `docs/CONSUMING.md` "Game gates"), each its own line
after the core gates or a rule of `wsc jobs check`, `wsc policy` or the `jobs view` page.

## Layout

| Path | What |
|---|---|
| `CLAUDE.md` | rules for every chat and agent working here |
| `docs/DECISIONS.md` | core decisions, dated, append only |
| `docs/CONSUMING.md` | how a game repo pins and uses the core |
| `docs/BACKLOG.md` | agreed core changes not yet built |
| `docs/PROXY_ORDERS.md` | the proxy's battle unit orders (`dev.orders`): entry points, Lua, `ctl.py order`, the adapter |
| `docs/PROXY_SITES.md` | engine sites: the byte layout, the all-or-nothing checks, boolean keys, value rows from numeric keys, the generator's refusals |
| `wsc.py`, `warscape/` | the CLI launcher and the library; verbs in `warscape/verbs/` |
| `schemas/` | the registry schemas the core ships |
| `registries/` | the core's own registries (real: `tools`; the rest declared empty so CI exercises every schema) |
| `tests/` | host tests (stdlib `unittest`), run by the `tests` gate (a skipped test is a `warn` naming it and its reason) |
| `wsc.toml` | this repo's declaration to the CLI |

# warscape-core

The shared core for the Total War remasters (Napoleon first; Empire moves onto it later, at a quiet time). It holds the
game-agnostic machinery; each game repo holds an **adapter** (its registry contents, paths, identity pins, screens) and pins
a released core version. A game repo never patches the core in place: it files the change here, and picks it up with a new tag.

Public (checked 2026-10-29 with the GitHub API). Python 3.12+, standard library only, so CI and a fresh clone need no installs.

## Core and adapter

What the core will hold, split as in `napoleon-remastered` `docs/plans/PLAN.md` section 4. **v0.1 is the first row only.**

| Core (here) | Adapter (game repo) | State |
|---|---|---|
| Registry framework, CLI (`wsc`), gates, CI workflow, pre-push hook | registry contents, extra verbs, own schemas | **v0.1** |
| Watcher, game lock, config profiles, headless display kit, sha-checked PC sync | paths, launch arguments | later |
| Proxy DLL skeleton: backend loading, log, crash capture, exe-identity guard, runtime patch engine, dev control channel | identity pin, engine sites, scene detection | later |
| Control API (scene, camera, shot, order, pause, speed) and contact sheets | scenario list, camera poses, openers | later |
| Pack reader, asset indexer, contact-sheet builder, texture upscaling pipeline | pack quirks, roles | later |
| RmlUi host, component library machinery, design tokens to RCSS, review viewer, fixture capture | design language, screens, data contracts | later |
| Frame-time and memory capture, A/B and regression diff | budgets, scenes | later |

## Use it

```sh
python3 wsc.py --help                      # verbs: reg, find, gates (+ a repo's own verbs)
python3 wsc.py find shadow resolution      # one search across every registry
python3 wsc.py reg add tools path/to/tool.py
python3 wsc.py reg set engine_facts some.fact state=verified date=2026-10-28 evidence=runs/20261028_a
python3 wsc.py gates --fast                # what the pre-push hook runs; `gates` alone adds the host tests (CI)
git config core.hooksPath .githooks        # once per clone
```
In a game repo the core sits at `core/` and the commands are `python3 core/wsc.py ...` from the game repo root (`docs/CONSUMING.md`).

## Registries

Each registry is a JSONL file (the source), a JSON Schema, a generated Markdown view and a check, all behind `wsc reg`.
A repo declares its registries in `wsc.toml`; the core ships these schemas (`schemas/`):

| Registry | Holds |
|---|---|
| `tools` | every tool: a `wsc` verb, or a script whose header says why it is not one; rows come from file headers |
| `scenarios` | the battle, siege, naval and campaign library with pinned sky and weather, camera poses by id, launch recipe, load time |
| `assets` | pack, path, format, hash, role, used by, upscale state |
| `ui_elements` | screen, vanilla source, data contract, interactions, pipeline status |
| `engine_sites` | RVA, anchor and stock bytes, patch or hook, config key, `verified` (date, run) |
| `config_keys` | default, release value, owner, what it does |
| `hotkeys` | binding, action, context, source; clashes fail the gate |
| `engine_facts` | claim, state (`verified`, `open`, `refuted`), evidence run, date |

The schema subset and the registry extensions (`x-view`, `x-unique`, `x-ref`, `x-source`) are documented in the docstrings of
`warscape/schema.py` and `warscape/registry.py`; the tool header format in `warscape/tools.py`.

## Gates

`wsc gates` runs, deterministically and without network: `schemas`, `registries`, `tools` (header and row for every tool), `json`
(strict JSON and JSONL), `windows_paths`, `doc_size` (living docs over `[docs] max_kb`, default 30 KB; dated records exempt),
`verified_dates` (a "verified" with no date or run id), `conflict_markers`, `eol` (warning), `core_pin` (the pin is a `vX.Y.Z` tag on
the core checkout; in the core, tags match `VERSION`), `hooks` (warning: the pre-push hook is wired in this clone) and `tests`
(host tests; the full set only). CI (`.github/workflows/gates.yml`) runs the full set on Linux and Windows on every push and PR.

## Layout

| Path | What |
|---|---|
| `CLAUDE.md` | rules for every chat and agent working here |
| `docs/DECISIONS.md` | core decisions, dated, append only |
| `docs/CONSUMING.md` | how a game repo pins and uses the core |
| `docs/BACKLOG.md` | agreed core changes not yet built |
| `wsc.py`, `warscape/` | the CLI launcher and the library; verbs in `warscape/verbs/` |
| `schemas/` | the registry schemas the core ships |
| `registries/` | the core's own registries (real: `tools`; the rest declared empty so CI exercises every schema) |
| `tests/` | host tests (stdlib `unittest`), run by the `tests` gate |
| `wsc.toml` | this repo's declaration to the CLI |

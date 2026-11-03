# Discovery

The discovery passes of the Total War remasters, moved here from a game repo's `discovery/core/` (that repo's job J64, core job W4, 0.12.0, C20). They read a
game's packs and exe in place (read only) and write deterministic results into the game repo's `discovery/<area>/` folders. The core holds the
tools; a game repo holds the adapter folder, every committed result and the registries.

## Where things moved

Old paths are the game repo's; the tools-registry ids kept their `discovery.core.` prefix (briefs cite them).

| Old path | Core path | Tools id |
|---|---|---|
| `discovery/core/api_inventory.py` | `discovery/api_inventory.py` | `discovery.core.api_inventory` |
| `discovery/core/assets.py` | `discovery/assets.py` | `discovery.core.assets` |
| `discovery/core/briefpaths.py` | `discovery/briefpaths.py` | `discovery.core.briefpaths` |
| `discovery/core/console_cmds.py` | `discovery/console_cmds.py` | `discovery.core.console_cmds` |
| `discovery/core/cuf.py` | `discovery/cuf.py` | `discovery.core.cuf` |
| `discovery/core/db.py` | `discovery/db.py` | `discovery.core.db` |
| `discovery/core/diffout.py` | `discovery/diffout.py` | `discovery.core.diffout` |
| `discovery/core/engine_api.py` | `discovery/engine_api.py` | `discovery.core.engine_api` |
| `discovery/core/exe.py` | `discovery/exe.py` | `discovery.core.exe` |
| `discovery/core/exe_strings.py` | `discovery/exe_strings.py` | `discovery.core.exe_strings` |
| `discovery/core/extracted.py` | `discovery/extracted.py` | `discovery.core.extracted` |
| `discovery/core/fonts.py` | `discovery/fonts.py` | `discovery.core.fonts` |
| `discovery/core/gate.py` | `discovery/gate.py` | `discovery.core.gate` |
| `discovery/core/imagehdr.py` | `discovery/imagehdr.py` | `discovery.core.imagehdr` |
| `discovery/core/layouts.py` | `discovery/layouts.py` | `discovery.core.layouts` |
| `discovery/core/loc.py` | `discovery/loc.py` | `discovery.core.loc` |
| `discovery/core/lua_api.py` | `discovery/lua_api.py` | `discovery.core.lua_api` |
| `discovery/core/luachunk.py` | `discovery/luachunk.py` | `discovery.core.luachunk` |
| `discovery/core/packfs.py` | `discovery/packfs.py` | `discovery.core.packfs` |
| `discovery/core/packs.py` | `discovery/packs.py` | `discovery.core.packs` |
| `discovery/core/re_env.py` | `discovery/re_env.py` | `discovery.core.re_env` |
| `discovery/core/ron2json.py` | `discovery/ron2json.py` | `discovery.core.ron2json` |
| `discovery/core/shader_catalog.py` | `discovery/shader_catalog.py` | `discovery.core.shader_catalog` |
| `discovery/core/shaders.py` | `discovery/shaders.py` | `discovery.core.shaders` |
| `discovery/core/sheets.py` | `discovery/sheets.py` | `discovery.core.sheets` |
| `discovery/core/tpl.py` | `discovery/tpl.py` | `discovery.core.tpl` |
| `discovery/core/tsvgz.py` | `discovery/tsvgz.py` | `discovery.core.tsvgz` |
| `discovery/core/ui_atlas.py` | `discovery/ui_atlas.py` | `discovery.core.ui_atlas` |
| `discovery/core/ui_walk.py` | `discovery/ui_walk.py` | `discovery.core.ui_walk` |
| `discovery/core/uic.py` | `discovery/uic.py` | `discovery.core.uic` |
| `discovery/core/x86re.py` | `discovery/x86re.py` | `discovery.core.x86re` |
| `discovery/requirements.txt` | `discovery/requirements.txt` | - |
| `proxy/tools/exe_info.py` | `proxy/tools/exe_info.py` | `proxy.tools.exe_info` |
| `tools/verbs/discovery.py` | `warscape/verbs/discovery.py` | `wsc.discovery` |
| (new: the path and name resolver) | `discovery/paths.py` | `discovery.paths` |
| `tests/test_discovery*.py`, `test_engine_api.py`, `test_exe_strings.py`, `test_x86re.py` | `discovery/tests/` (logic only, on a fixture adapter) | - |

## What a game provides (the adapter)

`wsc.toml` `[discovery] adapter = "<repo-relative folder>"`, else the one `discovery/*/games.json` in the game repo. The folder holds:
`games.json` (`"target"` and `"reference"` are the two games' names; each name is a key with `root`, `exe`, `data`, `pack_order`, `mod_packs`, and for the
reference `repo`; `"extract"`; optionally `captures` under the target), `carry_over.json`, `gate.json`, `asset_roles.json`, `db_schema.json`, `console.json`,
`engine_api.json`, `lua_cfuncs.json`, `probe_safe.json`, `exe_strings.tsv.gz`, `shader_catalog.json`, `frame_anatomy.md`, `shaders/`. No module finds the game
by its own place: `paths.py` takes the game root and the adapter from `proxy/tools/layout.py` (`discovery_adapter()`), and the names from `games.json`.
Result folders (`discovery/assets`, `db`, `loc`, `ui`, `diff`, `gate`) sit beside the adapter folder in the game repo; `--games` and `--out` still override.
Provenance strings written into results (`generator: discovery/core/...`) keep their old text so a re-run is byte for byte the same (backlog B53).

## Re-run (on the PC, read only; the game folders are never written)

`python3 core/wsc.py discovery all` (assets, db, loc, sheets, ui, then render), one pass with `discovery assets|db|loc|sheets|ui`, the diff areas
(`packs`, `layouts`, `fonts`, `lua_api`, `shaders`, `exe`) by running `core/discovery/<area>.py` after extracting with `proxy/tools/pack_list.py --extract`.
`discovery check` and `discovery gate` need only committed files. Optional extras (Pillow for `sheets`; capstone and pefile in the RE environment made by
`re_env.py`) are in `docs/CONSUMING.md`, "Discovery (optional extras)".

## Tests

`discovery/tests/` runs in the core's `tests` gate on Linux and Windows against `discovery/tests/null_adapter/` (two made-up games, `tgt` and `ref`); the
x86 test skips without capstone. Tests that read a game's real registries and committed results belong to the game repo.

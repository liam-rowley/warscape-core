# W14 report: Core schema extension and modifier-agnostic hotkeys

W14 adds `x-extends` (B2), so a game schema can add fields to a core schema, merged at load, without copying it. It also adds `fires_with` and the `x-chord` extension (B3), so a bare hotkey that fires with any modifier, or alone or with Shift, clashes with the chords it fires for (vanilla `Space` with `fires_with: any_modifier` now clashes with a mod `Alt+Space`). VERSION 0.17.0; branch `job/W14`.

## What exists
- **`warscape/registry.py` `load_schema(spec, root)`**: reads a schema and resolves `x-extends`, returning the merged document. `Registry.__init__` and `gates.py` `gate_schemas` both read through it, so the gate checks the merged document; `schema_path` is unchanged and no other reader of schema files exists (`grep -rn "schema_path\|schema.json" warscape`).
- **`x-extends` form (decision 2):**
  - only at the top level, and only `"core:<name>"`
  - an extending document may hold only `EXTENDS_KEYS`: `x-extends`, `$schema`, `$id`, `$comment`, `title`, `description`, `properties`, `required`, `allOf`, `$defs`, `x-view`, `x-unique`
  - these are load errors, each naming the key or the target:
    - any other key (`additionalProperties`, `type`, `x-wildcard`, `oneOf`, ...)
    - an `x-extends` below the top level; the walk follows schema positions only (SUBSCHEMA, SUBSCHEMA_MAP, SUBSCHEMA_LIST from `schema.py`)
    - a non-`core:` target, or a target that is not a string
    - a missing core schema
    - a core schema that itself extends
- **`x-extends` merge (decision 3):**
  - `properties`: the core's first, then the game's in the game's order; redefining a core property is an error that points to `allOf`.
  - `required`: the union, core order first.
  - `allOf` and `x-unique`: the core's entries, then the game's.
  - `$defs`: merged; a name clash is an error.
  - `x-view`, `title`, `description`, `$id`: the game's when given.
  - Everything else is the core's, so `additionalProperties: false` covers the merged set.
  - The merged document goes through `check_schema` in both callers.
  - Canonical key order follows the merged `properties` (decision 4). This is documented in the `registry.py` docstring, `README.md` "Registries" and a new `docs/CONSUMING.md` section "Extending a core schema" with a minimal example.
- **`schemas/hotkeys.schema.json`:**
  - `fires_with`: an optional enum, `any_modifier` or `shift`.
  - A new `allOf` `if: {required: [fires_with]}` / `then` rule: the binding must have no `+`. It applies to any `source` (open question 2).
  - `"x-chord": {"field": "binding", "flag": "fires_with"}`.
  - The description now says so.
- **`x-chord` in `Registry._check_unique`:**
  - It applies to every `x-unique` tuple that contains `field`. Two rows also clash on that field when one row's flag is `any_modifier`, its value is a bare key, and both last segments are equal. They also clash when the flag is `shift`, the keys are equal and the other row's modifiers are none or exactly `Shift`. All comparisons are case-insensitive.
  - The other fields of the tuple and `x-wildcard` apply as before.
  - The message gets a suffix naming the rule, e.g. `: Alt+Space reaches Space, which fires with any modifier` or `..., which fires alone or with Shift`. An exact match keeps today's message unchanged.
  - The meaning of the two flag values is defined once (`CHORD_FLAGS`), and documented in the docstring. There is no hotkeys-specific code in `registry.py`.
- **Docs:**
  - `README.md` "Registries": the hotkeys row and the two new extensions.
  - `docs/CONSUMING.md`: "Extending a core schema (0.17.0)".
  - `docs/BACKLOG.md`: B2 and B3 removed; B61 (context families) added.
  - `warscape/schema.py`: its docstring now lists the extensions.
- **VERSION** 0.17.0.

## Tests, red then green
- The red commit `67a4f36` adds `tests/test_extends.py` (15 cases) and 5 hotkey cases in `tests/test_registry.py`. In that commit the B3 cases fail on `unknown field 'fires_with'` and the B2 module fails on importing `load_schema`.
- Green after `9d9565d` (B2) and `1913996` (B3). The B2 cases in `tests/test_extends.py`:
  - an extra field is valid and is written after the core fields by `reg render`
  - the merged document is checked field by field
  - an unknown field is still refused
  - the game's `required`, the game's `$defs` and the game's `x-unique` apply, and so does the core's `allOf` (verified needs evidence and date)
  - an extended `core:hotkeys` keeps the `global` clash
  - load errors for a forbidden key (4 keys), a redefined core property, a `$defs` clash, a nested `x-extends` (in a property and in `allOf`), a non-`core:` target (a path and a list), and a missing core schema
  - the registry load error names the registry
  - `wsc gates --only schemas` checks the merged document: an unsupported keyword in the addition, an unresolved `$ref` and a load error all fail it, and a `$ref` to a core `$defs` entry passes
  - open question 4: a `core:jobs` extension with an extra field (in `dir` storage) passes `wsc jobs check`
- The B3 cases in `tests/test_registry.py`:
  - `Space` with `any_modifier` clashes with `Alt+Space`, `Ctrl+Shift+Space` and `Space`, in the same context and through `global`
  - it does not clash in another context, with `Alt+S`, or with `Alt+Spacebar` (the key is compared whole)
  - `S` with `shift` clashes with `Shift+S` and `S`, but not with `Ctrl+S`, `Ctrl+Shift+S` or `Alt+S`
  - without the flag the match stays exact
  - `fires_with` on `Alt+Space` or `Shift+S` is refused, and so is an unknown value; a mod row may carry the flag
  - two flagged rows on one key clash
- The existing hotkey cases are unchanged and green: `add_hotkey` only gained `**extra`.
- Full `python3 wsc.py gates` (Windows, local): 13 ok, 1 warn (the usual skips), 0 failed; 356 host tests.
- CI run 41715343781 on `1913996`: gates on ubuntu-latest, gates on windows-latest, proxy and harness-windows are all green.

## The consumer registry check
- I made a scratch copy of napoleon-remastered HEAD `6cbb9e9`: `wsc.toml` and `registries/`, with this branch's core at `core/`.
- With its rows as they are, `gates --only registries,schemas` is ok: 9 registries, 13,198 rows, including the 128 hotkeys rows. The new field is optional, and the core's own `registries/` are unaffected.
- With `fires_with` written on the 36 rows whose `source_ref` ends in `modifier=ANY` (4 rows) or `modifier=ALLOW_SHIFT` (32 rows), the gate is still ok: every flagged binding is bare, and the vanilla table does not clash with itself under the new rule.
- With a probe mod row `Alt+Space` in `battle` added, the gate fails with `... 'mod.probe' and 'vanilla.fps.show_allied_units_proxies.0' ...: Alt+Space reaches Space, which fires with any modifier`.
- What napoleon may do after the tag (nothing is required: the field is optional): as an optional job, `hotkeys import` writes `fires_with` on its 36 vanilla rows (`ANY` becomes `any_modifier`, `ALLOW_SHIFT` becomes `shift`) and reseeds; `wild_of` and `reaches` read the field instead of the `source_ref` suffix. Context families and the `all_modes` wildcard stay in napoleon's verb until B61 is built.

## Version
0.17.0. `origin/main` was 0.15.0 and the highest open job branch was `job/W7` at 0.16.0, checked again before the hand-back. If another row merges 0.17.0 first, this branch takes the next free number and merges `main` (never a rebase).

## Deviations from the brief, and why
- `warscape/schema.py`: a one-line docstring change listing the extensions the validator skips (x-wildcard, x-chord, x-extends). There is no code change.
- `warscape/gates.py` keeps its `import json`, now unused after `gate_schemas` moved to `load_schema`. I left it so this job's diff stays inside `gate_schemas` for the merge with W11; it can go in any later gates change.
- Open question 3 is filed as a backlog line (B61) as well as here. B61 may collide with another row's new backlog number at merge time; whoever merges second renumbers.
- The brief names Sonnet; this session ran on Opus by Liam's choice.
- The build ran as a subagent and the harness refuses a subagent's Write of a report file, so the orchestrator wrote this report from the builder's returned text, set the row to review and opened the pull request (same Claude-Session as the build).

## Open questions
1. As recommended, `fires_with` is an enum, not B3's boolean. The `shift` reading (the key alone or with Shift, not Ctrl) follows napoleon's vanilla-table reading and has not been proved in game. It is one line in `_chord_reach` if the game proves otherwise.
2. `fires_with` is allowed on any source, as recommended; one more `allOf` entry would restrict it to vanilla.
3. Context families (`battle` with `battle_land` and `battle_naval`) and a second wildcard context (`all_modes`) are filed as B61. They are the last clash rules napoleon's own `hotkeys check` holds that the core gate lacks.
4. A game may extend `core:tools` or `core:jobs`. The `core:jobs` case is tested; `x-source: tool-headers` comes from the core unchanged.
5. A game `required` entry naming a field that exists in neither the core nor the game's `properties` is not refused at load: every row would then fail validation, which is loud enough. Say if it should be a load error.

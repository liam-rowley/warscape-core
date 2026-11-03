# W14: Core schema extension and modifier-agnostic hotkeys

Model: Sonnet, reason: none needed (Sonnet is the default). Pure Python in the registry framework and one schema, all host-testable; no PC, no DLL.
Budget about 70 tool calls. At the cap, stop, commit, and report what is left.

## Goal
Two registry changes from the review of PR 1 (`docs/BACKLOG.md` B2, B3; both lines removed when this merges):
- **B2, extend a core schema.** Core schemas set `additionalProperties: false`, so a game that needs one extra field must copy the whole schema into its repo
  and loses every later core change to it. A game schema with `"x-extends": "core:<name>"` plus its extra properties is merged with the core schema at load.
- **B3, modifier-agnostic hotkeys.** Some vanilla keys fire with modifiers held (Empire: Esc, Space, Delete, Insert fire with any modifier, so a mod Alt+Space
  clashes with vanilla Space), and the exact-match clash check (`x-unique` on `binding, context` with the `global` wildcard) misses that. A hotkeys row can say how
  its bare key fires, and the clash check compares bare keys for those rows.

## Decisions already made (follow them; a deviation goes in the report with its reason)
### B2: `x-extends`
1. **Where:** one new function in `warscape/registry.py`, `load_schema(spec, root) -> dict` (read the file, resolve `x-extends`, return the merged document), used by
   `Registry.__init__` and by `warscape/gates.py` `gate_schemas` (which today reads raw files through `schema_path`, so it would check the partial document). Every
   other reader of a schema file goes through it too (`grep -rn "schema_path\|schema.json" warscape`). `schema_path` stays as is.
2. **Form:** only at the top level, only `"core:<name>"` (one level: a core schema never extends, and a game schema cannot extend another game schema). The extending
   document may hold only: `x-extends`, `$schema`, `$id`, `$comment`, `title`, `description`, `properties`, `required`, `allOf`, `$defs`, `x-view`, `x-unique`.
   Anything else is a load error naming the key (closed, in the spirit of C3: a key that would silently change the core's meaning, such as `additionalProperties`,
   `type` or `x-wildcard`, is refused rather than merged). An `x-extends` anywhere below the top level is an error too (the validator skips `x-` keys, so it would
   otherwise be ignored).
3. **Merge:** `properties`: the core's, then the game's added after them in the game's order; a game property whose name the core already has is an error (narrow a
   core property with an `allOf` entry instead). `required`: the union, core order first. `allOf`: the core's entries, then the game's. `$defs`: merged, a name clash
   is an error. `x-unique`: the core's tuples, then the game's. `x-view`, `title`, `description`, `$id`: the game's when given, else the core's. Everything else comes
   from the core unchanged (so `additionalProperties: false` still holds over the merged property set). The merged document must pass `check_schema`.
4. **Canonical key order** follows the merged `properties`: core fields first, then the game's. Say it in the `registry.py` docstring, where the other `x-` extensions
   are documented, and in `README.md` "Registries".

### B3: how a hotkey's bare key fires
5. **Field:** `fires_with` on `schemas/hotkeys.schema.json`, an enum `"any_modifier"` | `"shift"`; absent means the binding fires exactly as written. This is wider
   than B3's boolean `fires_with_any_modifier` on purpose: the only consumer's registry (napoleon-remastered `registries/hotkeys.jsonl`) has 4 rows whose vanilla
   modifier is `ANY` and 32 whose modifier is `ALLOW_SHIFT` (the key alone or with Shift; napoleon `tools/verbs/hotkeys.py` header and `wild_of`/`reaches`), today
   encoded only as a `source_ref` suffix that its own verb parses. One field covers both. See Open questions 1.
6. **Schema rule:** a row with `fires_with` has a bare binding (no `+`), enforced with an `allOf` `if`/`then` entry like the existing F4 rule. Allowed on any `source`
   (a mod key the proxy reads raw can fire with any modifier too); see Open questions 2.
7. **Clash rule, generic:** a new schema extension `x-chord: {"field": "binding", "flag": "fires_with"}`, read by `Registry._check_unique` and documented in the
   `registry.py` docstring. For every `x-unique` tuple that contains `field`, two rows' values of `field` are compared as `<mod>+...+<key>` chords (separator `+`):
   they clash when equal (case-insensitive, as now), or when one row's flag is `any_modifier` and both keys (last segment) are equal, or when one row's flag is `shift`,
   both keys are equal and the other row's modifiers are none or exactly `Shift`. The other fields of the tuple, and `x-wildcard` (`context: global`), apply as today.
   The message says which rule fired (`... Alt+Space reaches Space, which fires with any modifier`). No hotkeys-specific code in `registry.py`: the meaning of the
   two flag values is part of the `x-chord` extension, documented once.

## Scope: files this job touches
`warscape/registry.py` (`load_schema`, the `x-extends` merge, `x-chord` in `_check_unique`, the docstring), `warscape/gates.py` (`gate_schemas` through
`load_schema`), `schemas/hotkeys.schema.json` (`fires_with`, its `allOf` rule, `x-chord`, the description), `tests/test_registry.py` (hotkey cases),
`tests/test_schema.py` or a new `tests/test_extends.py` (B2 cases), `README.md` ("Registries": the two new extensions), `docs/CONSUMING.md` (a short "Extending a
core schema" paragraph with a minimal example), `docs/BACKLOG.md` (remove B2, B3), `VERSION`. No change to `warscape/schema.py` is expected (it already skips `x-`
keys); if one is needed, say why in the report. No game names in core files.

## Steps
1. Read `warscape/registry.py` (docstring, `schema_path`, `Registry.__init__`, `_check_unique`), `warscape/schema.py` (`check_schema`, `SUPPORTED`),
   `schemas/hotkeys.schema.json`, `tests/test_registry.py` (`add_hotkey`, `test_hotkey_clashes`) and `tests/_util.py`. Read napoleon-remastered's
   `tools/verbs/hotkeys.py` header and `find_problems` (read-only) for the `ANY`/`ALLOW_SHIFT` semantics the field must cover.
2. **Failing tests first**, committed red:
   - B2 (a throwaway repo whose `wsc.toml` names a repo schema extending `core:hotkeys` or `core:engine_facts`): a row with the extra field is valid and the field is
     written after the core fields by `reg render`; a row with an unknown field is still refused; a game `required` field is enforced; the core's `allOf` rules still
     apply; load errors for a forbidden top-level key, a redefined core property, a `$defs` clash, a nested `x-extends`, a non-`core:` target, and a missing core
     schema; `wsc gates --only schemas` checks the merged document (a broken game addition fails it).
   - B3: vanilla `Space` with `fires_with: any_modifier` clashes with a mod `Alt+Space` and with `Ctrl+Shift+Space` in the same context and through `global`, not in
     another context; `shift` clashes with `Shift+S` and `S` but not `Ctrl+S`; a row without the flag keeps today's exact rule (the existing cases stay green);
     `fires_with` on `Alt+Space` is refused by the schema; two flagged rows with the same key clash.
3. Build `load_schema` and the merge (decisions 1 to 4); switch `Registry` and `gate_schemas` to it.
4. Add `fires_with`, its rule and `x-chord` to the hotkeys schema; implement `x-chord` in `_check_unique`.
5. Docs, backlog, `VERSION`; then `python3 wsc.py gates` (full) and `python3 wsc.py policy --branch job/W14 --base origin/main`.

## Tests and acceptance
- The cases in step 2 red first, then green; every existing test green (`tests/test_registry.py` hotkey cases unchanged); `wsc gates` full green on Linux and Windows CI.
- The core's own `registries/*.jsonl` and napoleon's 128 hotkeys rows are unaffected by the schema change (the field is optional): check napoleon's file against
  this branch's schema read-only, e.g. `python3 wsc.py --root <a scratch copy of napoleon with this core at core/> gates --only registries`, and report the result.

## VERSION
A minor bump (a new schema extension and an optional field that consumers can start writing). Take the next free minor at merge time: `origin/main` says 0.15.0
when this brief was written and other W rows (W7 to W21) may claim minors first. Re-read `origin/main` `VERSION` and the open `job/*` branches before the last
commit; the second to merge takes the next free number and merges `main` (never rebase). Say in the report which number you took. Tags are Liam's.

## What consumers must do after the tag
Nothing is required: the field is optional and napoleon has no replacement schema today. Optional, as a napoleon job: its `hotkeys import` writes
`fires_with` (`ANY` -> `any_modifier`, `ALLOW_SHIFT` -> `shift`) on the 36 vanilla rows that carry a modifier today, reseeds, and its own verb's bare-key rule
(`wild_of`, `reaches`) can then read the field and later be dropped in favour of the core gate. The parent/child contexts its verb also handles (`battle` vs
`battle_naval`, the `all_modes` wildcard) are not in this job; see Open questions 3. A game that copied a core schema to add a field can switch to `x-extends`;
its rows' key order may change once (`wsc reg render`), a one-off diff.

## Kill criteria
- The merge needs a keyword the closed subset does not implement, or a merged document fails `check_schema` for a reason in the core schema itself: stop and report.
- `x-chord` cannot be added without changing the result of an existing `x-unique` case: stop and report the case.
- Core CI red after three fix attempts for a cause in this change: stop and report.
- Version collision handled as in VERSION above; never rebase a pushed branch.

## Open questions (with recommendations; the brief follows the recommendation unless Liam says otherwise)
1. **`fires_with` enum or B3's boolean `fires_with_any_modifier`?** Recommended: the enum (decision 5): napoleon's registry has 32 `ALLOW_SHIFT` rows next to 4 `ANY`
   rows, and a boolean would leave the larger group in a `source_ref` suffix. Napoleon's reading of `ALLOW_SHIFT` (key alone or with Shift, not Ctrl) is from the
   vanilla table, not proved in game (napoleon J21 report); the core rule follows that reading and is easy to change.
2. **Vanilla rows only?** B3 says vanilla. Recommended: any source, since the clash meaning is the same; restricting it is one more `allOf` line if Liam prefers.
3. **Context families** (napoleon J21: `battle` should clash with `battle_land` and `battle_naval`; `all_modes` behaves like `global` for one action) are a third
   hotkeys gap, not in B3. Recommended: a backlog line (an `x-wildcard`-like `x-family` prefix rule), filed by this job's report, not built here.
4. **Can a game extend `core:tools` or `core:jobs`?** Those schemas drive code (`x-source: tool-headers`, the job queue's fields). Recommended: allow it (extra
   fields are inert to that code) and add one test that a `core:jobs` extension with an extra field still passes `wsc jobs check`.
5. **File overlap with the other core rows (W7 to W21)**, for whoever merges second (merge `main`, never rebase):
   - **W15** (registry verbs: `reg remove` with an `x-ref` check, `last_used` stamping): `warscape/registry.py`, `tests/test_registry.py`. The heaviest overlap;
     different functions (`_check_refs`, storage) from this job's (`__init__`, `_check_unique`, a new loader).
   - **W13** (game gates): `warscape/gates.py` (`gate_schemas` here, the runner there) and `README.md` (different sections).
   - **W11**, **W12**: `warscape/gates.py`, other gate functions.
   - **W7** (engine-site values): `schemas/engine_sites.schema.json`, not the hotkeys schema; no shared file unless W7 needs a schema keyword (then `warscape/schema.py`).
   - All rows: `docs/BACKLOG.md`, `docs/DECISIONS.md` (only if this job adds a decision; none is expected) and `VERSION`.

## Finish
Report in `jobs/W14/report.md` (what was built, the tests red then green, the napoleon registry check, the version taken, deviations, open questions), then
`wsc reg set jobs W14 status=review report=jobs/W14/report.md` (`python3 wsc.py`). Push `job/W14`, open the draft pull request, and stop: an independent
reviewer merges (C18); Liam tags.

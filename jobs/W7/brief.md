# W7: Engine-site patch values: value_offset and numeric values from config keys

Model: Sonnet, reason: none needed (Sonnet is the default). A pure C++ header with host tests, a schema change, the table generator and a small driver
change; no reverse engineering, no PC, no change to how a plan is accepted or written. Budget about 80 tool calls; at the cap, stop, commit, report what is left.
Napoleon J27 keeps the live one-site proof, the ladders and the acceptance run.

## What
Backlog B59 (numeric patch values) and B41 (`value_offset`), the core half of napoleon-remastered J27 (its brief, `jobs/J27/brief.md` on that repo's `main`:
read "Decisions already made", the bullets "Numeric patch values need a core change" and "One configured value per family, never below stock", and
"Deliverables" 1 and 2). Today a `patch` row writes fixed `patch_bytes` behind a boolean key, and rows that share an RVA are refused, so every value
is its own DLL build. After this job a `patch` row may take its value from a numeric config key, so a player (and J27's ladders) change a distance
in the ini with no rebuild. Read first: `proxy/src/patch_engine.h` (layout and checks in its header comment), `proxy/src/patch_driver.cpp`,
`proxy/src/config.h`, `proxy/src/pe.h` (`ReadUnrelocated`, `RelocsInRange`), `proxy/tools/gen_tables.py`, `proxy/tests/test_patch_engine.cpp`,
`proxy/tests/test_config.cpp`, `schemas/engine_sites.schema.json`, `schemas/config_keys.schema.json`.

1. **Config: typed numeric keys with a range** (`schemas/config_keys.schema.json`, `proxy/src/config.h`, `gen_tables.py`).
   - Schema: optional `type` (enum `bool`, `int`, `float`, `string`), `min`, `max` (numbers, numeric types only). Without `type` the type is inferred
     from `default` as today, so every existing row validates unchanged. The trap this closes: JSON `0` is an int, so a float key with default 0 would
     silently become an int key; a key named by a `value_key` must carry an explicit `type` (`gen_tables.py` refuses it otherwise).
   - `config.h`: `kFloat = 3`; `KeySpec` gains `min` and `max` (`const char*`, `nullptr` = none) **appended after `def`**, so a table that omits them
     still compiles; `Config::Float(id)` returns a double. Float parsing accepts `[+-]digits[.digits][e[+-]digits]` checked by hand before the
     conversion (so the result never depends on the C locale: `1,5` is refused), and refuses `nan`, `inf` and anything that overflows a float32.
     An int key's value must fit int32. A value outside `[min, max]` is clamped to the nearer bound with a warning that says so; an invalid value takes
     the default with the existing warning, which names the key's real type (today it says "integer" for every non-bool).
   - `gen_tables.py`: `key_type` honours `type` (`float` emits `kFloat`; an int JSON value is a valid float), checks `default` and `release_value`
     against the type and the range, emits `min`/`max` only on rows that have them (rows without stay byte-identical), and writes floats in the ini
     with `repr` (`600.0`).
2. **Engine sites: `value_key` rows** (`schemas/engine_sites.schema.json`, `gen_tables.py`).
   - A `patch` row has exactly one of `patch_bytes` or `value_key` (an `x-ref` to `config_keys`): the `then` branch becomes a `oneOf` of the two
     `required` sets (`warscape/schema.py` implements `oneOf`). Optional with `value_key` only: `value_scale` (number > 0, default 1) and
     `value_floor_stock` (boolean, default false). `config_key` and `value_key` are exclusive on one row.
   - The encoding comes from the key's `type`: `float` writes float32, `int` writes int32, little-endian; `stock_bytes` must be 4 bytes. (A one-byte
     switch such as an override flag stays a boolean `config_key` row with `patch_bytes`.)
   - Generator refusals (each a message naming the row and the fix): value key missing, not `int`/`float`, or without an explicit `type`; its
     `default` not 0; no `max` (the tested ceiling: an ini can never ask for an untested value); `min` above 0 or `max` below 0 (0 must stay
     reachable, it means stock); stock not 4 bytes; a float row whose stock does not decode to a finite float32; `value_scale` or
     `value_floor_stock` without `value_key`; both `config_key` and `value_key`. **A round trip for every value row at `--check` time**: decode the
     stock bytes, encode them back, equal bytes; so every game's gate proves its own rows (J27 asked for this per row).
   - `SiteDef` gains, **appended at the end**: `const char* valueKey` (`nullptr` = fixed bytes), `uint8_t valueType` (`kValueNone`, `kValueF32`,
     `kValueI32`), `uint8_t valueFloorStock`, `double valueScale`. The generator emits them only on value rows, so a game whose rows use none gets a
     byte-identical `tables.h` (check it on the null game's existing rows).
3. **The pure resolution, `proxy/src/patch_value.h`** (new, no Windows types). `ResolveSiteValue(def, configured)` returns
   `{ action: Stock | Write | Refused, bytes[4], double written, why }`, in this order: configured 0 → Stock ("key at stock"); `written =
   configured × valueScale`; not finite, or outside int32 (int rows round to nearest), or outside float32 → Refused (the site stays stock, never the
   whole plan); with `valueFloorStock`, `written = max(stock decoded, written)`; encoded bytes equal stock → Stock ("equals stock"); else Write.
   `ResolveSites(sites, n, cfg)` returns an **effective copy** of the table: for each value row, `patch` = the resolved bytes and `enabled` = Write.
   `MakePatchPlan`, `ApplyPlanToBuffer` and `WritePlanAtomic` are **not changed**: they run on the copy, so the all-or-nothing checks (anchor, stock,
   relocation, overlap) hold for value rows exactly as for fixed rows, and a value row whose bytes already equal the resolved ones counts as done.
4. **The driver** (`patch_driver.cpp`): build the copy with `ResolveSites`, log one line per value row before the plan (`patch_engine: value <id> <-
   <key>=<v> (x<scale>[, floor stock <s>]): <written> f32|i32 [bytes]`, or `: stock (key at stock)`, `: stock (equals stock)`, `: REFUSED <why>, site
   left stock`), then run the plan on the copy. The existing `wrote ... [cur] -> [new]` line then shows the bytes written. A value row with its key at
   stock is checked like any site (the exe's identity) and not written.
5. **B41, `value_offset`: prove first, then decide.** The case is napoleon's imposter frame time, `mov dword [abs32], <float>` (`c7 05` + a relocated
   address + the float). Reading `pe.h`, the current layout may already register it: an anchor `c7 05 <abs32 as the file holds it>` compares through
   `ReadUnrelocated`, and `RelocsInRange` does not count a relocation that ends where the value starts. **First commit:** a host test in
   `test_patch_engine.cpp` with exactly that shape (a relocation on the address) planned and written at the preferred base and two ASLR bases, with a
   fixed row and with a value row.
   - It passes: no schema field. B41 closes with the test and a paragraph in the new doc ("an absolute address inside the anchor is compared
     unrelocated"); say so in the report.
   - It fails: add `value_offset` (optional integer 1..16, default 0): the stock bytes start `value_offset` bytes after the anchor; the gap bytes are
     compared unrelocated against a required `gap_bytes` field (so no byte between anchor and value goes unchecked), never written, and count in the
     overlap span (`MakePatchPlan` and `gen_tables.py`). The same three-base test then passes.
6. **The null game** (`proxy/tests/null_game/registries/`): one float key with `type`, `default` 0, `min` 0 and a `max`, and one value row naming it
   (refused at runtime with the other null sites, as today), so the generator, the generated table and the host build exercise the new fields; the
   null game's `tables.h` and ini regenerated, the existing rows' lines byte-identical.
7. **Docs and release:** `docs/PROXY_SITES.md` (new, short: the byte layout, the checks and all-or-nothing, boolean keys, value keys with the
   resolution order above, the generator's refusals, the absolute-address anchor or `value_offset`, how a game adds a site); a pointer in
   `docs/CONSUMING.md` "The proxy, the harness and the save tools"; the header comments of `patch_engine.h` and `config.h`; `gen_tables.py`'s
   `purpose:` line, then `python3 wsc.py reg add tools proxy/tools/gen_tables.py` (keeps its id); B41 and B59 removed from `docs/BACKLOG.md`;
   `VERSION` at the next free minor (0.16.0 today).

Files this job touches: `schemas/engine_sites.schema.json`, `schemas/config_keys.schema.json`, `proxy/src/config.h`, `proxy/src/patch_engine.h`
(`SiteDef` fields; `MakePatchPlan` only if `value_offset` is needed), `proxy/src/patch_value.h` (new), `proxy/src/patch_driver.cpp`,
`proxy/tools/gen_tables.py`, `proxy/tests/test_patch_engine.cpp`, `proxy/tests/test_config.cpp`, `tests/test_gen_tables.py` (new, the generator's
refusals on in-memory rows; set `WSP_GAME_ROOT` to the null game as `build.sh` does), `proxy/tests/null_game/registries/*.jsonl` and its generated
files, `registries/tools.jsonl`, `docs/PROXY_SITES.md`, `docs/CONSUMING.md`, `docs/BACKLOG.md`, `VERSION`. No game names in core files
(`tests/test_moved_tools.py` `NoGameNames`): say "a game"; the frame-time shape is described by its bytes. Branch `job/W7`.

## Tests and acceptance
- **Host tests**, `proxy/tests/test_config.cpp`: float parse (`600`, `600.0`, `-75.5`, `1e3`; refused: `1,5`, `nan`, `inf`, `1e39`, empty), int32
  bounds, clamping to `min` and `max` with the warning, the default on an invalid value, a typed table with and without `min`/`max`.
- `proxy/tests/test_patch_engine.cpp` (or a new `test_patch_value.cpp`; `build.sh` picks up every `test_*.cpp`): encode and decode vectors for the
  stock values a game's distance rows hold (float 50, 100, 150, 200, 0.25, -75; int 5 and 9: e.g. `00 00 c8 42` is 100.0); key 0 → stock; a value
  equal to stock → stock; scale (400 × 0.75 = 300); floor stock (80 under stock 100 → stock; 600 → 600); NaN, inf and an int32 overflow after scale →
  refused, that site stock and **the other sites still written**; the effective copy through `MakePatchPlan`, `ApplyPlanToBuffer` and
  `WritePlanAtomic` at three bases, writing only the 4 value bytes; a value row whose bytes already hold the resolved value → done; a bad anchor on any
  row still refuses everything; two value rows sharing one key; the B41 shape (step 5). Failing fixtures first where the code allows.
- `tests/test_gen_tables.py`: every refusal in step 2 and step 1 has a case; the round trip passes on good rows; a table with no value rows renders
  byte-identically to `main`'s generator output.
- **Acceptance:** `python3 wsc.py gates` green; with the null game, `proxy/tools/build.sh tests`, `all`, `repro` and `smoke` green (the smoke's site
  regex is count-agnostic); `python3 wsc.py policy --branch job/W7 --base origin/main` ok; the null game's existing `tables.h` lines unchanged.
  No PC: the live one-site proof (the log shows the written bytes) is J27's PC step b.

## The consumer's part (not here)
Napoleon J27 pins the tag Liam cuts from this job's merge (**`v0.16.0`**, or the number the report names after a collision) in its pin-bump commit.
Napoleon pins `v0.9.0` today, so unless another napoleon job has bumped the pin first, that commit crosses 0.10.0 to 0.16.0 and follows each
version's notes in `docs/CONSUMING.md` (0.15.0: delete a game verb named `discovery`). Then, all under J27 on `job/J27`: the `gfx.dist.*` keys with
`type`, `default` 0, `min` 0, `max` (set to the top of a ladder while stepping and to the ceiling for release: `max` is compiled in, so tightening it
is one rebuild before the 20-pass run), `release_value`, owner J27; the J9 rows rewritten (`patch_bytes` and the `gfx.*_proof` `config_key` replaced by
`value_key`, `value_floor_stock: true` on the distance rows, `value_scale` for followers such as the rope fade and knot at stock ratios; anchors and stock
unchanged); `gen_tables.py`; the live one-site proof; the ladders and the acceptance run (rule 79). The imposter frame time stays out of J27; with
step 5 done it can be registered by any later job. J24's fixed shadow rows may move to value keys later; nothing here requires it.

## Kill criteria
- A value row cannot be resolved without changing `MakePatchPlan`'s or `WritePlanAtomic`'s acceptance (an existing case in `test_patch_engine.cpp`
  would have to change to stay green): stop and report; do not loosen all-or-nothing.
- A refused value would refuse the whole plan or write a partial value: that is a bug, not a design choice; if it cannot be kept to its own site after
  about 15 calls, stop and report.
- The B41 test fails and `value_offset` would leave a byte between anchor and value neither compared nor written: stop that part after about 15 calls,
  ship B59 alone, and keep B41 in the backlog with what was found.
- A game's existing `tables.h` (the null game's rows) would change for rows that use no new field: stop and fix before anything else.
- CI red after 3 attempts for a cause in this change: stop and report.
- **Version collision:** `origin/main` `VERSION` is 0.15.0 and no other job branch is open (read 2026-11-03); W7 takes 0.16.0. Re-read `origin/main`
  `VERSION` and the open `job/*` branches before the last commit; the second to merge takes the next free number and merges `main` (never rebase).
  Say in the report which number was taken.
- Over about 80 tool calls: stop, commit, report what is left.

## Open questions (settle in the report)
- **Is `value_offset` needed at all?** Recommended: no, if the step 5 test passes on today's layout (likely: `ReadUnrelocated` already compares
  relocated anchor bytes and the relocation ends before the value); then B41 is a test and a doc paragraph. The fallback field is specified above.
- **Encoding from the key's type, or a row field?** Recommended: the key's explicit `type` (every J27 family is one encoding); add a row field only
  when one key must feed both an int and a float site.
- **`value_scale` in this job?** Recommended: yes (one multiply). J27 wants the rope fade and knot to follow the rope "at stock ratios" and the three
  mesh distances to scale together; without it each needs its own key and ladder. The building scalers fit too (key 1.5 × scale 10 = 15).
- **0 as "stock", or "equal to the default"?** Recommended: 0 (J27's own rule: "Value 0 or an absent key means stock"), guarded by the generator
  (`default` 0, `min` ≤ 0 ≤ `max`). A site that needs a literal 0 uses a fixed `patch_bytes` row.
- **Out of range: clamp or refuse?** Recommended: clamp to `[min, max]` with a warning (J27: "clamped to its tested ceiling"); NaN, inf and text that
  is not a number take the default (stock) with a warning (J27: "refused with a log line and the site left stock").
- **Floor at stock by default?** Recommended: no, opt-in per row (`value_floor_stock`): J24's shadow extrusion moves below stock (-75 to -150).
- **`config_key` and `value_key` on one row?** Recommended: exclusive; a master switch is the key at 0.

## Finish
Report in `jobs/W7/report.md` (what was built, the host test list, the B41 answer with its test, the generator refusals, deviations, open
questions, the version taken and what napoleon J27 must do), then `wsc reg set jobs W7 status=review report=jobs/W7/report.md`
(`python3 wsc.py`). Liam merges and tags the core; stop after the PR.

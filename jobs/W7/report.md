# W7 report: Engine-site patch values: value_offset and numeric values from config keys

Written by the orchestrator from the build agent's hand-back: the build ran as a subagent, and the harness refuses a subagent's Write of a
report file, so the parent writes it. Same Claude-Session as the build (a3c823fa-f176-4a15-ac97-f5c8704325bb). Built on Opus by Liam's
choice for this session (the brief names Sonnet).

A `patch` engine site can now take its value from a numeric config key (`value_key`, with optional `value_scale` and `value_floor_stock`), so a
player or a ladder changes a distance in the ini with no rebuild. Config keys gain `type`, `min` and `max`, with float keys and range clamping.
B41 (`value_offset`) turned out to need no new field: a host test shows that today's layout already registers an immediate placed after a relocated
absolute address. VERSION 0.16.0.

## What was built
- **Config** (`proxy/src/config.h`):
  - New `kFloat = 3`.
  - `KeySpec` gains `min` and `max` (`const char*`), appended after `def` with default member initializers, so tables that leave them out
    still compile cleanly under `-Wextra -Werror`.
  - `Config::Float(id)` returns a double.
  - Floats are checked by hand against `[+-]digits[.digits][e[+-]digits]` and converted with `std::from_chars`, so the C locale has no effect.
    `1,5`, nan, inf, values beyond float32 and empty text are refused.
  - An int must fit int32.
  - A value outside `[min, max]` is clamped to the nearer bound, with the warning `<key>=<v> is above the maximum <max>, clamped to <max>`.
  - The invalid-value warning now names the key's real type (`0/1`, `integer (int32)`, `number`).
- **SiteDef** (`proxy/src/patch_engine.h`): fields appended at the end, with defaults: `valueKey` (nullptr), `valueType`
  (`kValueNone`/`kValueF32`/`kValueI32`), `valueFloorStock`, `valueScale` (1.0). `MakePatchPlan`, `ApplyPlanToBuffer` and `WritePlanAtomic`
  are unchanged.
- **`proxy/src/patch_value.h`** (new, pure):
  - Encode and decode helpers for float32 and int32.
  - `ResolveSiteValue` resolves in the brief's order: key 0 gives stock ("key at stock"); then `x scale`; not finite, outside int32 (int rows
    round to nearest) or outside float32 gives Refused, with that site left stock; then the floor at stock; then encoded bytes equal to stock
    give stock ("equals stock"); otherwise Write.
  - `ResolveSites` returns an effective copy of the table with each value row's resolved bytes and its enabled flag, set true only for Write.
    The boolean `config_key` enabling moved here from the driver.
  - `ValueLine` is the per-row log line.
- **Driver** (`proxy/src/patch_driver.cpp`):
  - Builds the effective copy and logs one line per value row before the plan, at warn level for REFUSED.
  - Runs the plan and the atomic write on the copy. The existing `wrote ... [cur] -> [new]` line shows the bytes written.
  - A value row left at stock is marked `(value stock)` in the site list.
- **Schemas:**
  - `config_keys`: `type` (enum bool/int/float/string), `min` and `max` (numbers). If either bound is present, `type` is required and must be
    int or float.
  - `engine_sites`: `value_key` (an `x-ref` to `config_keys`), `value_scale` (exclusiveMinimum 0) and `value_floor_stock`.
    - A patch row must have exactly one of `patch_bytes` or `value_key` (`oneOf`).
    - `value_key` is allowed on patch rows only.
    - `value_scale` and `value_floor_stock` require `value_key`.
    - `config_key` and `value_key` are exclusive.
    - `value_key` is added to the view columns.
- **Generator** (`proxy/tools/gen_tables.py`):
  - `key_kind` honours `type` and otherwise infers it from `default` as before. A float default with no `type` is still refused.
  - Defaults and release values are checked against the type and the range. Floats are written with `repr` (`600.0`).
  - `min` and `max` are emitted only on rows that have them; value fields are emitted only on value rows.
  - The refusals are listed below.
  - Every value row gets a stock round trip (decode, encode, same bytes) at `--check`.
  - The `purpose:` line is updated and the tool row refreshed (`wsc reg add tools`, same id).
- **Null game:**
  - Key `null.distance`: float, default 0, min 0, max 600.
  - Row `null.value_distance`: a float32 at RVA 0x1100, `value_scale` 1.5, `value_floor_stock` true. It is refused at runtime along with the hook,
    and the smoke regex counts it.
  - `tables.h` and `nullgame.ini` regenerated. The existing rows' lines are byte-identical.
  - Its README mentions the new row.
- **Docs:**
  - `docs/PROXY_SITES.md` (new): byte layout, checks and all-or-nothing, the absolute-address anchor, boolean keys, value rows with the
    resolution order and log line, config key types, the generator's refusals, how a game adds a site.
  - Pointers in `docs/CONSUMING.md` ("The proxy, the harness and the save tools", from 0.16.0) and in the README doc table.
  - Header comments of `patch_engine.h` and `config.h` updated.
  - B41 and B59 removed from `docs/BACKLOG.md`.
  - VERSION 0.16.0.

### Generator refusals (each names the row and the fix; every one has a case in `tests/test_gen_tables.py`)
- **Value rows:**
  - The value key is missing, has no explicit `type`, or its type is not int or float (string, bool).
  - Its `default` is not 0.
  - It has no `max`.
  - Its `min` is above 0 or its `max` is below 0.
  - The stock is not 4 bytes.
  - A float row's stock is not a finite float32.
  - The stock does not round-trip.
  - `value_scale` or `value_floor_stock` appears without `value_key`.
  - `config_key` and `value_key` appear together, or `patch_bytes` and `value_key` together.
  - `value_scale` is not a number above 0, or `value_floor_stock` is not a boolean.
  - `value_key` is on a hook row.
  - A fixed patch row has neither `patch_bytes` nor `value_key`.
- **Keys:**
  - An unknown `type`.
  - A default or release value that is not of the key's type.
  - An int that does not fit int32.
  - A float that is not a finite float32.
  - `min`/`max` on a non-numeric key.
  - `min` above `max`.
  - A default or release value outside the range.
  - A float default with no type.
  - An id with no dot.

## Evidence
- **Host tests:**
  - `proxy/tests/test_config.cpp`, 128 checks:
    - Floats accepted: 600, 600.0, -75.5, 1e3, +2.5.
    - Floats refused: `1,5`, nan, inf, -inf, 1e39, 1e400, empty, `1.`, `.5`, `1e`, `0x10`, `1.5f`.
    - int32 bounds.
    - Clamping to min and max with the warning text.
    - An invalid value takes the default, and the warning names the type.
    - A typed table with and without a range.
    - The generated table parses the shipped ini, including the float key, with no warning.
  - `proxy/tests/test_patch_value.cpp` (new), 191 checks:
    - Encode and decode vectors: float 50, 100, 150, 200, 0.25, -75 (e.g. `00 00 c8 42` = 100.0); int 5, 9, -1.
    - Resolution: key 0 gives stock; a value equal to stock gives stock; scale 400 x 0.75 = 300.
    - Floor stock: 80 under stock 100 gives stock; 600 writes 600. Without the floor, below stock and -75 are written.
    - Int rows round to nearest (6.5 to 6, 7.5 to 8).
    - NaN, inf and an int32 or float32 overflow after scale are Refused: that site stays stock and the other sites are still written.
    - The effective copy goes through `MakePatchPlan`, `ApplyPlanToBuffer` and `WritePlanAtomic` at 0x400000, 0x01230000 and 0x7ff00000.
      Every changed byte lies inside a site's 4 value bytes, and the atomic write gives the same bytes as the pure apply.
    - A second plan on the written image counts every site as done.
    - With all keys at stock, value rows are checked but not written, and a value row with foreign bytes still refuses the plan.
    - A value row already holding the resolved value counts as done; one holding neither value is BadStock.
    - A bad anchor on a value row or on the fixed row refuses everything, with no protection calls.
    - Two value rows share one key (the second at x2).
    - The B41 shape as a value row.
    - The generated null table's value row round-trips, its key is numeric, and the shipped ini resolves it without a refusal.
  - `proxy/tests/test_patch_engine.cpp`, 209 checks: the B41 block (fixed row, three bases, two bytes changed, address untouched, done
    afterwards, a relocated-in-memory anchor refused under ASLR).
  - `tests/test_gen_tables.py` (new, 13 tests):
    - A golden header and ini for tables without the new fields, rendered by `main`'s generator before W7, match byte for byte.
    - Explicit types that match the inferred ones change nothing.
    - The null game is valid and current.
    - Typed keys render with ranges and `repr`.
    - Every refusal above.
    - The round trip.
    - The overlap check still holds for value rows.
    - The schemas pass `check_schema`, and their new rules accept and reject the expected rows.
- **Full gates:** `python3 wsc.py gates`: 13 ok, 1 warn (environment skips: no POSIX `sh`, no capstone), 0 failed.
- **DLL:** `build.sh all` and `repro` with the null game in a local ubuntu:24.04 container: mingw DLL built (imports and exports as before),
  15 host test programs passed, repro identical from another path.
- **CI run 41712246669 on d0445f9:** gates (ubuntu, windows), harness-windows and proxy (`build.sh all`, `repro`, `smoke` under wine) succeeded.
  Run 41710414965 on 01e10c8 failed only on a lua.org download timeout inside `build.sh all`; this change had no part in it.
- **Policy:** `python3 wsc.py policy --branch job/W7 --base origin/main` lists only the report (written here), the review and the done status
  (the reviewer's).
- **No PC:** the live one-site proof, where the log shows the written bytes, is napoleon J27's PC step b.

## Deviations from the brief and why
- **A new `proxy/tests/test_patch_value.cpp` instead of growing `test_patch_engine.cpp`.** The brief allows this. The B41 fixed-row case is
  in `test_patch_engine.cpp` as the first commit; the B41 value-row case is in `test_patch_value.cpp`.
- **`ResolveSites` returns a struct.** `EffectiveSites` holds `sites`, an `enabled` bool array and per-row `values`, because `SiteDef` has no
  enabled field. The boolean `config_key` enabling moved from the driver into `ResolveSites`, so the driver has one source for both kinds of
  row.
- **Int rows round ties to even** (`std::nearbyint` under the default rounding mode). The brief says "round to nearest" without naming a
  tie rule.
- **A refused value logs at warn level; the other value lines at info.**
- **One schema rule beyond the brief:** `value_key` only on `kind: patch`. The generator refuses it too.
- **The site table's comment line** gains ` [, valueKey, valueType, valueFloorStock, valueScale]`, but only in a table that has value rows.
  In the null game's `tables.h` that comment line and the two counts changed; every row line is byte-identical. A game without value rows
  gets a byte-identical file.
- **A README doc-table row** for `docs/PROXY_SITES.md` (README is not in the brief's file list).
- **Local builds ran in a plain ubuntu:24.04 container**, not through `build.sh --docker`: `--docker` mounts the game root, and with
  `WSP_GAME_ROOT=proxy/tests/null_game` that folder does not contain the core. The smoke ran in CI only, since there is no wine locally.
- **Call budget:** about 85 tool calls against the brief's "about 80" (relaxed for this session). No kill criterion was hit.

## Open questions
1. **Is `value_offset` needed?** No. The B41 test passes on today's layout at three bases, for a fixed row and for a value row. B41 is closed
   with the test and a paragraph in `docs/PROXY_SITES.md`: write an absolute address in the anchor as the file holds it.
2. **Encoding from the key's type or a row field?** From the key's explicit `type`, as recommended. Add a row field only if one key must ever
   feed both an int and a float site.
3. **`value_scale` in this job?** Yes, built and tested (400 x 0.75 = 300; two rows on one key at x1 and x2).
4. **0 as stock, or equal to the default?** 0, guarded by the generator (default 0, `min` <= 0 <= `max`). A site that needs a literal 0 uses a
   fixed `patch_bytes` row.
5. **Out of range: clamp or refuse?** Clamp to `[min, max]` with a warning in the config parser. Text that is not a number, nan and inf take
   the default (stock) with a warning. A value that overflows after scaling is refused at its own site only.
6. **Floor at stock by default?** No, it is opt-in per row (`value_floor_stock`).
7. **`config_key` and `value_key` on one row?** Exclusive, refused by both the schema and the generator; the key at 0 is the off switch.
- **Version taken:** 0.16.0. `origin/main` was at 0.15.0 and no other job branch was open when this was pushed.
- **What napoleon J27 must do:**
  - Pin `v0.16.0` (crossing 0.10.0 to 0.16.0 and following each version's notes in `docs/CONSUMING.md`; 0.15.0 deletes a game verb named
    `discovery`).
  - Keys `gfx.dist.*` with an explicit `type`, `default` 0, `min` 0, `max` (the tested ceiling, compiled in), `release_value`, owner J27.
  - J9 rows rewritten to `value_key`, with `value_floor_stock: true` on the distance rows and `value_scale` for followers; anchors and stock
    unchanged; 4-byte stocks only. The one-byte override flag stays a boolean row.
  - Run `gen_tables.py`, then the live one-site proof, the ladders and the acceptance run.
  - The imposter frame time can now be registered by any later job with no core change.

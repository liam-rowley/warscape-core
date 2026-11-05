# Engine sites: patches, hooks and value rows

Owner of: how the proxy patches and hooks a game's exe in memory (`proxy/src/patch_engine.h`, `proxy/src/patch_value.h`,
`proxy/src/patch_driver.cpp`, `proxy/src/config.h` for the keys), the `engine_sites` and `config_keys` registries
(`schemas/engine_sites.schema.json`, `schemas/config_keys.schema.json`) and their generator (`proxy/tools/gen_tables.py`).
The exe on disk is never touched. A game's rows, addresses and evidence stay in the game repo.

## The byte layout
One row is one RVA. The bytes from that RVA are the **anchor** (fixed context the site is recognised by: an opcode before an immediate,
the padding before a function), then the **stock** bytes; a patch replaces the stock bytes, a hook detours at the first stock byte:

    rva                      rva + len(anchor)
    | anchor_bytes ...       | stock_bytes ...   (patch_bytes, or a value row's bytes, replace stock_bytes)

At most 32 anchor and 32 stock bytes. RVAs are rebased at run time (actual module base; ASLR is on).

## The checks, all or nothing
Every site is checked, then the driver decides once (`MakePatchPlan`): the site lies in one section's file-backed bytes (a hook in an
executable one); anchor and stock compare equal after the load delta is taken off every relocated dword (`ReadUnrelocated`); a patch's
value bytes carry no relocation; no two sites overlap. A patch whose bytes already equal its patch bytes counts as done. **Any bad site
means nothing is written**, and every site is still logged. At write time every page a written site touches is made writable first,
once, and keeps its own old protection; one failure restores the pages already changed and writes nothing (`WritePlanAtomic`). After the
write each page is restored once with its recorded value and read back: `patch_engine: protections restored on <n> page(s): <rva>=<prot> ...`,
and a `left changed` warning for a page that does not read back as recorded (a copy-on-write page reads back as its written form; W33, C29).
A disabled site is still checked: it is part of the exe's identity.

**An absolute address inside the anchor** (`c7 05 <abs32> <imm32>`, `mov dword [abs32], imm32`) needs nothing special: write the
address in the anchor as the file holds it (unrelocated). `ReadUnrelocated` compares it at any base, and its relocation ends where the
value starts, so it does not count as a relocated value. `test_patch_engine.cpp` (the B41 case) and `test_patch_value.cpp` plan and
write that shape at the preferred base and two ASLR bases.

## Fixed rows and boolean keys
A `patch` row with `patch_bytes` writes those bytes. `config_key` (a boolean key) switches it: off = checked, not written. A one-byte
switch (an override flag) stays this kind of row.

## Value rows (`value_key`)
A `patch` row may take its bytes from a numeric key instead: `value_key` names an `int` or `float` key, and the key's explicit `type`
decides the encoding (int32 or float32, little-endian; `stock_bytes` is 4 bytes). Optional: `value_scale` (a number above 0, default 1)
and `value_floor_stock` (default false). `patch_bytes` and `config_key` are not allowed on a value row. Before the plan the driver builds
an effective copy of the table (`ResolveSites`); `ResolveSiteValue` decides each value row, in this order:

1. key at 0 (or absent): **stock** ("key at stock"): checked, not written;
2. `written = configured x value_scale`;
3. not finite, outside int32 (int rows round to nearest) or outside float32: **refused**, that site left stock, the others go on;
4. `value_floor_stock`: `written = max(stock value, written)`;
5. the encoded bytes equal stock: **stock** ("equals stock");
6. else **write** the encoded bytes.

The plan then runs unchanged on the copy, so every check above holds for value rows. One log line per value row precedes the plan:
`patch_engine: value <id> <- <key>=<v> (x<scale>[, floor stock <s>]): <written> f32|i32 [bytes]`, or `: stock (key at stock)`,
`: stock (equals stock)`, `: REFUSED <why>, site left stock`; the usual `wrote <id> ... [cur] -> [new]` line shows what was written.
Several rows may share one key (a family of distances; followers at a ratio through `value_scale`).

## Config keys
`config_keys` rows may carry `type` (`bool`, `int`, `float`, `string`); without it the type is inferred from `default` (JSON `0` is an
int, so a float key with default 0 needs `"type": "float"`). Numeric keys may carry `min` and `max`: a value outside is clamped to the
nearer bound with a warning. An int must fit int32; a float is `[+-]digits[.digits][e[+-]digits]` (locale-free: `1,5` is refused),
never nan, inf or beyond float32. An invalid value takes the default with a warning naming the key's type. The ini writes floats as
`600.0`.

## The generator's refusals
`gen_tables.py` (and `--check` in the gates) refuses, naming the row and the fix: a value key that is missing, not `int`/`float`, or
without an explicit `type`; its `default` not 0; no `max` (the tested ceiling: an ini can never ask for an untested value); `min` above 0
or `max` below 0 (0 must stay reachable, it means stock); stock not 4 bytes; a float row whose stock is not a finite float32; stock
bytes that do not round-trip (decode, encode, the same bytes: every game's gate proves its own rows); `value_scale` or
`value_floor_stock` without `value_key`; `config_key` or `patch_bytes` with `value_key`. For keys: a type, default, release value, min or
max that is not of the key's type, `min` above `max`, a default or release value outside the range. Tables with no value rows and no
ranges render byte-identically to before (`tests/test_gen_tables.py`).

## How a game adds a site
Find the bytes in the game's exe, add the `engine_sites` row (and its key) with `python3 core/wsc.py reg add`, run
`python3 core/proxy/tools/gen_tables.py`, check it offline with `python3 core/proxy/tools/gen_tables.py --exe <staged exe copy>` (every site `MATCH`: [UPGRADING.md](UPGRADING.md)),
rebuild the DLL and read the start-up site check in `proxy.log`. For a value row: the key with
`type`, `default` 0, `min` 0 (or below), `max` at the top of the tested steps, a `release_value`; the row with `value_key` and, where
needed, `value_scale` and `value_floor_stock: true`.

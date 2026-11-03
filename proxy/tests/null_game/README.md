# The null game (J12)

A fixture game repo for warscape-core's own CI: `WSP_GAME_ROOT=proxy/tests/null_game` makes `proxy/tools/layout.py` treat this
folder as the game, so `proxy/tools/build.sh all|repro|smoke` builds the DLL from `proxy/src` with the null adapter
(`proxy/null/`) and runs every host test, and `pc_deploy.py kit --what harness` builds a harness kit from `harness/null/`.
`registries/` holds the config keys the core reads and two engine sites that are always refused: a hook and a value row (W7, its
float key `null.distance` with a range), so the generator, the generated table and the host build exercise every field. Nothing here is a real game;
regenerate `proxy/null/generated/` and the ini with `WSP_GAME_ROOT=proxy/tests/null_game python3 proxy/tools/gen_tables.py`.

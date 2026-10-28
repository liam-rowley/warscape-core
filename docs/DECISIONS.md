# Decisions

One line per decision: date, who, the decision, and whether it is reversible. **Append only**; a reversal is a new dated line that
names the one it replaces. Detail lives in the doc or code that owns the topic. Numbers are `C<n>` so they never collide with a game
repo's `D<n>`. Lines marked "proposed" came in a pull request; Liam's merge of that pull request accepts them.

| # | Date | Who | Decision | Reversible |
|---|---|---|---|---|
| C1 | 2026-10-28 | Liam | The core holds the game-agnostic machinery (`napoleon-remastered` `docs/plans/PLAN.md` section 4; its D10, D18); game repos pin a released version and never patch it in place. Empire is not modified until it moves onto the core. | no |
| C2 | 2026-10-28 | Liam | Python 3.12, standard library only, so CI and a fresh clone need no installs. | yes |
| C3 | 2026-10-28 | proposed (Claude, PR 1) | Schemas are checked by a closed stdlib subset of JSON Schema 2020-12 (`warscape/schema.py`): any keyword it does not implement is refused, never ignored. If the subset falls short, the fallback is to vendor `fastjsonschema` (pure Python, no dependencies), not to grow the subset into a full validator. | yes |
| C4 | 2026-10-28 | Liam | Living-doc size cap 30 KB, dated records exempt, as a config value (`wsc.toml` `[docs] max_kb`). KB means KiB (1024 bytes) (proposed, Claude). | yes |
| C5 | 2026-10-28 | proposed (Claude, PR 1) | Repo configuration is TOML (`wsc.toml`, read with stdlib `tomllib`) so it can carry comments; registries stay JSONL. | yes |
| C6 | 2026-10-28 | proposed (Claude, PR 1) | The pre-push hook runs the fast gates on every push to any branch (Empire's checked main only); bypass is `git push --no-verify` with a reason in the commit. | yes |
| C7 | 2026-10-28 | proposed (Claude, PR 1) | Registry JSONL merges by union (`.gitattributes`); a union that keeps two versions of a row fails `wsc reg check` (duplicate id) until fixed. | yes |
| C8 | 2026-10-28 | proposed (Claude, PR 1) | Tool ids: `wsc.<verb>` for verbs, the path slug for scripts. Library modules and host tests are not tools (no row); the `tools` section of `wsc.toml` says which globs. The header is the source of a tool row; there is no first-sentence fallback. | yes |

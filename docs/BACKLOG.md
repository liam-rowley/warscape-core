# Backlog

Core changes agreed but not yet built, highest value first. A game that needs one files it here (or as a PR); it ships in a tag.
Remove a line when its change merges.

| # | Change | Why | Raised |
|---|---|---|---|
| B1 | **Game-specific gates**: `wsc.toml` `[gates] dirs = [...]`, gate modules with the same contract as verbs (`NAME`, `run(ctx) -> Result`) | games can add verbs but not checks; napoleon will need some (vanilla key-file import, review-page status sync) | review of PR 1, 2026-10-28 |
| B2 | **Extend a core schema**: a game schema with `"x-extends": "core:<name>"` plus extra properties, merged at load | core schemas set `additionalProperties: false`, so one extra field means replacing the whole schema and losing core updates | review of PR 1, 2026-10-28 |
| B3 | **Modifier-agnostic hotkeys**: a `fires_with_any_modifier` field on vanilla rows; the clash check compares the bare key for those | Empire: Esc, Space, Delete and Insert fire with any modifier held, so a mod Alt+Space clashes with vanilla Space; the exact-match check misses it | review of PR 1, 2026-10-28 |
| B4 | **Large registries**: `x-view` option to skip or summarise the Markdown view | a 60,000-row assets registry renders a 4 MB view nobody reads; decide with napoleon's discovery phase whether game-derived rows are committed at all | review of PR 1, 2026-10-28 |
| B5 | **`core_pin` checks the tag**, not only `VERSION` (`git describe --tags --exact-match` in the core checkout) | an untagged core commit with the same `VERSION` passes today (the submodule sha is the real pin, so low risk) | review of PR 1, 2026-10-28 |
| B6 | **Stamp `last_used`** from the job queue when a job report cites a tool, then turn retirement warnings back on (C9) | nothing updates `last_used` yet | PR 1 report, 2026-10-28 |

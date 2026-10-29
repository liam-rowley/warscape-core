# Backlog

Core changes agreed but not yet built, highest value first. A game that needs one files it here (or as a PR); it ships in a tag.
Remove a line when its change merges.

| # | Change | Why | Raised |
|---|---|---|---|
| B1 | **Game-specific gates**: `wsc.toml` `[gates] dirs = [...]`, gate modules with the same contract as verbs (`NAME`, `run(ctx) -> Result`) | games can add verbs but not checks; napoleon will need some (vanilla key-file import, review-page status sync) | review of PR 1, 2026-10-28 |
| B2 | **Extend a core schema**: a game schema with `"x-extends": "core:<name>"` plus extra properties, merged at load | core schemas set `additionalProperties: false`, so one extra field means replacing the whole schema and losing core updates | review of PR 1, 2026-10-28 |
| B3 | **Modifier-agnostic hotkeys**: a `fires_with_any_modifier` field on vanilla rows; the clash check compares the bare key for those | Empire: Esc, Space, Delete and Insert fire with any modifier held, so a mod Alt+Space clashes with vanilla Space; the exact-match check misses it | review of PR 1, 2026-10-28 |
| B4 | **Large registries**: `x-view` option to skip or summarise the Markdown view | a 60,000-row assets registry renders a 4 MB view nobody reads; decide with napoleon's discovery phase whether game-derived rows are committed at all | review of PR 1, 2026-10-28 |
| B6 | **Stamp `last_used`** from the job queue when a job report cites a tool, then turn retirement warnings back on (C9) | nothing updates `last_used` yet | PR 1 report, 2026-10-28 |
| B7 | **Failing-fixture test for `core_pin` on a dirty core**: let the gate read `VERSION` from `ctx.core_root` (not the running core) so a test can point it at a throwaway dirty checkout | "never patch the core in place" is enforced but untested (napoleon J5 ledger) | napoleon J5, 2026-10-29 |
| B8 | **`DECISIONS.md` format gate** (rows numbered `C<n>`/`D<n>` in sequence, ISO date, reversible yes/no), plus append-only on pull requests; port `decisions_problems` from napoleon `tools/pr_policy.py` | both repos say "append only" in prose; napoleon enforces it in its PR policy since J5, the core does not | napoleon J5, 2026-10-29 |
| B9 | **Pin changes in one commit**: `core_pin` (or the PR policy, once B1 lands) checks every commit in a push or PR range, not just the tip: a commit that moves the `core` gitlink must set `wsc.toml` `[core] version` to the matching tag, and the reverse | `CONSUMING.md` says "commit `core` and `wsc.toml` together" in prose; a split pair passes today because only the tip is checked, leaving a commit that checks out the wrong core. Low value while upgrades are two lines | napoleon J17 review, 2026-10-29 |

# W141 report: Discovery tools: seven small fixes for napoleon J95

Built in the session of napoleon J95 (its Part A), which also wrote this row and brief because the core takes code only on a `job/W<n>` branch (plan PR #183). Every item's "Applies" grep still matched on `main`, so none was dropped.

## What was built
1. `exe.py` `mask_for`, `search`: fixed. A cut rel32 masks the bytes present, an address-like dword is masked only at a position that starts inside no operand, and `search` returns `[]` below `MIN_FIXED_BYTES` (6). Tests `test_rel32_cut_by_the_window_edge_masks_the_bytes_present`, `test_address_like_dword_across_an_operand_end_stays_fixed`, `test_pattern_below_the_fixed_byte_floor_is_not_found`.
2. Unclosed files in `lua_api.py` (three) and `test_discovery_lua.py` (one): fixed. No new test, as the brief says; `python3 -W error::ResourceWarning -m unittest test_discovery_lua` passes, 6 tests.
3. `db.py`: fixed. `parse_header` raises `ValueError` on a mark byte other than 1 (`test_header_with_another_mark_byte_fails`); the README has an Empty tables column and section (`test_readme_splits_out_the_empty_tables`).
4. `discovery check` reads `used_by`: fixed. `problems()` reports a dangling id and a row `write_used_by` would set differently, rebuilt from the committed atlas (`committed_art_users`). Tests in class `UsedBy`.
5. `briefpaths.py` Registry gaps: fixed. Only a bullet's own `path:` field is exempt (`test_registry_gaps_exempt_only_the_bullets_own_path`).
6. `shader_catalog.py`: fixed. `import` skips and lists a capture with no `frame.txt` and exits non-zero if none imported; `density --from-file` reads paths from a file or stdin. Tests in class `ImportAndDensity`.
7. `discovery ui` fails loudly: fixed. `extract_problem` exits 1 naming the folder and the command, and writes nothing. Tests in class `MissingExtract`.

## Evidence
- `python3 wsc.py gates` (full, Windows, 2026-11-07): 1606 host tests passed, 5 skipped (4 need capstone, 1 needs a POSIX sh). The run's one failure was `doc_paths` on my UPGRADING line, since reworded; `gates --fast` after that is the last gate run, and CI on this pull request is the full check of the final tree.
- The changed code against napoleon's committed files and the shipped packs, read-only, output in a scratch folder (no game launch):
  - `problems()` on napoleon `discovery/ui`: 0 problems, so item 4 does not fail the bump.
  - Mark byte: 1 on all 310 Napoleon and all 286 Empire tables.
  - Empty tables: 26 (1 with a schema, 25 without), matching the audit's 26 and 25.
  - Item 5 on napoleon's briefs: 2 have the section, 0 new errors.
  - `exe.py` against the committed `exe.json`, 2929 signatures: function unique 1159 to 1236, none 1190 to 1071, multiple 468 to 516, shared 33 to 28, unsearchable 4 to 3. 156 signatures changed class, all function signatures; 403 changed their masked count; no signature that stayed unique changed its RVA. 19 lost `unique` (18 to multiple, 1 to none).

Usage: 60 tool calls; models: opus; 1 session, shared with napoleon J95, counted by hand, about, 2026-11-07

## Deviations from the brief and why
1. `search` keeps `None` (class `unsearchable`) when the longest fixed run is under 4 bytes, as it did; the floor's `[]` applies after that check. The brief's "not found" holds for both, and the existing test and the class stay.
2. `test_two_signatures_on_one_address_are_shared_not_unique` used 4 and 5 byte patterns, now below the floor: the fixture grew to 6 and 7 bytes; what it asserts is unchanged.
3. Empty tables were never in "Not decoded" (they are `decoded: true`), so nothing moved out of it. A 0-row table that fails to decode stays in "Not decoded", because it is a real failure.
4. `discovery ui` checks the extract on every step, not only `art` and `live`: all of them read it through `Atlas`, and `rows` would write empty rows the same way.
5. `problems()` finds `assets.jsonl` beside `rows_path` rather than taking a new argument, which keeps the change inside `discovery/` (a verb change would have hit the kill criterion). A test tree without the file skips the check.
6. A section in `docs/UPGRADING.md`, outside the brief's `discovery/` scope: the core's rule for what a game must do at a bump.
7. `MIN_FIXED_BYTES` stays 6. Napoleon's `engine_sites` anchors go down to 1 byte, but those are read at a known RVA and never go through `search`; every pattern that does is a 16+ byte window or a guard site.

## Open questions
1. The 19 signatures that lost `unique` are candidates, not engine sites (the tool's own rule), but napoleon J9 started from those hits. recommended: napoleon's bump job re-runs `exe.py` and checks no `engine_sites` row rests on one of the 19. default after: 2026-11-21.

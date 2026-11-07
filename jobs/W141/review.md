# W141 review

## Round 1 (2026-11-07, branch job/W141 at 69d7b98)

**Verdict: merge.**

No blockers and no should-fix items. This round changes nothing outside the job folder and the row. The three later items below go in one `later` row on a `plan/` branch.

### Machines
- CI on the final head: gates run 42322611224 at 69d7b98 (push). `gates (ubuntu-latest)` and `gates (windows-latest)` both passed, 15 ok, 1 warn, 0 failed, 1606 host tests, 5 skipped, `doc_paths` ok. So the builder's missing full run after its last edit is closed. The warn is the `tests` line.
- `proxy` and `harness-windows` were skipped correctly: the `wsc.toml` `[ci.inputs]` filters match neither `discovery/` nor `docs/`.
- `policy` was skipped on the draft (run 42322619642), so it counts as nothing. The real run is on the pushed head of this round, after `gh pr ready`.
- Local `python3 wsc.py gates` (full, Windows, 2026-11-07, at 69d7b98): 15 ok, 1 warn, 0 failed, 1606 passed, 5 skipped.
- Latest main: the branch forks at ccb751a; origin/main is 9e93ffd. The one commit between is the v0.50.0 release and changes only `VERSION`. It shares no file with this branch, and `git merge-tree` is clean.

### A test that fails without each fix
I reverted each fix on its own in a scratch copy and ran its test module: 18 reverts, all 18 failed, and the unreverted tree passed. Per fix:
- Item 1: the E8 and the 0F cut rel32, the straddling dword, the floor, and the floor off by one.
- Item 3: the mark byte, the README column, the section.
- Item 4: the whole check, the dangling id, the differs branch.
- Item 5: the whole fix, and a bullet exempted whole.
- Item 6: the skip, the non-zero exit, `--from-file`.
- Item 7: the whole check and the db branch.

Item 2 is exempt by the brief. No bare `open(` is left at the four sites, and `python3 -X dev -W error::ResourceWarning -m unittest test_discovery_lua` passes, 6 tests.

### exe.py and committed results (risk-first reading)
I picked this because it is the one change that moves a game's committed facts. I ran `exe.py` read-only over both shipped exes into a scratch folder, with main's code and with this branch's, against napoleon's committed `discovery/diff/exe.json` (the game was not started).
- Main's code reproduces the committed file exactly (2929 signatures, all rows), so every difference below comes from this change.
- The branch's code changes one row, `signatures function`: unique 1159 to 1236, shared 33 to 28, multiple 468 to 516, none 1190 to 1071, unsearchable 4 to 3. This matches the report. `guard_site`, `patch_site` and `cfg_site` do not change class.
- The floor changes nothing today: 0 of 2929 signatures are below `MIN_FIXED_BYTES`; the lowest fixed count is 7 (function), 9 (patch and cfg), 10 (guard). So `none` does not yet include any "too short to say" case.
- No signature that stayed unique moved its RVA, and no `multiple` became `unique` at an address outside its old hits.
- The report's open question is answered. 26 signatures lost a candidate class: the report's 19 `unique`, plus 7 `shared` it does not count. None of napoleon's 64 `engine_sites` rows has its RVA within 32 bytes of any hit of any signature whose class or hits changed. A grep of `engine_sites.jsonl` and `registries/engine_facts` for all 26 lost names finds none. The only rows citing `exe.json` are the PE facts, which do not change. So no site rests on a lost hit.
- Nothing in core code reads `exe.json` beyond `discovery render`, and `docs/UPGRADING.md` says what a re-run does. The committed file stays byte-identical until a game re-runs it, so its meaning does not change silently. See later item 1 for the gap that remains.
- The report leaves out that `empire_unique` also flips on 53 rows. No tool reads that field.

### Other claims, on napoleon's committed files (read-only)
- Item 4: `problems()` gives 0 on real data, and the check is not vacuous: `assets.jsonl` is found (12295 rows), and the 6335 rows with `used_by` match 6335 rebuilt from the atlas.
- Item 3: the README gives 26 empty tables (1 with a schema, 25 without).
- Item 5: 2 briefs have the section, 0 errors. A bare path in `reason:` is caught as well as a backticked one.
- Item 7: `extract_problem` is None for all five steps on the real extract, so no false refusal. `wsc discovery ui` runs the pass as a subprocess and returns 1 on its exit code, so the failure reaches the shell.
- Deviations 1 to 7 are named with reasons. I accept them: deviation 6 (`docs/UPGRADING.md`, outside `discovery/`) is what a bump needs, and deviation 7's `MIN_FIXED_BYTES` stays the brief's 6.
- The report's exe evidence sat in a scratch folder, so nothing could be opened from main; the numbers above are my own re-run of it.

### Findings
No blockers. No should-fix.

**Later** (one row, `plan/` branch):
1. `discovery/exe.py:210` `method` still reads `{func_len, window, max_hits}`, the same before and after this change, so nothing in `exe.json` says which mask rule or floor made it, and no gate notices a file left on the old rule after a pin bump. See it: `detail.method` is identical in the old and new runs above though 156 classes differ. Fix: record `min_fixed_bytes` and a mask rule number in `method`. The header at `discovery/exe.py:11` also still describes the old mask and omits the floor.
2. `discovery/exe.py:51` `mask_for` walks bytes, not instructions, so `8b e8` (mov ebp,eax) reads as a call. All 5 signatures that fell to `none` (`cond_*`) had their tail masked only by that false operand, so they lost a hit because the new rule keeps the in-image dword inside it fixed. 182 function signatures have an in-image dword no longer fully masked. This is the brief's rule, and these are candidates, not sites; an instruction-length walk would remove it.
3. `discovery/shader_catalog.py:741` `listed_paths` reads `utf-8`, so a list written by PowerShell with a BOM makes the first path `'﻿C:/...'`, which fails loudly as file not found. `utf-8-sig` fixes it.

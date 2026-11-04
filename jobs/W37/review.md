## Round 1 (2026-11-04, branch job/W37 at c683d7a, review fix f6071a7)
**Verdict: merge.**

Checked against the brief: steps 6, 7, 8 branch on the build's own log and tables, never the game's name; the null game's assertions and final line are unchanged; the fixture is a named test fixture (adapter with `gesture = nullptr`); a second smoke run is in `ci/gates.yml.in` and the rendered workflow; one paragraph in `docs/CONSUMING.md`. No file under `proxy/src` changed. Report evidence: CI run 41810276745 (proxy job green, both paths); the red local run is described but not a citable log (accepted: the failure is the same text as napoleon run 41801657509).

Risk-first reading: `proxy/tools/build.sh` step 8 (a wrong site or an empty variable silently weakens the only off-PC check of a consumer's DLL).

### Fixed by the reviewer (1 commit, f6071a7)
- **should-fix, fixed:** `proxy/tools/build.sh` step 8 took the first `{ "...` line of the whole `generated/tables.h`. For a game with no engine sites the sites table holds only the sentinel, so the grep fell through to the first config key (`controls.gestures`), and the "no engine sites" branch never ran (the peek would use a key as a site id). Now the grep reads only the `kSites[ ... };` block. Checked on a zero-site header (empty result) and on the fixture (`null.dummy_hook`); `gates --fast` ok.

### Later
- The report's own deviation 1 (`--docker` mounts only the game root, so an in-repo fixture needs a scratch tree) is a fair follow-up; not blocking.
- The fixture copies the null game's generated tables; `gen_tables.py --check` covers it, per the report.

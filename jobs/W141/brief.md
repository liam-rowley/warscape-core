# W141: Discovery tools: seven small fixes for napoleon J95

Phase 1 (the pipeline). Napoleon's later sweep (its job J95, audit R4) found seven small faults in the discovery tools. Those tools became the core's files in napoleon J64, so a game job cannot fix them, and Liam chose one core pull request over backlog lines (napoleon D56: "the seven discovery code fixes go as one warscape-core PR inside J95, then a pin bump"). The core's `policy` takes code only on a `job/W<n>` branch, so this row is that pull request. Napoleon's `jobs/J95/brief.md` Part A is the source of these items.

Model: Opus, reason: builds run on Opus; the work itself is routine.
Budget about 90 tool calls: about 10 reading, 50 for seven fixes with their tests, 15 for gates, 15 for the report and the pull request.
Semver: patch
No DLL or harness input changes: `discovery/` and its tests only, so a game's pin bump to this tag carries no acceptance run for it (napoleon rule 79).
Subagents: none; do the work in this session.
No PC: `needs_pc` is false. Host tests only; the game is never started.

## Start
1. `git pull`; `python3 wsc.py jobs next --id W141` and follow its mechanics. If this session's model is not Opus, stop and say so.
2. Run each item's "Applies" grep on `main` first. An item already fixed is dropped and said so in the report; do not re-fix it.

## Target facts (check each again before relying on it)
- `discovery/tests` is in `[tests] dirs` in `wsc.toml`, so the `tests` gate runs these tests on Linux and Windows.
- `discovery/README.md` names the verbs that build the extract; item 7's message uses the verb it names.
- `decode_table` in `discovery/db.py` turns a `ValueError` into `status: failed`.
- `MIN_FIXED_BYTES` is 6 (napoleon D56). Check it against the shortest anchor in napoleon's `engine_sites` registry and change it only with a reason in the report.

## Decisions already made for this job
- One pull request, one test per item except item 2 (napoleon D56).
- The watcher half of napoleon J24 Later 5 (never edit a running `.sh`) is not here.

## Deliverables
1. **`exe.py` `mask_for`** (napoleon J6 Later 1). Applies: `grep -n "def mask_for" discovery/exe.py`. The second loop masks any 4 bytes whose value falls in the image, also across the instruction boundaries the first loop walked, so an address-like dword that straddles an operand boundary is over-masked; and a rel32 cut by the window edge (`i + 5 > len(window)`) is left unmasked, so its partial bytes must match. Fix: mask the rel32 bytes that are present when the window ends inside an operand, and mask address-like dwords only at positions that start inside no operand the first loop consumed. Then `search` treats a pattern with fewer than `MIN_FIXED_BYTES` fixed (True) bytes as not found (no hits): a named constant with a comment saying why. Test: a window with a cut rel32, a window with an address-like dword across an operand boundary, and a pattern below the floor returns `[]`.
2. **Unclosed files** (napoleon J6 Later 3). Applies: `grep -n "open(" discovery/lua_api.py discovery/tests/test_discovery_lua.py`. Use `with open(...) as fh:` or `Path.read_bytes` and `read_text` at each. No new test: run those tests with `python3 -W error::ResourceWarning` and say so in the report.
3. **`db.py`** (napoleon J7 Later 1 and 2). Applies: `grep -n "def parse_header\|def readme\|'empty'" discovery/db.py`. (a) `parse_header` returns the mark byte and nothing checks it: raise `ValueError` when it is not 1, per the header layout in the module docstring. (b) The README renders one count table and a "Not decoded" list: add an empty tables column to the totals table (declared rows 0, split by with and without a schema) and list the empty tables in their own short section instead of in "Not decoded". Tests: a header with mark byte 0 fails with the message; the README of a synthetic `tables.json` with one empty table with a schema and one without has the column and the section.
4. **`discovery check`: `used_by`** (napoleon J10 Later 3). Applies: `grep -n "used_by" discovery/ui_atlas.py discovery/gate.py`. Add to `problems()` (what `wsc discovery check` calls) a check that every assets row with `used_by` lists only ids that exist in the `ui_elements` rows, and report a row that `write_used_by` would now set differently. It works on the committed files only, like `problems` today. Test: a synthetic registry pair with a dangling id fails, a matching pair passes.
5. **`briefpaths.py` Registry gaps** (napoleon J11 Later 1). Applies: `grep -n "in_gaps" discovery/briefpaths.py`. `found_path_problems` skips every line under the Registry gaps heading. Fix: skip only the bullets and, inside a bullet, only its own `path:` field (the one `registry_gaps` parses); every other line and every other field of a bullet (the `reason:` text) goes through `token_problem` like the rest of the brief. Test: a brief with a clean bullet and a prose line naming a game-folder path under the heading reports exactly that line; a `reason:` field naming such a path is reported.
6. **`shader_catalog.py`** (napoleon J24 Later 5). Applies: `grep -n "def cmd_import\|density" discovery/shader_catalog.py`. (a) `import` with a named capture whose `frame.txt` is missing fails the whole import: skip it, collect the names, print one line listing the missing captures and how many were imported, exit 0 if at least one imported and non-zero if none did. (b) `density` takes capture paths as `nargs='+'`, which breaks past about 40 paths on a Windows command line: add `--from-file FILE` (one path per line, `-` for stdin) and keep the positional form. Tests: a synthetic capture folder with one missing `frame.txt` (import skips, lists, exits 0); `--from-file` with 100 paths yields 100 results.
7. **`discovery ui` fails loudly** (napoleon J65 Later 2). Applies: `grep -nE "extract|reach.json|art_keys" discovery/ui_atlas.py`. It writes empty `reach.json` and `art_keys.json` without an error when `extract/<target>` is missing. Fix: before the `art` and `live` steps, if the extract folder the step reads is absent or empty, exit non-zero with a message naming the folder and the command that builds it, and write nothing. Test: the step against a temp tree without the extract exits non-zero, names the folder, creates neither file.

## Out of scope
- Anything outside `discovery/` and this job's row and folder; shared helpers in `warscape/` (see Kill criteria).
- New discovery features; the watcher half of napoleon J24 Later 5; the provenance strings of W61; `shader_catalog.py import` scope of W119.
- Napoleon's facts and pin bump: its J95 owns them.

## Open questions
None: napoleon D56 settled both of J95's.

## Kill criteria
- More than half of items 1 to 7 are already fixed on `main`: do those that remain, then report; do not widen the scope.
- `python3 wsc.py gates` fails twice in a row on a test you did not touch, after a rebase on `main`: stop and report the failing test id.
- A fix needs a change outside `discovery/`: stop and file it as a `later` row instead.
- Over about 90 tool calls: stop, commit, report what is left.

## Finish
Write `jobs/W141/report.md` (`## What was built`, `## Evidence`, `## Deviations from the brief and why`, `## Open questions`, and the `Usage:` line): per item "fixed (test name)", "already fixed (where)" or "dropped (why)", and the commands run. Then `wsc reg set jobs W141 status=review report=jobs/W141/report.md`. Push and open a draft pull request; a fresh session reviews it.

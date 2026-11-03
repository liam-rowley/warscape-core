# W15: Registry verbs: reg remove, last_used stamping, exe words in find

Model: Sonnet, reason: none needed (Sonnet is the default). Three small, separate changes to the registry CLI and the tools check, all stdlib Python with host
tests; no proxy, no harness, no PC. Budget about 90 tool calls (about 25 per item, the rest for docs, gates and the report). At the cap, stop, commit, and
report what is left.

## Goal
Three backlog items (`docs/BACKLOG.md` B28, B6, B43; all three removed when this merges):
- **B28, `wsc reg remove <reg> <id>`.** No verb removes a row. With one file per row (`[storage] dir`) a `git rm` of the file works, but nothing checks first that
  no other row points at it (napoleon-remastered `jobs/J55/report.md`, open question 4). `tools.check` already tells people to "remove the row" with no verb to do it.
- **B6, tool last use from the job queue, and C9's retirement warnings back on.** `last_used` is set once, when `wsc reg add tools` creates the row, and nothing
  updates it, so C9 turned the warnings off (`[tools] retire_after_days = 0`). The consumer's plan wants "the tools registry flags tools unused for a set period
  for retirement" (napoleon `docs/plans/PLAN.md` line 52, its `jobs/J5/rules.md` row 72, which waits on this item).
- **B43, exe-shaped words in `wsc find`.** RE sessions search the exe by hand. The exe string index is core code since W4 (`discovery/exe_strings.py find`, its table
  `exe_strings.tsv.gz` in the game's discovery adapter); napoleon J9 (`jobs/J9/report.md`, core item 5) asked that `find` call it for exe-shaped words rather than
  index 24,648 strings into a registry.

## Decisions already made (follow them; a deviation goes in the report with its reason)
1. **`reg remove` refuses while anything points at the row.** `wsc reg remove <reg> <id> [<id> ...]` loads every declared registry, removes the rows in memory and
   refuses (exit 1, nothing written) when any of these holds, with one line per referrer naming the file, the row and the field:
   - a row of any registry has the id in a property whose schema carries `x-ref: <reg>` (directly or on `items`), the rule `Registry._check_refs` already applies;
   - the registry is the `x-source: tool-headers` one and another row's `status` is `superseded:<id>`, or the tool's `path` is still a tracked file
     (`ctx.files()`): "delete the file first, or supersede the row" (removing a live tool's row only makes `tools.check` fail on "tool without a registry row");
   - the registry is the jobs registry (`jobs`) and `<[jobs] dir>/<id>/` exists (`jobq.problems` would fail on a folder with no row);
   - backstop: `Registry.check` of every registry and, for the tools registry, `tools.check`, return a problem after the removal that they did not return before
     (the diff of the two lists is printed). This catches a reference kind the named rules miss.
   Removing several ids at once lets two rows that only point at each other go together. An unknown id is an error naming the registry. On success the rows are
   saved through `Registry.save()` (it already deletes a row file in `dir` storage and rewrites a JSONL) and the view re-rendered, like `reg set`.
   New method `Registry.remove(ids)` in `warscape/registry.py`; the checks live in the verb (`warscape/verbs/reg.py`), which already loads every registry.
2. **A tool's last use is derived from merged job reports, never written by the queue.** Writing `last_used` into tool rows from job branches would conflict: two
   job branches in flight that cite one tool both change the same line of the same row file (napoleon keeps `tools` in `dir` storage) to different dates, and
   GitHub does not merge that (napoleon J55's reason for one file per row). Instead `warscape/tools.py` gains `last_uses(ctx) -> {tool id: (date, report path)}`:
   - the jobs whose row says `done` (`jobq.main_rows`; nothing when the repo declares no `jobs` registry), each with its `report.md` and `review.md` read from the
     working tree;
   - the job's date is the date in the newest `## Round N (YYYY-MM-DD, ...)` heading of its `review.md` (`jobq.ROUND_HEAD`); a legacy review without such a heading
     uses the first `YYYY-MM-DD` in its first 5 lines (`jobq.DATED`, the rule `jobs check` already enforces); a job with neither is skipped;
   - a report **cites** a tool when its text contains the tool's `path` as a whole path (not preceded by a letter, digit, `_`, `-` or `.`, and not followed by a
     letter, digit or `_`; a leading `core/` before it still counts, so a game report citing `core/harness/job.sh` cites the core's `harness/job.sh` if that repo
     reads it), or, for a verb row, `wsc <verb>`, `wsc.py <verb>` or the id (`wsc.<verb>`) as a word;
   - the retirement check uses the later of the row's `last_used` and the derived date, and its warning names where the date came from
     (`live but last used 2026-08-01 (jobs/J12/report.md) ...` or `(row)`). `last_used` keeps its meaning as the floor: the date the row was added or a date set
     by hand (`wsc reg set tools <id> last_used=<date>` still records a use outside a report).
   The derivation is cached per process (`find`, `reg check` and the `registries` gate may call it more than once).
3. **The retirement window.** `warscape/repo.py` `DEFAULTS` keeps `retire_after_days = 0`: a repo without a job queue has nothing that records a use, the exact case
   C9 guards against. The consumer turns it on in its own `wsc.toml` (below). The core's own `wsc.toml` also stays at 0, with its comment rewritten: the core's
   tools (harness, proxy tools, discovery) are used mostly through a game's jobs, whose reports the core cannot read, so a core window would flag tools in daily
   use. Decision line: append the next free `C<n>` to `docs/DECISIONS.md` as `proposed (Claude, core W15)`: a tool's last use is the later of its row's `last_used`
   and the newest merged (`done`) job report that cites it, derived at check time, never written by the queue; this is the stamping C9 waited for, so a repo
   with a job queue may set `[tools] retire_after_days`; the default stays 0 and the core keeps 0 (its tools' uses are in its consumers' reports). Reversible: yes.
4. **`find` hands exe-shaped words to the core's exe index; no loader, no new key.** W13's brief (on `origin/brief/W13` until it merges, open question 6) asks W15
   not to invent a second extension loader beside W13's `warscape/gatemods.py`. None is needed: since W4 the index is core code and its table is an adapter file
   found through the existing `[discovery] adapter` (`proxy/tools/layout.py` `discovery_adapter()`), so `find` calls it directly. This job does not depend on W13.
   A later per-game `find` source (not asked for) would be a `find` stage of W13's gate modules; say so in the report, build nothing for it.
   - **Exe-shaped:** a search word (as typed, before `warscape/search.py` splits it on `_`) of at least 4 characters matching `^[A-Za-z_][A-Za-z0-9_]*$` that has
     an `_` between two letters or digits, or a lower-case letter followed by an upper-case one (`gfx_hardware_shadows`, `CampaignUI`, `get_character_by_cqi`).
     `--exe` searches the table for every word whatever its shape; `--in <regs>` without `exe_strings` in the list skips the table, `--in exe_strings` searches only it.
   - **Search:** the rows whose text contains every exe-shaped word, case-insensitively, as literals (`re.escape`), through `exe_strings`' own reader. Refactor
     `discovery/exe_strings.py` `find` into `search(table, pattern, refs_only=False) -> rows` and `line(row) -> str`, with `find` printing as today (its output
     and `discovery/tests/test_exe_strings.py` unchanged).
   - **Output:** after the registry hits, `exe strings (<adapter, repo-relative>/exe_strings.tsv.gz): <n> hits` and at most `-n` lines from `line()`, then
     `... <k> more (wsc find --exe ... -n <bigger>)` when cut. `--json` prints `{"registry": "exe_strings", "row": {<HEADER field>: <value>}}` per hit.
     The exit code is 0 when the registries or the table had a hit, 1 when neither did.
   - **No table:** no discovery adapter or no `exe_strings.tsv.gz` in it: silent (the core itself has none, so `find` in the core prints exactly what it prints
     today), unless `--exe` was given, then one line naming the fix (`exe_strings.py build <exe> --out <adapter>/exe_strings.tsv.gz` on the PC with the RE
     venv, `discovery/re_env.py`).
   - **Loading:** reuse `warscape/verbs/discovery.py` `_core(root)` and `_mod(name)` (they put `discovery/` on the path and point `paths` at the repo); pass the
     table path explicitly (`paths.adapter_file('exe_strings.tsv.gz')` after `_core`), because `exe_strings.TABLE` is fixed at import.

## Scope: files this job touches
- Changed: `warscape/registry.py` (`Registry.remove`), `warscape/verbs/reg.py` (`remove` action, header `Usage:` line), `warscape/tools.py` (`last_uses`, the retirement
  check and its warning; the "remove the row" message names `wsc reg remove tools <id>`), `warscape/jobq.py` (only if a small helper for "a done job's date" reads
  better there than in `tools.py`), `warscape/verbs/find.py` (the exe block, `--exe`, header `Usage:` line), `discovery/exe_strings.py` (`search`/`line` split; header
  `usage:` gains `wsc find` if you touch it), `wsc.toml` (the `retire_after_days` comment only).
- Tests: `tests/test_registry.py` or a new `tests/test_reg_remove.py`; `tests/test_tools.py` (derived last use, the window, the warning text); a new
  `tests/test_find_exe.py`; `discovery/tests/test_exe_strings.py` (only if the split needs a case). Use `tests/_util.py` `TempRepo` for throwaway repos.
- Rows: `python3 wsc.py reg add tools warscape/verbs/reg.py warscape/verbs/find.py` (and `discovery/exe_strings.py` if its header changed); ids are kept.
- Docs: `README.md` ("Use it": one `reg remove` line), `docs/CONSUMING.md` (a short "Tool retirement (W15)" paragraph: the derivation, the citation rule, the
  `[tools] retire_after_days` opt-in; one line in "Discovery" that `find` searches the adapter's `exe_strings.tsv.gz` for exe-shaped words), `docs/DECISIONS.md`
  (the new `C<n>`), `docs/BACKLOG.md` (remove B6, B28, B43), `VERSION`.
- Not touched: `proxy/`, `harness/`, `saves/`, `schemas/` (no schema change: `last_used` keeps its field), `warscape/repo.py` `DEFAULTS`.

## Steps
1. Read `warscape/registry.py` (docstring, `save`, `set`, `check`, `_check_refs`), `warscape/verbs/reg.py`, `warscape/tools.py` (`row_from_header`, `check`),
   `warscape/jobq.py` (`ROUND_HEAD`, `DATED`, `review_rounds`, `main_rows`, `problems`), `warscape/verbs/find.py`, `warscape/search.py`,
   `warscape/verbs/discovery.py` (`_core`, `_mod`), `discovery/exe_strings.py`, `discovery/paths.py`, `discovery/tests/test_exe_strings.py`, `tests/test_tools.py`.
2. **Failing tests first**, committed red:
   - `reg remove`: a row removed in `jsonl` and in `dir` storage (the file is gone, the view re-rendered); refused for an `x-ref` referrer (a scalar and an array
     item), for `superseded:<id>`, for a tool whose file still exists, for a job whose folder exists, for an unknown id; two rows pointing at each other removed
     together; nothing written on a refusal (the bytes of every registry file unchanged).
   - last use: a `done` job whose report cites a tool path moves that tool's last use to the review's round date; a verb cited as `wsc reg` and as `wsc.py reg`;
     a path inside a longer path (`xharness/job.sh`, `harness/job.sh.bak`) does not cite; a job that is not `done` does not count; a legacy review dated in its first
     lines counts; no jobs registry gives `{}`; with `retire_after_days = 90` an old row cited by a recent report does not warn and an uncited one warns, naming `(row)`.
   - find: an exe-shaped word prints the exe block from a synthetic table (write it with `discovery/tsvgz.py`, header `exe_strings.HEADER`) in a `TempRepo` with
     `[discovery] adapter`; a plain word does not; `--exe <plain word>` does; `--in tools` skips it; `--in exe_strings` searches only it; `--json`; exit 0 on an
     exe-only hit; no adapter: silent, and `--exe` prints the fix; in the core's own checkout `find` output is unchanged.
3. Build B28, then B6, then B43 (decisions 1, 2 and 3, 4).
4. Docs, the decision line, backlog, rows, `VERSION`; then `python3 wsc.py gates` (full) and `python3 wsc.py policy --branch job/W15 --base origin/main`.

## Tests and acceptance
- The cases in step 2 red first, then green; every existing test green; `wsc gates` full green on Linux and Windows CI.
- `python3 wsc.py reg remove tools <a live tool id>` in this checkout refuses (its file exists) and leaves `git status` clean.
- In a scratch copy of the consumer's tree (napoleon-remastered, read-only: copy it outside both repos, put this branch's core at `core/`, nothing committed
  there): `python3 core/wsc.py find gfx_hardware_shadows` lists the exe strings from `discovery/napoleon/exe_strings.tsv.gz` (needs `[discovery] adapter =
  "discovery/napoleon"` in the copy's `wsc.toml`: napoleon pins v0.9.0, so add the key in the copy only and say so), and a `last_uses` count over its done jobs
  (how many of its tools have a derived date, and how many would warn at 90 days). Record both in the report. If the copy will not load under the new core within
  about 10 calls (napoleon is several minors behind), skip this check and say why.

## VERSION
A minor bump: a new `reg` action, a changed `find` output and a changed `tools` check (consumer-visible, pre-1.0). Take the next free minor at merge time:
`origin/main` says 0.15.0 when this brief was written, `job/W7` claims 0.16.0, and other W rows (W7 to W21) may claim minors first. Re-read `origin/main`
`VERSION` and the open `job/*` branches before the last commit; the second to merge takes the next free number and merges `main` (never rebase). Say in the
report which number you took. Tags are Liam's.

## What consumers must do after the tag (napoleon-remastered; also goes into `docs/CONSUMING.md`)
- **No acceptance passes:** nothing under `proxy/` or `harness/` changes, so napoleon's rule 79 does not count this tag (its J58 core-diff rule).
- **Retirement warnings (opt-in):** set `[tools] retire_after_days = 90` (or another window) in its `wsc.toml` in the pin-bump commit or later; run
  `python3 core/wsc.py reg check tools` and retire what it lists (`reg set tools <id> status=superseded:<id>`, or `reg remove tools <id>` after `git rm` of the
  file), or cite the tool in the next report that uses it. Then close its `jobs/J5/rules.md` row 72 (`core B6`).
- **`reg remove`:** replaces `git rm registries/<name>/<file>.json` for a row (J55 report item 4); nothing to migrate.
- **`find` and the exe index:** works once napoleon is past 0.15.0 with `[discovery] adapter = "discovery/napoleon"` (W4's consumer half, napoleon J64); before
  that `find` behaves as today. Its RE notes that say "search the exe with `exe_strings.py find`" may say `wsc find <word>` instead.
- Napoleon pins v0.9.0 today: the commit that crosses this tag also follows each earlier version's notes in this file (0.10.0 to 0.15.0).

## Kill criteria
- `reg remove` cannot tell a referrer apart without a schema change (a reference kind that is neither an `x-ref`, a `superseded:` status nor a job folder, and
  that the before/after check does not catch): stop that part after about 15 calls and report the reference kind; ship B6 and B43.
- The derived last use would have to read git history (commit dates, `git log`) to be right: stop and report; the shallow CI checkout has no history, so it
  must come from files on disk.
- The `find` exe block changes `find`'s output or exit code in a repo without an exe table: that is a bug, fix it before anything else.
- `discovery/exe_strings.py find`'s output changes byte for byte for an existing caller: revert the split and call `find` with captured output instead.
- Core CI red after three fix attempts for a cause in this change: stop and report.
- Version collision handled as in VERSION above; never rebase a pushed branch.

## Open questions (with recommendations; the brief follows the recommendation unless Liam says otherwise)
1. **Derive the last use, or write it into the rows?** The row says "stamps". Recommended: derive (decision 2). Writing it from job branches conflicts whenever two
   jobs in flight cite one tool on different days (common: most PC jobs cite `harness/job.sh`), stamps jobs that never merge, and depends on a step someone
   can forget. Derived, it needs no write, no merge and no discipline. Cost: the `last_used` column of the rendered view shows the floor, not the derived date
   (the warning names the derived one). Alternative if Liam wants the column right: a `wsc reg render` pass that writes derived dates, run only on `main` by
   Liam; not built here.
2. **Retirement on in the core?** Recommended: no (decision 3): the core's tools are used through its consumers, whose reports it cannot see. Napoleon turns it on.
3. **Which words are exe-shaped?** Recommended: an identifier with an inner `_` or a lower-to-upper case change, 4+ characters, plus `--exe` to force. A plain word
   (`shadow`) would flood the output with exe strings on every search. Dotted names (`gfx.dist.trees`) are config keys, which the registries already hold.
4. **Search the exe table by AND of the exe-shaped words, or each word separately?** Recommended: AND (one block, like the registries' every-word match).
5. **`reg remove` on a `done` job row?** Recommended: refused while its folder exists (decision 1); a job's folder is history, and deleting it is a `meta/` decision,
   not a verb's.
6. **File overlap with the other core rows (W7 to W21)**, for whoever merges second (merge `main`, never rebase):
   - **W13** (game gate modules; on `origin/brief/W13`): `warscape/jobq.py` (it drops `call_hooks` and `S.hooks` and changes `brief_problems`) and
     `warscape/tools.py` per its file list. W15 only adds functions in `tools.py` and at most one helper in `jobq.py`: small. If W13 merges first, nothing in this
     brief changes (no hook is used).
   - **W12** (guards; queued): `warscape/jobq.py`, `warscape/checks.py`, `tests/test_jobs.py`; separate functions.
   - **W14** (schema `x-extends`; `job/W14` open): `warscape/registry.py` (schema loading); W15 adds `Registry.remove` only, and decision 1's `x-ref` walk must read
     the merged schema W14 builds (`self.schema` after load), which it does if it reads `reg.schema` as `_check_refs` does.
   - **W11** (`core_pin`): `warscape/gates.py`, `warscape/repo.py`; no shared function.
   - All rows: `docs/BACKLOG.md`, `docs/DECISIONS.md` (append-only, next free `C<n>`; W13 claims C21), `docs/CONSUMING.md`, `README.md` and `VERSION`.

## Finish
Report in `jobs/W15/report.md` (what was built, the tests red then green, the scratch-copy numbers from the consumer's tree or why they were skipped, the
version and the `C<n>` taken, deviations, open questions, what napoleon must do), then `wsc reg set jobs W15 status=review report=jobs/W15/report.md`
(`python3 wsc.py`). Push `job/W15`, open the draft pull request, and stop: an independent reviewer merges (C18); Liam tags.

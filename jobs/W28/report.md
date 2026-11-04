# W28 report: Small gate fixes: dates, strict JSON, skipped gates, the serve page, stale doc paths

Six gate fixes from the 2026-11-03 audit, each shown failing on a fixture first: `verified_dates` accepts only a date or a run id; strict JSON refuses duplicate keys (one hook, used by the json gate, the registry loader, `jobq` and `gen_tables.py`); `[gates] skip` needs `"<gate>:<decision id>"` and prints a warn line; the `jobs view` page pins marked by SRI, escapes raw HTML and sets a hash-based CSP; `gen_tables.py` reads its registries through the loader (dir storage gives the same bytes); a new `doc_paths` gate (a warning, per the kill criterion). VERSION 0.34.0, decision C28, backlog B87.

## What was built
1. **`verified_dates`** (`warscape/checks.py` `VD_DATED`, `VD_WORD`): a claim is dated only by an ISO date, a compact `20YYMMDD` date (run folders such as `20261104_a`) or a
   `reports/`, `runs/`, `records/` path; the loose alternatives (a `3-10` pattern, "session", `.md)` and `v2`) are gone, and the "verified" word match is case-insensitive
   (so "VERIFIED on PC" is seen at all). Failing first: `test_checks.VerifiedDates.test_only_a_date_or_run_id_dates_a_claim` failed on the old code (`[] != [1]`).
   **Lines newly flagged:** none. The gate over the core (100 living docs) and the fixture game (4) was green before and after, so no line needed a date.
2. **Duplicate keys** (`checks.no_duplicate_keys`, `checks.strict_loads`): `strict_json_error` and both registry loaders (`registry.py` `_load`, `_load_dir`, beside its `_boom`)
   use the one hook; `jobq.py` reads the legacy file, the failed-result JSONs, a branch's row file and JSONL rows with `strict_loads` (`gh` output untouched);
   `gen_tables.py` reads `identity.json` and `console_sources.json` with it. Failing first: `test_checks.StrictJson.test_duplicate_keys_are_refused` (error),
   `test_json_gate_refuses_a_duplicate_key` and `test_registry.Rows.test_a_duplicate_key_fails_load_naming_the_file` (failures) on the old code.
   No committed JSON in the core, the fixture game or the null game holds a duplicate key (`json` gate green: 79 files in the core, null game included; 4 in the fixture game).
3. **`[gates] skip`** (`warscape/gates.py` `skips`, `selected`, `run`): entries are `"<gate>:<decision id>"`; a bare name, an id the `[policy] decisions` file lacks, or no decisions
   file is a config error (exit 2) that names the fix; each skipped gate is one `WARN <gate> skipped <gate>: <id>` line; `--only <gate>` still runs it. Failing first: the four
   `test_gatemods.SkipIsNeverSilent` tests failed on the old code. The existing `test_skip_and_only_accept_game_gate_names` now uses the id form.
   The core cannot reach a rule inside a skippable gate (napoleon's `test_repo_rules.silenced` inside `tests`): README "Gates" says so; napoleon carries its own skip and decision.
4. **The serve page** (`warscape/jobq.py` `MARKED_URL`, `MARKED_SRI`, `view_csp`): `integrity="sha384-/TQb...MVi" crossorigin="anonymous"` on the marked 12.0.2 tag (hash computed
   2026-11-04 from the cdnjs file; jsDelivr's copy of 12.0.2 gives the same hash); a marked `html` renderer override returns escaped text; a CSP meta with `default-src 'none'`,
   `script-src <the marked URL> 'sha256-<inline script>'`, `style-src 'sha256-<inline style>'`, `img-src 'self' data:`, `connect-src 'self'`, `base-uri` and `form-action 'none'`.
   The inline script holds the token, so its hash is computed per page at render time. Failing first: `test_jobs.View.test_serve_page_pins_marked_escapes_raw_html_and_sets_a_csp`
   errored on the old code. Checked in headless Chrome on 2026-11-04 (local, no run id): under the CSP marked loaded with its SRI, a brief rendered with code spans and a table,
   and `<img onerror>`, `<script>` and an inline `<b>` came out as text.
5. **`gen_tables.py`** (`registry_rows`): reads `engine_sites` and `config_keys` through `warscape.registry.load_from_config` with the game's `wsc.toml` (or the defaults and
   `core:<name>` when there is none, as for the null game); load errors are `INVALID` lines. The generated-file comment is unchanged (it names the JSONL, and changing it would change
   bytes); the header's `purpose:` and the tools row are updated. Failing first: `test_gen_tables.RegistryLoader.test_dir_storage_gives_the_same_tables_bytes_as_jsonl` failed on the
   old code (0 sites after `reg migrate engine_sites --to dir`). The null game's `tables.h` and ini are byte-identical (`gen_tables.py --check`: current).
6. **`doc_paths`** (`checks.doc_path_tokens`, `doc_path_found`, `stale_doc_paths`; `gates.gate_doc_paths`; `[docs] path_ignore`): every backticked token with a `/`, an extension or a
   trailing `/`, no placeholder characters and no scheme must be a tracked file or folder, from the root, the doc's folder or across `core/`, or be git-ignored. Failing first:
   `test_checks.DocPaths` errored on the old code (no `stale_doc_paths`).

## Evidence
- `python3 wsc.py gates` (full, local Windows, 2026-11-04, before the merge of `main`): 12 ok, 4 warn (doc_paths, hooks, ci_render's W23 bootstrap note, the tests' 5 skips), 0 failed;
  722 host tests passed. `gates --fast` and `policy --branch job/W28 --base origin/main` pass after the merge. CI: the draft pull request's run.
- napoleon-remastered, read-only (`main` 93047e6, defaults, `jobs/` and DECISIONS excluded as in the core): **56 misses** in 29 living docs (29 of them in `proxy/README.md`).
  Its `wsc.toml` is on core 0.10.0 and still has `[jobs] hooks`, so the gate itself cannot run there before its pin bump.

## Paths item 6 flagged in the core and what happened
- 730 misses on the first rule: 627 in `jobs/**` (briefs, reports and reviews name the game paths and branches of their day) and 9 in `docs/DECISIONS.md` (append only).
  Both are records, so the gate skips the jobs folder and the decisions file.
- One tightening of the token rule (a path has an extension or a trailing `/`) dropped `origin/main`, `job/W28`, `actions/cache` and the like.
- Nine `path_ignore` entries in the core's `wsc.toml`: `plan/`, `brief/`, `meta/`, `job/`, `release/` (branch prefixes), `core/` (a game's submodule), `reports/`, `runs/`, `records/`.
  A git-ignored path (`_scratch/registries/`) passes.
- The 71 left are deliberate references to other repos, not stale core paths: the old-path column of the `discovery/README.md` move table (`discovery/core/*.py`), game paths in
  `docs/CONSUMING.md`, `docs/BACKLOG.md` and the proxy docs (`tools/gates/pipeline.py`, `viewer/pins.json`, `proxy/README.md`), and empire paths. None was renamed or gone in the
  core, so no doc was edited for them.

## Deviations
- **`doc_paths` ships as a warning** (kill criterion): telling the 71 other-repo references from stale ones would take more than 15 `path_ignore` entries. B87 tracks the error form.
- **`doc_paths` skips the jobs folder and the decisions file**, which are living docs for `verified_dates`: a job's docs and the append-only decisions file record their day, and the
  decisions file cannot be edited to fix a miss.
- **VERSION 0.34.0, not 0.31.0**: open branches carry 0.31.0 (W15), 0.32.0 (W16) and 0.33.0 (W25); W29 has not merged. **C28**: `policy` wants the base's last row plus one;
  W15 and W25 also carry C28, so whichever merges later renumbers.
- `verified_dates` became case-insensitive for the word "verified": without it the brief's "VERIFIED on PC" case could not be flagged. No core line changed state.
- `docs/CONSUMING.md` is 29,049 bytes with the new section; "Registry storage and views (0.6.0, opt-in)" moved to `CONSUMING_OPTIONS.md` with a one-line link to keep it under 29,700.

## The consumer's part (at a game's pin bump)
(a) `verified_dates` may flag old lines and `doc_paths` lists missing paths: fix each with the true date or path, mark historical ones `(was <path>)`, list non-paths in
`[docs] path_ignore`; (b) a `[gates] skip` entry needs a decision id (`gate:<id>`); (c) napoleon's `test_repo_rules.silenced` stays its own and needs its skip under a
decision id; (d) `gen_tables.py` now loads the game's whole `wsc.toml`, so that file must load with the new core (napoleon's `[jobs] hooks` goes first, as for every verb).

## Open questions
1. **`doc_paths` as an error** (B87): recommended, a per-line `(game)` / `(empire)` marker or a `[docs] path_repos` table, then error. Alternative: keep the warning.
2. **Skip syntax**: built as recommended, `"gate:decision-id"` strings.
3. **CSP**: built as recommended (hashes computed per page); no fallback was needed.

## Fix round 1
Review round 1 (`jobs/W28/review.md`, verdict "merge after fixes"), fixed on 2026-11-04 by session f50072b0.

- **should-fix 3, ignored paths reported** (a567652): the cause was not Windows or the worktree. One `../` token in the batch makes
  `git check-ignore --stdin` exit 128 for every name, and the gate read any code but 0 or 1 as "nothing is ignored". `../` tokens (and a bare `../`)
  are now dropped before the call, and a failed or unrunnable call is a gate error naming the exit code and stderr. The loud error caught one more
  case during this round (a bare `../` in new CONSUMING text) before it was handled. Host test: `test_gatemods.DocPathsGate`, failed on the old code
  (the `_scratch/registries/tools.md` line was reported).
- **should-fix 1, `doc_paths` is an error** (94cf63d): the gate returns `error`. The 67 misses left after the fix above, cleared:
  14 new `[docs] path_ignore` entries in the core's `wsc.toml` (10 prefix globs or folders: `discovery/core/**`, `tools/**`, `docs/plans/**`,
  `harness/runs/**`, `viewer/**`, `upscale/**`, `shaders/`, `rml_mod/**`, `perf_mod/**`, `docs/learnings/**`; exact files: `harness/README.md`,
  `proxy/README.md`, `docs/CI_FAILURES.md`; and `ctx.root/core/`, a Python expression), commented by owner; stale lines fixed (CONSUMING.md's
  `registries/jobs.md` is now "a committed jobs view", PROXY_HARNESS.md names `proxy/tests/null_game/proxy/tests/test_null_adapter.cpp`, BACKLOG.md
  names empire's real `docs/learnings/LEARNINGS_HARNESS.md`, checked in the empire-remastered checkout read-only); a game's seven test files
  (`test_repo_rules.py` and the like) are named bare where the line already says whose they are, instead of seven exact entries; and job folders are
  records at any depth, so the fixture game's `jobs/F1/brief.md` and `F2` (which name the report their job will write) are not checked. No line
  marker was added: the ignore list stayed short. Host test: `test_gatemods.DocPathsGate.test_a_missing_path_is_an_error_and_a_nested_jobs_folder_is_a_record`.
  The gate docstring, README "Gates", CONSUMING's "Gate changes in 0.35.0" and C30 say error; B87 is removed (built). This supersedes the
  "ships as a warning" deviation above.
- **should-fix 2, decision number** (a3791ea, the merge of `main` at 60ba80e): main now has C28 (W25) and C29 (W33), so this job's row is **C30**;
  plan PR #87 also carries a C28 and renumbers when it lands. VERSION **0.35.0**: main is at 0.34.0 (W33 and W16), and W29 (C27, job branches
  stop editing VERSION) has not merged.
- **later, napoleon's 56 misses**: added to CONSUMING's pin-bump steps (94cf63d): clear them in the pin-bump branch, or skip the gate there under a
  decision id while it does.
- **Found while merging:** the line merge of `registries/tools.jsonl` kept two rows for `proxy.tools.fetch_ui`, `gen_tables` and `layout`; rows
  merged by id against the merge base 79ebbb4 (f6d87d2). `docs/CONSUMING.md` was 31,527 bytes on `main` (W16 and W33; main's `doc_size` gate and
  its `test_cli` copy are what is red there, issues #95 and #96): the 0.24.0 hooks section and the 0.26.0 base-judged policy steps moved to
  `CONSUMING_OPTIONS.md` with a one-line link each (94cf63d), 29,967 bytes now. Whoever fixes main's copy first, the other merge keeps one move.

Evidence (local Windows, 2026-11-04, this worktree at 94cf63d): `python3 wsc.py gates` (full): 14 ok, 1 warn (ci_render's W23 bootstrap note), 1 failed:
650 host tests, 649 passed, 1 skipped; the one failure was `test_jobs.ThisRepo.test_the_queue_passes_jobs_check` asking for this row to be `review` once
this section existed, and it passes after `wsc reg set jobs W28 status=review`. `gates --fast` then: 14 ok, 1 warn, 0 failed; `doc_paths` ok over 17 living
docs, `doc_size` ok over 111. CI: the draft pull request's run.

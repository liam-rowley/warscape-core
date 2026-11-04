# W28: Small gate fixes: dates, strict JSON, skipped gates, the serve page, stale doc paths

Model: Sonnet, reason: none needed (Sonnet is the default). Six small, independent fixes in `warscape/`, `proxy/tools/gen_tables.py` and the host tests, plus a size check on one doc; no DLL, no PC.
Budget about 110 tool calls (about 18 per fix, 15 for docs, gates and the report); at the cap, stop, commit the fixes that are green, and list in the report what is left.

## What
Audit 2026-11-03 (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`, read-only; `git show origin/main:docs/audits/AUDIT_2026-11-03.md` in that clone): the
rule rows "verified claims carry a date", "strict JSON" and "gates not silenced", the `--serve` row, the `gen_tables.py:177` row and R11's stale-path check.
W23 (base-judged policy) and W12 (guards, B24 as a host test) are merged (checked 2026-11-04 on `origin/main` ea98a96); line numbers below are from that
commit, so re-find each by name. Build in this order, commit after each; each fix is shown failing on a fixture first (one line each in the report).

1. **`verified_dates`: a date or a run id, nothing looser** (`warscape/checks.py` `VD_DATED`, line 101; used in `undated_verified`, lines 125, 137, 148).
   Today `VD_DATED` also accepts `\b\d{1,2}-\d{2}\b`, `session`, `\.md\)` and `\bv\d`, so "VERIFIED on PC", "verified in session" and "verified 3-10 times" pass.
   - Accept only: an ISO date `\d{4}-\d\d-\d\d`, a compact date `20\d{6}` (run folders such as `20261104_a`), and a path under `reports/`, `runs/`, `records/` (as today).
     Drop the three loose alternatives. A line that links a dated record keeps passing because the link text or target carries the date; a bare `(foo.md)` no longer does.
   - Run the gate over the core and the fixture game: fix every living-doc line the stricter rule newly flags by adding the date or run id it lacks (the true one, from `git log` or
     a report), never by rewording "verified" away. List the lines fixed in the report: games meet the same list at their pin bump.
   - Tests (`tests/test_checks.py`, beside the `undated_verified` cases near lines 68-72): "VERIFIED on PC", "verified in session", "verified 3-10 times" and "verified (see x.md)"
     are flagged; "verified 2026-11-04", "verified, run 20261104_a" and a `reports/...` path are not.
2. **Strict JSON refuses duplicate keys** (`warscape/checks.py` `strict_json_error`, lines 43-59; `warscape/registry.py` `_load` line 200 and `_load_dir` line 223, both
   `json.loads(..., parse_constant=_boom)`; also `warscape/jobq.py` lines 62 and 173 and `proxy/tools/gen_tables.py` `jsonl` and the `identity.json` read, which read repo data without it).
   - One `object_pairs_hook` in `checks.py` that raises `ValueError("duplicate key 'k'")`; `registry.py` imports it (one implementation, beside its `_boom`). `strict_json_error` and both registry
     loaders pass it; `jobq.py` and `gen_tables.py` use it for repo data (grep `json.loads` and leave `gh` output alone).
   - Tests: `tests/test_checks.py` (`{"a":1,"a":2}` refused, nested too, JSON Lines per line with its line number); `tests/test_registry.py` (a jsonl row and a dir-storage file with a
     duplicate key fail `load`/`check` naming the file); the `json` gate on a fixture file.
3. **`[gates] skip` is never silent** (`warscape/gates.py` `selected`, lines 360-363, and `run`; config in `warscape/repo.py` `DEFAULTS` line 41).
   - Each skipped gate prints one warn line in the `gates` report: `skipped <gate>: <decision id>`. A skip entry is `"<gate>:<decision id>"` (recommendation: the string form, so a bare name
     is the only breaking case); a skip with no decision id is a config error that names the fix, and the id must exist in the repo's decisions file (the one `policy` reads for append-only).
   - A skippable gate that contains a rule (napoleon's `test_repo_rules.silenced` sits inside the skippable `tests` gate) is out of the core's reach: the guard here is only that a skip is
     visible and has a decision. Say so in the docs (item 7) and in the report, for napoleon to carry its own skip under a decision id.
   - Tests (`tests/test_gatemods.py` or `tests/test_cli.py`): a skip with an id gives a warn line and the run passes; a bare name errors; an unknown id errors; `--only <skipped gate>` still runs it.
4. **The `jobs view --serve` page** (`warscape/jobq.py` `render_view`, lines 716-850: the script tag at 823 and `div.innerHTML = marked.parse(...)` at 833, on a page that also holds `SERVE.token`).
   - Pin the CDN script with Subresource Integrity: `integrity="sha384-..."` and `crossorigin="anonymous"` on the existing marked 12.0.2 URL (compute the hash from the file at that URL once, keep it in a
     constant with a comment naming how it was made, and a test that the tag carries it).
   - Escape raw HTML in the rendered output with a marked renderer `html()` override that returns the escaped text (recommendation: so code spans and tables still render; the alternative is escaping
     `<`, `>`, `&` in the source before `marked.parse`). Add a `<meta http-equiv="Content-Security-Policy">` allowing the one script origin plus the page's own inline script (by hash), `connect-src 'self'`.
   - Tests (`tests/test_jobs.py`): the rendered HTML has the `integrity` attribute; a brief containing `<img src=x onerror=alert(1)>` and `<script>` reaches the page only as escaped text (check what the
     page ships and the override in its script); the token appears only in the `SERVE` JSON.
5. **`gen_tables.py` reads the registries through the loader** (`proxy/tools/gen_tables.py` lines 25-29 `jsonl` and 321-322; it reads `registries/engine_sites.jsonl` and `config_keys.jsonl` by path, so
   `wsc reg migrate engine_sites --to dir` breaks it and `[registries]` is ignored).
   - Read both through the registry loader (`warscape.registry.load_from_config(cfg, root, only=...)`; copy an existing caller, `grep load_from_config`), then the existing sort. `identity.json` is not a
     registry and stays a plain read (through item 2's strict hook). Update the header and the generated-file comment only where they name the path, and keep the generated bytes identical for jsonl
     storage (a game's regenerate-and-diff gate must stay green).
   - Tests (`tests/test_gen_tables.py`, near line 108): run the tool on the null game with `engine_sites` migrated to dir storage and get the same `tables.h` bytes as with jsonl.
6. **Stale doc paths** (R11; B24 generalised; W12 shipped only `tests/test_moved_tools.py` `NoOldLayoutPaths`, a fixed list of old-layout names).
   - A gate `doc_paths` (`warscape/gates.py` in `GATES`, `warscape/checks.py` `stale_doc_paths`) over the living docs (`checks.living_docs`, the set `verified_dates` uses): every backtick token that looks like a
     repo path (contains `/`, no spaces, none of `<*{$%~`, no scheme, no drive letter, not on a configured `[docs] path_ignore` list) must exist (git-tracked file or a directory prefix of one), resolved from the
     repo root, the doc's own folder, or with a `core/` prefix (the game's view). A miss fails with `<doc>:<line>: path not found: <token>`; a line carrying `(was <path>)` or `(moved)`, and fenced blocks, are exempt.
   - Run it over the core's docs and fix every miss (renamed: point at the new path; gone: drop the sentence). Leave `NoOldLayoutPaths` alone: it also checks non-doc files.
   - Tests (`tests/test_checks.py`): a stale token is flagged with its line; an existing file, a directory, a `core/`-prefixed path, an ignored token and a placeholder (`<id>`, `*`) are not.
   - Run it read-only against a napoleon-remastered clone (`--root`; write nothing there) and put the miss count in the report (the audit's R11 cites `PLAN.md:101`-era drift and `CI_FAILURES.md:16`).
7. **`docs/CONSUMING.md` size and the docs.** It is 28,706 bytes on `origin/main` against the 30 KiB cap (30,720): about 2 KB of headroom. Answer: **do not trim it for its own sake** (plan commit 8d43469 just moved
   "The options compared" out; a second move risks another red `main`), but do not spend the headroom either. Put each behaviour in the doc that owns it (README "Gates" for items 1, 2, 3, 6; the
   `jobs` part of `CONSUMING.md` for item 4's pin and CSP) and add one short `CONSUMING.md` section of at most 12 lines ("Gate changes in 0.31.0, W28": the skip syntax, `doc_paths` and `path_ignore`,
   the stricter `verified_dates`, the pin-bump steps). Check `wc -c docs/CONSUMING.md` before the last commit: above 29,700 bytes, move the oldest dated section that is least read ("Registry storage and
   views (0.6.0, opt-in)" or similar) to `CONSUMING_OPTIONS.md`, leaving a one-line link.

## Scope: files this job touches
`warscape/checks.py`, `warscape/registry.py`, `warscape/gates.py`, `warscape/jobq.py`, `warscape/repo.py`, `proxy/tools/gen_tables.py` (its header and its tools row), `wsc.toml`, the living docs items 1 and 6
correct, `tests/test_checks.py`, `tests/test_registry.py`, `tests/test_jobs.py`, `tests/test_gatemods.py` (or `test_cli.py`), `tests/test_gen_tables.py`, `README.md`, `docs/CONSUMING.md`,
`docs/CONSUMING_OPTIONS.md` (only if item 7 needs it), `docs/DECISIONS.md` (one row), `docs/BACKLOG.md`, `registries/tools.jsonl`, `VERSION`. Not touched: `proxy/src/**` and `proxy/tools/build.sh` (DLL inputs),
`warscape/policy.py` (W23's), `harness/*`. Branch `job/W28`.

## Acceptance
- `python3 wsc.py gates` green locally and in CI on `ubuntu-latest` and `windows-latest`; each fix shown failing on a fixture before it passes (one line each in the report).
- The report lists the living-doc lines item 1 newly flagged and how each was dated, the paths item 6 flagged and what happened to each, and the napoleon read-only count for item 6.
- `VERSION` bumped to the next free minor (0.31.0 unless `origin/main` or an open `job/*` branch took it: re-read both before the last commit; the second to merge takes the next number and merges `main`).
- A DECISIONS row with the next free `C<n>` (C28 if free; other briefs and builds in flight may take it: re-check after merging `main`).

## The consumer's part (not here)
At a game's pin bump: (a) `verified_dates` and `doc_paths` may flag old lines: fix them with the true date or path; (b) a `[gates] skip` entry needs a decision id (`gate:<id>`);
(c) napoleon's `test_repo_rules.silenced` stays its own and needs its skip under a decision id. Say this in the report.

## Open questions (recommendation for each)
1. **Skip syntax.** Recommended: `"gate:decision-id"` strings. Alternative: a `[gates.skip]` table, rejected as a breaking change for no gain.
2. **`doc_paths` as an error or a warn.** Recommended: error (the core's docs are small and fixed in this job); a game may skip it with a decision id while it clears its misses.
3. **CSP on the serve page.** Recommended: one meta tag with the inline script allowed by hash, recomputed in a test; if that proves brittle, ship SRI and the escaping and report the CSP as open.
4. **File overlap.** Other briefs and builds in flight (W15, W16, W25, W26, W27, W29, W33, W35) may edit `README.md`, `docs/CONSUMING.md`, `docs/DECISIONS.md`, `docs/BACKLOG.md`, `VERSION`,
   `gates.py` and `repo.py`: separate hunks; merge `main` in (never rebase), resolve by hand, take the next free `C<n>`.

## Kill criteria
- Item 1 flags more than about 40 living-doc lines in the core: loosen nothing; fix the first 40 and report the rest as a follow-up row.
- Item 2: a committed registry or JSON file in the core, the fixture game or the null game already holds a duplicate key: that is the finding; fix the data, report it, never relax the check.
- Item 4: the SRI hash of the marked URL cannot be computed (no network) after 3 calls: ship the CSP and the escaping, and report SRI as open.
- Item 5 changes a byte of the generated `tables.h` or the default ini for the null game: stop and report; the output must stay identical.
- Item 6's gate needs more than about 15 `path_ignore` entries after one tightening of the token rule: ship it as a `warn` and report.
- CI red after three fix attempts for a cause in this change: stop and report.

## Finish
Report in `jobs/W28/report.md` (each fix: the fixture that failed, the fix, the tests; the lines and paths newly flagged; the napoleon count; deviations; open questions), then
`wsc reg set jobs W28 status=review report=jobs/W28/report.md` (`python3 wsc.py`). Liam tags the core after the merge; stop after the PR.

# W43 report: Decisions and backlog rows as one file per row

Decisions and core tools are now one file per row, new decision ids are minted so two branches cannot share one, and backlog items have a home as `later` job rows with a checked importer. The rows of the two backlog files have not moved yet and `docs/DECISIONS.md` is frozen, not deleted: the rules force both into follow-ups after this merge (Open questions 1 and 2 give the steps). Every decision and tool row is carried, checked by field value.

Usage: 50 tool calls; models: opus; 1 session, one build session, counted by hand from the claim, 2026-11-05

## What was built
- **Decisions:** `schemas/decisions.schema.json`, `registries/decisions/` (41 imported rows plus this job's `C261105-bbfb`), `[policy] decisions = "registry:decisions"`. In `warscape/policy.py`, `decision_row_problems` is the append-only rule as a file rule, and `added_decision_files` keeps the `added_decision_rows` fact shape, so rule F and game modules read it unchanged. The Markdown code path is untouched.
- **Ids:** `wsc reg add decisions --mint` (`mint_id` in `warscape/registry.py`) draws `<prefix><yymmdd>-<4 hex>`. `policy` refuses a new number.
- **Importer:** `wsc reg migrate <registry> --from-md FILE [--check]`, compared by field value (`Registry.md_problems`). A rerun adds only what is new, which is how C40 and C41 came in after they merged to the table.
- **Guard:** `[policy] decisions_retired`: while the file exists, the `registries` gate fails on a row the row files lack, so a stale branch's Markdown row cannot vanish. `skips` finds a decision id through the row files.
- **Tools:** `wsc reg migrate tools --to dir`, napoleon's mechanism (`[storage] dir`), no second one: 91 rows before and after, compared as parsed rows, identical. `registries/tools.jsonl` is gone.
- **`later`:** a job status in `schemas/jobs.schema.json`, with `backlog_id` and `area`. `jobs next`, `jobs review` and the autopilot ignore it; `jobs view` has a Later lane; `jobs check` needs no semver or brief for it and refuses one with a brief; `status=needs_brief` promotes it. `wsc jobs later --from-md FILE [--area NAME] [--check]` moves a backlog table.
- **`wsc find`:** searches `backlog_id` and `decision`, and an exact id or `backlog_id` now comes before rows that only cite it.
- **Views:** `x-view` gained `sort` and `full`, used by decisions only, so every other view, committed ones in a game included, renders byte for byte as before.
- **Docs:** `CLAUDE.md`, `README.md`, `docs/REVIEW.md` (Later items), `docs/CONSUMING.md`, `docs/CONSUMING_OPTIONS.md` (the opt-in), `docs/UPGRADING.md`.

## Evidence
Tests: `tests/test_row_files.py` (44 tests, committed red at `5001ba0`: it failed on import), the two `test_w43_*` cases in `tests/test_policy_base.py`, and `test_bypass_4` rewritten for row files, all through the real judge. Full `python3 wsc.py gates` on this Windows PC before the last two merges of `origin/main`: 15 ok, 1 warn (5 skips: capstone not installed, no POSIX symlinks), 1183 host tests. Branch CI: gates run 42125497108 at `519eae8` failed on `gates (windows-latest)` only (deviation 7); ubuntu, `proxy` and `harness-windows` passed. The run after the fix is in the pull request's checks (`policy` skips drafts).

The row counts at the final merge (`origin/main` 34e5f66):
```
docs/DECISIONS.md: 41 rows, every one in registries/decisions
tools before 91 after 91 identical True
```
`find C36` prints the row. The backlog move on a scratch export of the branch, before the last merges (W42 has since removed B99, so 48 + 15 = 63 now):
```
jobs later: docs/BACKLOG.md: 49 rows, every one a job row
jobs later: docs/BACKLOG_HARNESS.md: 15 rows, every one a job row
jobs check: 107 rows, ok
```
`find B95` there printed W43 first, as its description cites B95; that is why the exact-match ranking went in, and `test_find_resolves_the_old_number_ahead_of_a_row_that_cites_it` holds it.

The rule through the real verb, on throwaway local branches judged against `job/W43` (`origin/main` still has the old rules):
```
--- edit, no replacing row
policy: plan/w43-demo-edit: REFUSED (1 files changed)
policy: registries/decisions is append only: C36.json was changed, moved or removed (a reversal is a new row whose `replaces` names the old one)
exit 1
--- edit, with a replacing row
policy: plan/w43-demo-both: REFUSED (2 files changed)
policy: registries/decisions is append only: C36.json was changed, moved or removed (a reversal is a new row whose `replaces` names the old one)
exit 1
--- two branches, one base
policy: plan/w43-demo-one: ok (1 files changed)
policy: plan/w43-demo-two: ok (1 files changed)
merge exit 0
```
A consumer is unaffected: `tests/fixture_game` and the Markdown cases in `tests/test_policy.py` pass with no edit.

## Branches in flight
Open pull requests when this was written: this one only (#128 and #129 merged during the build; C41 came from #129). Old branches that still change the files, none with a pull request, include `plan/pc-deploy-guard-and-capture-2026-11-05`, `plan/review-followups-2026-11-05`, `plan/w36-later` and `plan/w31-review-later`. A branch that adds a Markdown decision row after this merges fails the `registries` gate; one that edits `registries/tools.jsonl` meets a modify/delete conflict. Both are loud.

## Deviations from the brief, and why
1. **Scope, after the brief merged: none.** The tools move and the `later` scope were both put in the brief before #125 merged, on Liam's instructions relayed by the napoleon session on 2026-11-05 (the messages "Scope addition to W43" and "Decision from Liam"). That session also confirmed the follow-up order below.
2. **The brief says B19 and B98 hold unescaped pipes; that was wrong.** B98's pipe is escaped (`\|`), and it is carried as a plain `|`. B19 has three cells: its table row has no Raised cell, so its row has no `Raised:` part. No text is lost in either.
3. **The build landed as one code commit, not one per step** (`9aeb4bb`), against step 3. The tests were red first as asked.
4. **`--mint` is a flag on `reg add`** as the brief says, and only the `[policy] decisions` registry takes it, as backlog ids were dropped from scope. `backlog`, `backlog_prefix` and the `registries/backlog/` folder are not built.
5. **Added beyond the brief:** the exact-id ranking and `decision` as a search field, as `find C36` printed only the date and `find B95` ranked a citing row first.
6. **The `--check` of the scratch `jobs later` run predates the last merges.** The follow-up re-runs it at its own merge.
7. **`[tests] timeout_s = 1080` in `wsc.toml`, not in the brief.** Run 42125497108 failed with `tests: timed out after 600 s` on Windows, no test failing. W42 raised the job limit to 20 minutes, but the gate's own 600 s default still bound, and Windows was already at about 9.5 minutes (9:43 on #125), so this job's tests tipped it over. 1080 s stays under the job limit. The Windows slowness itself is W42's open question 1, still open.
8. **Usage is counted by hand** (the core has no transcripts): an estimate, from the claim on.

## Open questions
1. **Follow-up 1: move the backlog (`plan/`, straight after this merges).** A job branch may change only its own row, and `later` was not in the base's schema, so this could not run here. Both files stay intact on `main` until then. Row ids start at the next free `W<n>`; re-count at that merge.
   ```
   git pull
   git switch -c plan/backlog-to-later-rows origin/main
   python3 wsc.py jobs later --from-md docs/BACKLOG.md --area core
   python3 wsc.py jobs later --from-md docs/BACKLOG_HARNESS.md --area harness
   python3 wsc.py jobs later --from-md docs/BACKLOG.md --check
   python3 wsc.py jobs later --from-md docs/BACKLOG_HARNESS.md --check
   git rm docs/BACKLOG.md docs/BACKLOG_HARNESS.md
   python3 wsc.py gates --fast
   python3 wsc.py policy --branch plan/backlog-to-later-rows --base origin/main
   ```
   Both `--check` runs must exit 0 first, and the printed counts must match `grep -c '^| B'` on each file. Commit with the `Claude-Session` trailer, then open the pull request.
2. **Follow-up 2: delete `docs/DECISIONS.md` (`meta/`, Liam reviews it).** The base's rules refused it here, and `wsc.toml` is outside the `plan` globs.
   ```
   git switch -c meta/retire-decisions-md origin/main
   python3 wsc.py reg migrate decisions --from-md docs/DECISIONS.md --check
   git rm docs/DECISIONS.md
   # wsc.toml: delete the `decisions_retired = "docs/DECISIONS.md"` line
   python3 wsc.py gates --fast
   python3 wsc.py policy --branch meta/retire-decisions-md --base origin/main
   ```
3. **Should a `replaces` row mark the old row in the view?** Not built: no row replaces another yet. Recommended: add it with the first real reversal.
4. **`later` rows carry `sonnet` and phase 1 as placeholders,** as both are required. Set them when a row is promoted and briefed.

## What napoleon must do
Nothing is forced. It stays on `docs/DECISIONS.md` through its pin bump; it has no backlog file. Opting in to decision rows is two pull requests after that bump (`docs/CONSUMING_OPTIONS.md`, "Decisions as one file per row"), and its D rows keep their numbers.

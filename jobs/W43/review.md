# W43 review

## Round 1 (2026-11-06, branch job/W43 at 8df4430)

**Verdict: merge after fixes.**

The core of the job is sound: decision rows, minted ids, tools as row files, `later` rows and both importers do what the brief asks, and I found no way to change a decision row and pass. One stated decision is not met: the guard for the frozen `docs/DECISIONS.md` (brief decision 11) does not stop the branch it exists for. The report's follow-up 2 also fails as written.

### What I ran
- `python3 wsc.py gates` on this PC at 8df4430: 14 ok, 2 warn, 0 failed, 1193 host tests, 5 skipped. The warnings are the worktree's `hooks` path and the capstone and POSIX skips.
- `python3 wsc.py policy --branch job/W43 --base origin/main`: refused only for the missing review and the row not yet `done`, as the brief expects. The note names the changed rule files; the new rules are proven by host tests (C24).
- CI: gates run 42127636682 at 8df4430 is green, all jobs. `policy` skipped, as the pull request is a draft.
- Tool rows, compared with `origin/main` by parsed row: 91 and 91, same ids. Only `wsc.jobs` differs, in its `usage`, because the verb gained `jobs later`.
- Decisions: `--check` 41 rows, exit 0. `find C36` prints the row.
- Follow-up 1, run on a throwaway branch: 48 + 15 = 63 rows (W48 to W110), both `--check` exit 0, no duplicate B number, no table row missed by the importer, `gates --fast` green, `policy` ok as a `plan/` branch judged by this head's rules, `find B95` ranks W85 first, `jobs next` skips them.
- Scope: `tests/test_policy.py`, `tests/fixture_game`, `ci/`, `VERSION`, `harness/` and `proxy/` unchanged, and no workflow file. `test_bypass_4` was rewritten as the brief expected and is not weakened: it still proves a head's `decisions = ""` does not switch the rule off.

### Risk-first reading
I picked `warscape/policy.py` `decision_row_problems` and the judge's path to it, as a hole there lets a decision change on `main`, and then the window guard in `warscape/gates.py`. By reading the code and its tests, not by a run of my own, I checked a change, a delete and a rename, a stray or nested file, a head that empties the key, and every branch kind (the rule runs before the kind is read). All are refused, and the `old == new` shortcut only skips a file the head has exactly as the base has it. Natural sort cannot compare a number with text: `re.split` keeps strings and numbers at alternating positions.

### Blocker
1. **The frozen file's guard does not reach a stale branch, so a stale Markdown row merges and turns `main` red.** `warscape/gates.py:63-65`; `warscape/policy.py:192`; claimed at `jobs/W43/report.md:52` and `docs/DECISIONS.md:4`.
   The guard is in the `registries` gate, which reads the head's `wsc.toml`. CI runs gates on push only, on the branch head (`.github/workflows/gates.yml`), and `main` does not require up-to-date branches (`strict_required_status_checks_policy` is false). A branch cut before this merge has neither the key nor the code, so its gate passes. `policy` judges with the base's rules, but in registry mode it never looks at the Markdown file, and `docs/*` is in the `plan` globs. Since C40 such a branch merges itself on green. This is the failure the Goal names (each branch passes alone, `main` goes red), and the branches exist: `plan/review-followups-2026-11-05`, `plan/w36-later`, `plan/w31-review-later` and `plan/pc-deploy-guard-and-capture-2026-11-05`.
   To see it fail, from `origin/main` add a `| C42 | ... |` row to `docs/DECISIONS.md` and commit:
   ```
   gates --fast on that head:  ok registries, 14 ok, 0 failed
   policy --base <W43 head>:   policy: plan/stale-md-row: ok (1 files changed)
   after merging it into W43:  FAIL registries, docs/DECISIONS.md: row C42 has no row in registries/decisions
   ```
   Fix: carry `decisions_retired` into `settings` and have `check` refuse, on every branch kind, a head that still has that file with table rows different from the base's. Prose and deleting the file stay allowed, as follow-up 2 needs. That rule is judged with the base's code, so it reaches a stale head. Add a host test through the real judge with the head's `wsc.toml` on the old value, and correct the report's sentence.

### Should-fix
2. **Follow-up 2 fails as written.** `CLAUDE.md:50`, `jobs/W43/report.md:78-86`. After `git rm docs/DECISIONS.md`, `gates --fast` gives `FAIL doc_paths: CLAUDE.md:50: path not found: docs/DECISIONS.md`. That line means napoleon's file. Reword it here (for example "napoleon-remastered decision D15"), or the follow-up's listed diff is incomplete. `policy` itself says ok on that branch.
3. **A decision row, now a `plan/` change, is not paperwork to CI.** `wsc.toml:98`. W43 added `registries/decisions/*` to `[policy] plan` but not to `gates_windows`, whose comment says it is the plan set. Each plan branch that adds a row pays for the Windows gates, near the 18-minute limit this job just raised. Add `registries/decisions/` to the exclusion; `tests/test_ci.py` has the case table.
4. **The report's evidence is out of date.** `jobs/W43/report.md:19,21`. The brief asks for the branch's run id: the report names only the red run and points at the pull request; the green one is 42127636682. "The final merge (`origin/main` 34e5f66)" is not the final one: d533581 merged 6e0263e. `:24` says tools are identical; say that `wsc.jobs` gained its `usage` text.

### Later
5. `replaces` that is not a list crashes the rule. `warscape/policy.py:225`: `"replaces": 5` gives `TypeError` and `the base's rules gave no verdict`. It fails closed, so nothing gets through, but the message does not name the row. Check it is a list of strings in `decision_row_errors`.
6. A frozen-file row with an extra pipe shows as `gate crashed: RegistryError` (`warscape/registry.py:566`, through `md_problems`). Also closed, and the text is right; `md_problems` could return it as a problem.
7. Long `later` row titles: at least eight run past 75 characters (B58, B64, B68, B71, B73, B78, B89, B31), as the title is the whole bold lead. Nothing is lost, as the description holds the text. Tidy them when a row is promoted.

These three go in `later` rows once the status is on `main` (the new `docs/REVIEW.md` wording); they need no action on this branch.

### Report deviations
Deviations 1 to 8 are named and reasoned, and I accept them, including `[tests] timeout_s` (the reason is in CI run 42125497108) and the correction on B19 and B98, which I checked against the importer's output. The `Usage:` line is hand-counted, as deviation 8 says; I could not verify it.

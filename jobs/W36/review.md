# W36 review

## Round 1 (2026-11-05, branch job/W36 at f4a1f18)

**Verdict: merge.**

No blockers and no should-fix items. All three decisions are built. The one large change from the brief, decision 1 warning instead of refusing, is the brief's own kill criterion, and it holds up when the scan is re-run independently. Liam should note what that means: the forged-status residual is narrowed, not closed, and no row yet exists to harden it (see "For Liam").

### Machines
- `python3 wsc.py gates` (full, 2026-11-05, this head): 14 ok, 2 warn, 0 failed; 999 host tests passed, 5 skipped. The report's 15 ok and 1 warn differs by the `hooks` warn, which is this review worktree's absolute `core.hooksPath`, not the branch. The `tests` warn is the same 5 skips the report names.
- `python3 wsc.py policy --branch job/W36 --base origin/main` before this review: refused only for the missing `review.md` and the row not being `done`, with the rule-change note. The branch changes the rules, so its new rules are proven by its host tests, not by this run (C24).
- `wsc jobs review`: all 9 checks on f4a1f18 passed or were skipped. The `policy` check has been skipped on every draft run, so this merge gives it its first real run.

### Claims against evidence
- **The scan (the claim the deviation rests on).** The builder left no script or output (deviation 7, where the brief asked for the run folder), so I re-ran it through the GitHub API, read only: for each merged `job/*` pull request, its files, then its own brief at the merge commit's first parent.
  - warscape-core: 32 merged, 11 touch `workflow_paths`, 3 would be refused: W2, W29, W37, the report's three. The extra merged branch is W35, merged since its count, and it names its files.
  - napoleon-remastered: 65 merged, 19 touch, 11 would be refused: the report's ten plus J64 (#192), which merged on 2026-11-05, after the scan's pin 0c5c255 (2026-11-04).
  - Total 14 today against the report's 13, on the same method. Either is past the limit of 3. Every pull request targeted `main`, as the report says. The per-job reasons I spot-checked agree (J42, J62, W29, W37, J79).
- **Red, then green.** `0108235` changes only the three test files and `9863433` the code. Run at `0108235`: `test_trailer` 42 failures, `test_policy` 7 failures and 1 error, `test_policy_base -k w36` 5 failures and 2 errors of 8, as reported. All 8 pass at this head.
- **CI ids.** `gates` run 41933842361 is success on d602a60; run 41931100907 is success on fcc67bf at attempt 2; `policy` run 41933846332 is skipped on d602a60. All as reported.
- **Deviation 2 (no `VERSION` bump).** `warscape/release.py` `plan`: with `VERSION` equal to the last tag v0.38.0 and W36 `done` at `semver: minor`, it returns `release` at `bump(max(T, V), minor)` = 0.39.0, so consumers still get a tag. I read the code path and did not run the release workflow. "Liam's instruction for this session" cannot be checked from the repo, but `policy` allows either below `semver_from` and the result is the same.
- **Napoleon's hook.** `tools/claude_hook.py:322` builds `'git commit ' + args`, which starts in command position, so the new match sees it. Nothing there imports `COMMIT`. It is the only caller outside the core in the repos on this PC.

### The brief
Every deliverable is present: `workflow_paths` and `bases` with type checks, in the core's and the fixture's `wsc.toml`; the docstring, tools row and docs; `JUDGE_API` still 1; no workflow changed, so no re-render. The report names all eight deviations with reasons. I accept them. Deviation 3 (command position) is a real change of behaviour, but the brief lists `echo git commit` as a no-commit, and the old regex only appeared to pass that case because the test had no session id.

### Risk-first reading
I picked `warscape/policy_base.py` `refuse_unlisted_base` and `judge`, and `warscape/policy.py` `workflow_warnings`, because a mistake there is a bypass or a blocked pull request for every consumer, and `warscape/trailer.py`, the one full rewrite.
- `judge`: the rule runs before the head is read, reads only the base, and an unresolved base still falls to `diff_base`'s refusal. A base with no `bases` key takes the default, and CI passes `origin/$BASE_REF` (`warscape/ci_render.py:155`). Every other caller uses `origin/main`, so nothing in the pipeline is newly refused.
- `workflow_warnings`: reads the brief through `base_file` only, so a brief edited on the head counts for nothing (`test_w36_a_brief_on_the_head_names_nothing`), and the base's config decides (`test_w36_the_heads_own_workflow_paths_do_not_silence_it`). It sits in the `job` arm with no early return ahead of it, so it runs even on a refused branch.
- `trailer.py`: I ran 69 commands of my own through `commit_lacks_trailer`. Every option in decision 2 and every no-commit case in the brief behaves as the brief says. The gaps are the later items below. All but one fail open, and that one is a false positive on a command nobody types. None reaches napoleon, which passes a canonical string.

### Findings
**Blocker:** none. **Should-fix:** none.

**Later:**
1. `warscape/trailer.py:26`: three real global options are unknown, so a commit behind them reads as no commit: `git --no-advice commit`, `git --no-lazy-fetch commit`, `git --attr-source=HEAD commit` (and the two-word form). All three run on git 2.55.0. The brief's list did not name them, so the job met its list, but the goal ("a hook does not have to normalise") is not quite reached. To see it: `commit_lacks_trailer("git --no-advice commit", "s")` returns False. Two entries in `FLAGS` and one each in `TAKES_NEXT` and `TAKES_EQUALS`.
2. `warscape/trailer.py:21`, `:25`: forms the old regex saw and the new match does not, beyond the two the report names (`xargs`, `sudo -u`): `timeout 60 git commit`, `nice git commit`, `time -p git commit`, `env -i git commit`, `VAR=$(foo bar) git commit`, and a nested `git -C $(dirname $(pwd)) commit` (`WORD` takes one level of `$(...)`). Same class as deviation 3, and each returns False. `timeout` and `nice` are the likely ones and cost a word each, though `timeout 60` also needs its argument skipped.
3. `warscape/trailer.py:69`: the docstring lists gitconfig aliases and path-qualified git as unseen but not wrappers, which C36 and the report do name. The next reader of the code gets the shorter list. Fix with item 2.
4. `warscape/trailer.py:46`: git ignores an alias that shadows a builtin, but this follows it: `git -c alias.status=commit status` returns True and runs no commit. Harmless (it asks for a trailer), and worth one test if the module is touched.
5. `warscape/trailer.py:25`: a line continuation ends the match: `git \<newline> commit` returns False. The old regex missed it too, so this is no regression.
6. `docs/REVIEW.md:49`: clearing the workflow warning is prose, so this is the "Repeats" case in `docs/REVIEW.md` step 5. A guard that needs no scan: refuse a `merge` round that does not name each unnamed workflow path. The 14 past branches would not count against it, because it asks the reviewer to speak, not the brief to have been written differently. Worth weighing when the hardening row is written.
7. As W27's review said of its scan: this scan was also not committed, and W36 is the second rule to need it. If the hardening row re-measures, it should be a host-tested tool. This round's own script is not committed either.

### For Liam
- **No row hardens the warning yet.** The kill criterion says to ask for one, and report open question 1 does; a job branch cannot add it. Until then a job can add a workflow posting a fake `policy` status if its reviewer ignores the warning.
- **Report open question 2 stands.** The base refusal is a verdict, not a stop: the workflow has already started with the base's privileges. `branches: [main]` on the trigger in `ci/policy.yml.in` would be the direct fix, and it is a `meta/` change.
- **Report open question 3.** `docs/CONSUMING.md` is 30671 bytes, 49 under the cap.
- **Report open question 4.** The flaky lock test's reasoning agrees with `harness/job.sh:204-214`. It needs its own row.

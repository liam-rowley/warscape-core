# W26 report: Job claim and autopilot: atomic claim, phase and needs_pc, red CI, stale worktrees

`wsc jobs next` now claims the job before it prints its steps: it pushes `origin/main` to a new `job/<id>` (`brief/<id>` for a brief) on
origin, and that push only creates the branch, it never moves one. So two terminals can no longer get the same job. Jobs are picked by
(phase, number). A `needs_pc` build is held back on a machine with no PC state folder (`[jobs] pc_state`, `WSC_PC_STATE`). The
autopilot starts a review only on a green head, starts a fix only once CI has finished, runs one `needs_pc` row at a time and prunes dead
worktree registrations on every tick. A new library module, `warscape/worktrees.py`, gives a game's `setup` verb the stale-worktree and
stray-`.git` warnings, and `wsc jobs worktrees [--prune]` prints the same. Built by session ed0f955b-6885-5035-b233-0a11a4c51d0c.

## What was built
- **Claim** (`warscape/jobq.py`): `claim`, `claim_argv`/`claim_line`, `fetch_main`, `next_claim`, `empty_claims`, `remote_heads` (now
  under `remote_branches`), `take_it`, and `steps`. `next_claim` fetches `main` only when there is something to claim. It pushes with
  `git push --porcelain --force-with-lease=refs/heads/<b>: origin origin/main:refs/heads/<b>` and reads the porcelain line for that ref:
  - `*` means claimed.
  - `=`, or `!` with `[rejected]`, means another session got there first. It re-reads the branches once and moves on, at most 5 times.
  - Anything else (`[remote rejected]`, no ref line, no origin, no `origin/main`) is exit 1 and nothing is claimed.

  `--id` claims too. `--peek` and `--offline` print the exact push and claim nothing. `build_steps(r, sha)` and `brief_steps(..., sha)`
  say "Claimed: job/<id> now exists on origin at <sha7>. Take it: git fetch origin job/<id>, git checkout -b job/<id> origin/job/<id>".
  The "push early" clause is gone.
- **Order and `needs_pc`**: `order_key` (phase, then number; an absent or non-int phase counts as 99) and `pc_absent()`, which reads
  `WSC_PC_STATE` at call time, expands `$VAR` and `~`, and tests the folder with `Path.is_dir()`. `not_ready('build')` uses it and so does
  `lane`, which puts such a row in "waiting" with the reason. `S.pc_state` is set by `configure_from`, so the signature of `not_ready` is
  unchanged. The key is added to `repo.py` `DEFAULTS['jobs']` (the loader's allowed-key list).
- **CI read**: `branch_ci(root, sha, offline, run)` returns `green|red|running|none|unknown` plus lines. `running` wins over a failure,
  and skipped and neutral runs count as passed. `branch_checks` is rebuilt on top of it with the same text, so its tests are unchanged.
- **Autopilot**: `JobServer(..., ci=, prune=)` seams, `defer_reason` (the PC rule first, then CI), `prune_tick` and `_session_job`. A
  deferral is logged once per (head, reason) and never sets `started`. The verb wires `ci` to `branch_ci` and `prune` to `worktrees.prune`.
- **`warscape/worktrees.py`** (library, not a tool): `registered`, `stale`, `main_root`, `stray_git(root, ceiling=None)`, `report` and
  `prune`. Git runs with `git_env()`.
- **Verb** (`warscape/verbs/jobs.py`): `next` runs through `next_claim`. New: `--peek`, `--prune`, and the `worktrees` action. `HELP`,
  the header `usage:`/`when:` and the tools row are updated.
- **Docs**: `docs/CONSUMING.md` (the `pc_state` key and a bullet on claim, autopilot and the consumer steps), `docs/DECISIONS.md` C32,
  `docs/BACKLOG.md` B87 (the napoleon follow-ups). VERSION is left at main's: W29's release workflow reached `main` first and numbers the release (this row is below `semver_from`, so it counts as `patch`). The decision was renumbered from C29 as W33, W27 and W28 took C29 to C31.

## Evidence
- Red commit `db0c17a` (tests only), CI run 41886083852: `gates (ubuntu-latest)` and `gates (windows-latest)` both failed, as intended.
  Locally: 118 tests, 4 failures and 28 errors.
- Green: `python3 -m unittest tests.test_jobs tests.test_worktrees tests.test_fixture_game` gives 140 tests OK (2026-11-04). The CI runs
  on the final head are listed in the pull request. Run 41887220713 at `9f990b7`: `gates (ubuntu-latest)` success. No case is skipped on
  either OS: the claim and worktree tests use real git in temp folders and run on both legs.
- Failing fixtures, applied one at a time as working-tree mutations (each file restored after its run, nothing committed), all **RED**:

  | Fixture | Test that goes red |
  |---|---|
  | claim pushes HEAD | `test_the_claim_pushes_origin_main_not_head` |
  | claim with `--force` | `test_a_refused_claim_never_moves_the_existing_branch` |
  | plain push, no lease (the brief as written) | `test_a_refused_claim_never_moves_the_existing_branch` |
  | any push failure is a lost race | `test_a_failure_that_is_not_a_race_exits_1_and_claims_nothing` |
  | `pick_next` by id alone | `Order` |
  | `not_ready` ignores `pc_state` | `test_a_missing_folder_skips_the_row_with_the_reason` |
  | `WSC_PC_STATE` ignored | `test_the_environment_beats_the_key` |
  | review start ignores `branch_ci` | `test_review_starts_only_on_green_and_logs_a_deferral_once_per_head` |
  | `unknown` starts a review | `test_review_starts_only_on_green_and_logs_a_deferral_once_per_head` |
  | fix deferred on red | `test_fix_defers_only_while_ci_has_not_finished` |
  | `needs_pc` serialisation dropped | `test_one_needs_pc_row_at_a_time` |
  | `stray_git` counts a linked worktree's own repo | `test_stray_git_above_the_main_root` |
  | merged worktrees removed by `--prune` | `test_prune_removes_only_the_missing_folders` |
- Dry-run autopilot against the real repo: `python3 wsc.py jobs view --serve --auto --dry-run --no-open --interval 30`, stopped after
  three ticks:
  ```
  2026-11-04 18:30:04 UTC jobs auto: on, every 30 s (dry run: nothing is started)
  2026-11-04 18:30:05 UTC jobs auto: would prune dead worktree registrations
  2026-11-04 18:30:06 UTC jobs auto: tick: nothing ready for review or fix (9 job branches)
  2026-11-04 18:30:37 UTC jobs auto: would prune dead worktree registrations
  2026-11-04 18:30:37 UTC jobs auto: tick: nothing ready for review or fix (9 job branches)
  2026-11-04 18:31:08 UTC jobs auto: would prune dead worktree registrations
  2026-11-04 18:31:09 UTC jobs auto: tick: nothing ready for review or fix (9 job branches)
  ```
- `python3 wsc.py jobs next --peek` (2026-11-04, after the red-PR lines). No live claim was made from this session. The first real claim
  happens at the next `jobs next`:
  ```
  W9: Acceptance and scene launches: build id after launch, staged saves, hist_nile retry, flakes, evidence shas, watcher preflight (model sonnet, needs_pc yes)
  (not claimed: --peek) `git push origin --force-with-lease=refs/heads/job/W9: origin/main:refs/heads/job/W9` claims it (python3 wsc.py jobs next does). Then take it: git fetch origin job/W9, git checkout -b job/W9 origin/job/W9, then follow jobs/W9/brief.md.
  ```
- `python3 wsc.py jobs worktrees --offline` on the core's PC clone: "2 worktrees' branches are merged" (review-W2 and w6-review). There is
  no `.git` above it today: `~/repos/.git` is gone. That clone has 25 worktree registrations, not 47.

## Deviations from the brief, and why
- **The claim uses an empty lease, `--force-with-lease=refs/heads/<b>:`, not a plain push.** Decision 1 assumed that git refuses a push to
  an existing remote branch. On this PC (git 2.55) a plain `git push origin origin/main:refs/heads/job/X` onto an existing empty claim made
  at an older `main` fast-forwards it and exits 0 (porcelain flag space, summary `257629a..941b7cc`). The second session would then "win" a
  claim it lost and move the first session's branch. An empty lease is git's create-only push: if the ref exists at another sha it gives
  `!` `[rejected] (stale info)`; if it exists at the same sha it gives `=`. It never forces. It is still the server's atomic compare-and-swap,
  with no check-then-push. The fixture "plain push, no lease" turns the test red. `--force` is still never used, and its fixture is red too.
- **Fixtures as working-tree mutations, not throwaway commits**: same effect (one change, one named test, then restored).
- **Stale-claim wording**: "J<n>: claimed <age> ago **or less**". The age is the head commit's committer date, as decision 5 says. An
  empty claim's head is a `main` commit made before the claim, so the true claim age can be shorter. The words say so, and open question 2
  asks about it.
- **Stale claims count only rows still waiting**: a `job/<id>` of a `queued` row, or a `brief/<id>` of a `needs_brief` row. A
  merged-and-kept branch of a done job is therefore never shown as a claim.
- **Deferral memory is per (head, reason)**, not per head alone. A head that goes from `running` to `red` logs again, because the new state
  is worth one more line.
- **`worktrees.stray_git(root, ceiling=None)`**: the extra `ceiling` lets the tests stop the walk at their temp folder, so a `.git` higher
  up on a machine cannot make them flaky. It also skips a submodule's superproject, which is expected, not stray.
- **Changed existing tests**: `Autopilot.make` passes `ci=` green and a no-op `prune=` (the old cases had no CI to read). The `MainHealth`
  `next` case stubs `remote_heads`, `fetch_main` and `claim` so that it can never push to the real origin. No assertion changed. No
  existing test asserted the old "push early" text.

## Open questions
1. **Decision 11's split**, as built: a review waits for `green`; a fix waits only while CI is `running` or `none`, so a fix starts on
   `red`, `green` and `unknown`. Reversing it is one expression in `JobServer.defer_reason`.
2. **Decision 5's 24 h threshold** uses the head commit's date, which is earlier than the claim. On a quiet `main`, a fresh claim can be
   listed at once. If that is noisy, a claim could carry its own date (an empty commit on top of `main`), but that breaks "no commits of its
   own". For now the line says "or less".
3. **Open question 5 of the brief**: yes, a claim triggers CI. This job's own claim push at `72f50d4` ran `gates` (run 41884627000,
   success, cached sets skipped). It does not slow the claim, which returns when the push does. A claim also runs the local pre-push hook
   (`gates --fast`, under a second here). A failing local gate refuses the claim with exit 1, as decision 2 asks.
4. **`stale`'s "ancestor of origin/main" rule** flags a fresh worktree whose branch has no commits yet (for example a job just checked
   out). It is reported only, never removed. It could be narrowed to job/brief rows that are done, if Liam prefers.
5. Napoleon's wiring (B87): its `setup` verb calls `worktrees.report`, its `wsc.toml` sets `pc_state`, and its CLAUDE.md "pick up" line
   drops "push early". These are napoleon changes this job could not make.

# W44 review

## Round 2 (2026-11-06, branch job/W44 at bb92c56)

**Verdict: merge.**

All five round 1 findings are answered, and I checked each one on the code rather than in the report. The one gap the fix session left open, napoleon never measured on the fixed code, is closed below: I ran it, and every prediction in the report held. No blocker and no should-fix. This round changes nothing outside the job folder and the row.

### CI on the fix commits, Windows included
- **The fix commits have no CI run of their own.** `15e4de9`, `9eedad8`, `9a46afb`, `bdea080`, `c879f10` and `e2d3f7d` reached origin in one push with `1270eb3`, so GitHub ran only the pushed head. They are covered as part of the head's tree, not one by one. That is enough for a squash merge, which lands only that tree.
- **The run on `1270eb3` proves nothing:** 42141779919 was cancelled about 85 s in by the next push, on ubuntu and on both Windows jobs.
- **The run on `bb92c56` is the evidence:** 42141819455 finished `success`. `gates (windows-latest)` ran the full set, 01:10:07 to 01:23:10: 15 ok, 1 warn, 0 failed, 1280 host tests passed, 5 skipped. `harness-windows` passed. `gates (ubuntu-latest)` passed with the same 1280.
- **The Windows job was a real run, not a pass marker:** the `changes` job says `gates_windows=true` and `Cache not found` for tree `11ed50a6`; the marker it then saved names commit `bb92c56`. `proxy` was skipped, correctly: `proxy=false`, and the branch touches no proxy input.
- **Nothing differs from what was tested but paperwork:** `git diff 1270eb3 bb92c56` is one line of `jobs/W44/report.md`, and all six fix commits are ancestors of `bb92c56`. The log does not name test files; `test_audit` is inside the 1280 by count, which equals my local run of the same tree.
- Run 42138672224 on `a681ee3` had Windows skipped before ubuntu finished, so it covered nothing on Windows, but it predates the fixes.
- Pushing this round adds only this file and the row. If `changes` skips Windows on the same input tree, that skip stands on 42141819455.

### The failure on ubuntu: a flaky test, not W44's
`test_lock_wait_takes_a_lock_released_meanwhile_and_times_out_with_124` in run 42138672224, `2.0649 not greater than or equal to 2.5`. It is already filed as `W81`.
- **W44 cannot have caused it.** The branch changes neither `harness/job.sh` nor `tests/test_job_sh.py`. The failing commit `a681ee3` changed only `jobs/W44/review.md` and the row against `1e7244e`, whose run 42137131031 passed. The same test passed on `bb92c56`.
- **It fails on other branches with the same number.** `job/W31`, run 42075839757, commit `6b7c73e`: `2.0673`. `W81` cites a third, on W34, run 41934314012, which I did not open.
- **The cause:** `harness/job.sh:204` sets its deadline from `date +%s`, whole seconds, and the loop polls every 2 s. A start late in a second reaches the deadline after one sleep, about 2 s plus process start, while the test wants at least 2.5.
- **Reproduced in part, 2026-11-06:** `lock --wait 3` started at set points within a second, 20 runs on this PC, gave two bands: 11 at 2.65 to 2.88 s and 9 at 5.04 to 5.14 s. The early band is the early deadline. It stays above 2.5 here because Git Bash starts slowly, which would explain why ubuntu fails and Windows does not. I did not run it on Linux: the 2.06 there is read from the two failure logs. If process start is about 0.06 s, the early band opens for about 6% of starts; that rate is an estimate, not a measurement.
- **It matters beyond this job:** the check is required, so a red lands on any branch at random, and on a merge push it stops auto-merge. A `plan/` row raises `W81` with the second run.

### Round 1 findings
| # | Finding | Verdict | How I checked |
| --- | --- | --- | --- |
| 1 | `idle_queue` quiet on a parked queue | fixed, `bdea080` | fires on napoleon below, naming `J29` and `J60`; `parked()` read against `lane()`: both pick the same branch for a `progress` row |
| 2 | report's napoleon claims | fixed, `e2d3f7d` | run, shas, 14 unmatched subjects and the 9 against 12 table are in `## Fix round 1`; the edits to lines 3, 93 and 118 are what round 1 asked for, and the report lists the old wording |
| 3 | `<id> brief` as job merges | fixed, `15e4de9` | 69 job merges, 78 brief merges on napoleon below |
| 4 | `pin_lag` depends on the clone | fixed, `9a46afb` | `details.tags_from` is `origin` online and the evidence names the store with `--offline` |
| 5 | findings on paths gone from main | fixed, `9eedad8` | 4 and 6 paths in `details.gone`, none in the findings; the fixer's `a.tree` is better than my round's `a.sizes`, and a mutation below confirms the gitlink case |

### What I ran
- `python3 wsc.py gates` at `bb92c56`, 2026-11-06: 14 ok, 2 warn, 0 failed, 1280 host tests passed, 5 skipped. The warns are this clone's absolute `core.hooksPath` and the skips.
- `python3 wsc.py jobs check`: 116 rows, ok.
- `python3 wsc.py audit --since 2026-10-28` on the core, online, at main `215f440`, output outside the repo: exit 0, 46 findings, 40 job merges, `ci_durations` read.
- **Each fix undone in a throwaway copy, `tests/test_audit.py` run each time.** The unmutated baseline passed. All seven mutations failed a named test: the brief subject, `hot_files` gone, `conflict_files` gone, gitlink kept, tags from origin, parked not busy, `max_job_hours` as the limit. My first attempt was void, because the module did not load in the copy and that looks like a kill; I repaired it and added the baseline.

### Napoleon measured on the fixed code
This is the run the fix session could not do. I made a fresh clone with its `core` submodule inside this worktree's ignored `_scratch/`, deleted afterwards, so no napoleon checkout was touched. `python3 wsc.py --root _scratch/nap audit --since 2026-10-28 --json <outside>` from `bb92c56`, online, at napoleon main `bca3b99`, one commit past the `9550e58` of the earlier run, 2026-11-06: exit 0, 44 findings, 12 metrics, 0 skipped, 0 failed. The same with `--offline --only pin_lag,queue`: exit 0.

| The report predicted | Measured |
| --- | --- |
| job merges 75 to 69, brief 72 to 78 | 69 and 78 |
| `idle_queue` appears, `J29` and `J60` parked | fires, high; parked at 54.6 hours each; ready 9, progress 2 |
| `pin_lag` reads 12 online | 13, because `v0.43.0` came out after the prediction: pin `v0.30.0`, `tags_from` origin |
| `--offline` says it read the store | it does, in the evidence line |
| 4 `hot_file` and 6 `conflict_file` findings move to `details.gone` | both, the same paths |
| `.github/workflows/gates.yml` may cross 25% | it does: 18 of 69, 26% |

52 findings less those 10, plus `idle_queue` and that `hot_file`, is the 44 measured. `J78` gates 11 rather than 10, and the brief lane is 22 rather than 21: the extra commit is a plan row, `J104`. This satisfies deliverable 4 on the fixed code, and the kill criterion stays untripped.

### Risk-first reading
I picked `parked()`, `core_tags()` and the `a.tree` split in `warscape/audit.py`, because the first two decide whether a high finding reaches Liam and the third is what every path finding now rests on. `branch` can only name a key of `a.heads`, because `lane()` returned `progress` from that same set. Both fetch paths leave the head sha readable for `git show`. A timed-out `ls-remote` is a `SubprocessError` and lands in `failed`, not in a crash. `git diff origin/main...HEAD` touches no workflow file, so the W36 check does not apply. The rest of the diff since round 1 is the W43 merge, which I skimmed: main's `timeout_s` won, as the report says.

### Later
- **A fresh claim reads as parked.** The limit the report names in blocker 1 is real: `wsc jobs next` claims by pushing main's sha, so on a main quiet for 24 hours a job claimed a minute ago reads as parked and `idle_queue` can fire falsely. A `plan/` row files it.
- **`subject_kind` is case-sensitive.** `Job/j1 (#7)` and the two `Plan:` subjects read as `other`, so napoleon's true job count is 70. Outside the default window, so left, in the same row.
- `doc_cap` on finished briefs and `both_sides_min`: report open questions 2 and 3 stay for W45, as round 1 said.
- Brief open question 1 (`VERSION` in `hot_files`) has its default date on 2026-11-10; nothing here changes the recommendation.

## Round 1 (2026-11-06, branch job/W44 at 1e7244e)

**Verdict: merge after fixes.**

The core half is sound. The napoleon half was never run by the builder, and the run the orchestrator supplied shows three things the core could not: two metrics that read wrong on a real game, and a report whose napoleon claim is out of date. No kill criterion was tripped. Nothing in this round changes a file outside the job folder and the row: every finding is for the fix session.

### What I ran
- CI on `1e7244e`: all 9 checks passed or were skipped (`wsc jobs review`, 2026-11-06).
- `python3 wsc.py gates` on the branch, 2026-11-06: 14 ok, 2 warn, 0 failed. 1215 host tests passed, 5 skipped (the POSIX hook test and four capstone tests); the other warn is `hooks`, this clone's absolute `core.hooksPath`.
- `tests/test_audit.py`: 68 tests, OK, 66 s (2026-11-06).
- `wsc policy --branch job/W44 --base origin/main` before this review: refused only for the missing review and the row not `done`, as expected.
- The core calibration again, through `record(head='f743242')`: 38 job merges, and `docs/CONSUMING.md` 32, `VERSION` 28, `docs/BACKLOG.md` 24, `registries/tools.jsonl` 23, `docs/DECISIONS.md` 18. These agree with the brief and the report.
- `docs/audits/AUDIT_2026-11-05.md` is byte-identical to `render_md()` of its JSON. None of the core record's `hot_file` or `conflict_file` subjects is missing at its `main`, and the core has no `W<n> brief` subject, so findings 2 and 3 below do not change that record.
- Napoleon, read-only, through `gh api` on 2026-11-06 (this session's git is confined to its worktree): the tree at `9550e58`, commit subjects since 2026-10-28, and `job/J16`, `job/J29`, `job/J60` with their rows on the branch, at `9550e58` and at `2975b13`.

### The outside evidence, judged
The orchestrating session ran `python3 wsc.py --root <napoleon> audit --since 2026-10-28 --offline --json <scratch>/nap_audit.json` from `1e7244e` against napoleon main `9550e58`, on 2026-11-06. Exit 0, napoleon's git status unchanged including ignored files. Lanes: progress 2, ready 9, waiting 1, brief 21, blocked 1, done 69. `J78` gates 10 rows. 75 job merges, 52 findings: `job_lifetime` 25, `conflict_files` 13, `doc_caps` 7, `hot_files` 4, `queue` 2, `pin_lag` 1. `ci_durations` skipped (`--offline`), none failed.

**Queue: 9 ready against the brief's 12, none in progress. The kill criterion is not tripped: a counting rule explains all three rows.** The hand count took rows that are queued with their dependencies done; `lane()` also reads the branches. I checked the three rows it moves:

| Row | Row on main | Row on its branch | Branch head | Lane |
| --- | --- | --- | --- | --- |
| `J16` | queued | blocked (waits for W39 in a pin bump) | `666645e`, 2026-11-04 | blocked |
| `J29` | queued | queued | `d95f4fe`, 2026-11-03, 55 behind main | progress |
| `J60` | queued | queued | `dceb74c`, 2026-11-03, 55 behind main | progress |

The sha difference is not the cause: `2975b13` is dated 2026-11-05, all three rows are queued there and all three heads are older, so these three rows read the same at that sha. I checked these three rows only, not all 103. The number is explained, but explaining it exposes finding 1.

**`J78` gating 10:** agrees with "at least 8". **No write to napoleon:** the third kill criterion holds, given `--json` outside the repo (deviation 2 of the report). **`pin_lag`:** see finding 4.

### Blockers
1. **`idle_queue` stays quiet on the state it exists to catch.** `warscape/audit.py:339` counts every `progress` row as busy. `J29` and `J60` are queued rows whose branches last moved on 2026-11-03 with "the PC plan for the later slot", so nobody is building them, and they hold the rule off. The row's own description names "napoleon at 12 ready rows with nothing building", and the record for that state has no `idle_queue` finding. This follows decision 3 to the letter, so it is not a builder's error, but W45 re-measures by id: Liam would read the absence as a queue at work. To see it fail: the record's `queue` value has ready 9 and progress 2, and its findings have no `idle_queue`. Fix: do not count a `progress` row as busy when its branch head is older than a threshold (reuse `max_job_hours`, or add a key), and list those rows in `details` as parked. Ready stays 9: this is not tuning the number to 12. Add a fixture each way, name it as a deviation from decision 3, and update `docs/AUDIT_METRICS.md`.
2. **The report's napoleon claims are out of date, and the evidence is not in it.** `jobs/W44/report.md:3` says napoleon's half "agrees (... 12 ready rows ...)" and line 93 says "It agrees with"; that reading had no branch information, and the real run says 9. Line 3 also says the calibration was not run, and open question 1 at line 118 asks for it. Deliverable 4 wants both calibration outputs pasted, and the brief says a difference is explained in the report. Fix: add the run above with its command, shas, date and exit code; paste its finding lines; explain 9 against 12 with the table above; and correct lines 3, 93 and 118. The output is in a temporary scratchpad (`C:\Users\liamr\AppData\Local\Temp\claude\555b7be18f8a94c1\787b5534-2481-4979-b076-947644bd84ee\scratchpad\nap_audit.json`); if it has gone, rerun the command. **It has to be a fix session:** `policy` refuses a review written by a session that also wrote `report.md`, so this round could not add it.

### Should-fix
3. **`<id> brief:` subjects count as job merges.** `warscape/audit.py:142`: `subject_kind('J6 brief: Empire to Napoleon diff (#21)', 'J')` returns `('job', 'J6')`. On napoleon that is 6 of the 75 job merges (`J2`, `J3`, `J5`, `J6`, `J17`, `J19`), so the true count is 69 job merges and 78 brief merges. Every `hot_files` share is measured against the wrong number, and `throughput` details are off. A brief merge for a job with no job merge yet would also enter `job_ids()`. The brief's target fact gave this rule and said to check it on both repos first; the builder could only check the core, which has no such subject. Fix: read `<id> brief` as `brief`, add a test, and update "How a merge is read". The report must also give napoleon's unmatched subjects, as the brief asked: 14 in this window, which covers its whole history.
4. **`pin_lag` depends on the clone it runs in.** `warscape/audit.py:429` reads tags from the local `core/` store. The record says the newest tag is 0.38.0 and the lag is 8; the core's newest tag is `v0.42.0`, so the true lag is 12. The rule fires either way here, and decision 3 said "object store", so the code is as briefed. But a stale store can silence it: a pin at 0.36 with a store at 0.38 reads 2 where the truth is 6, and no finding is raised. That is the fault deviation 4 fixed for the PC: a finding must not depend on where the audit ran. Fix: online, read the tags with `git ls-remote --tags` in `core/` (no write); with `--offline`, keep the store and say so in `details` and the evidence line.
5. **Findings name files that no longer exist.** `warscape/audit.py:225` and `:252` never check that the path is still at main. On napoleon all 4 `hot_file` findings and 6 of the 13 `conflict_file` findings do this (`registries/jobs.jsonl`, `jobs.md`, `tools.jsonl`, `tools.md`, `engine_facts.jsonl`, `engine_facts.md`, gone at `9550e58`), and two of those 10 are `high`, which is two of the record's three `high` findings. `registries/jobs.jsonl` is also the old form of the very registry `hot_files` excludes. W45 would turn each into a proposal about a file already fixed. Fix: keep the counts, raise no finding for a path not in `a.sizes`, list those paths in `details`, and test it.

### Later
- `doc_cap` on finished briefs: report open question 2 stands; napoleon adds `jobs/J64/brief.md` and `jobs/J76/brief.md`. W45 should settle it.
- `both_sides_min`: report open question 3 stands. Napoleon gave 13 findings against the core's 28, so judge it on the 7-day default.

### Accepted deviations
- Deviation 10, `[tests] timeout_s = 900` in the core's `wsc.toml`: named, evidenced, one line, and the brief's "sets nothing new" was about `[audit]`. Keep it.
- Deviations 1 to 9 are named with their reasons. Deviation 1 is closed by the orchestrator's run once finding 2 is answered.

### Risk-first reading
I read `warscape/audit.py` in full, because every later proposal rests on it, and traced `lane`, `remote_heads` and `branch_rows` in `warscape/jobq.py`. Its only writes are the two online fetches and the output files; `--offline` with `--json` writes nothing in the repo. The branch reads, window arithmetic and exit codes held up. I skimmed `tests/test_audit.py` and did not repeat the builder's mutation check.

# W45 report: Proposals registry, the answer round and the decide/ branch kind

W45 adds the half of C41 between a finding and a change: a proposals registry, `wsc proposals draft|check|ask|answer|close`, a `decide/` branch kind only the owner merges, and a guard on every branch kind so that nothing but `decide/` can write an answer. `wsc audit` now reads the rows, suppressing declined findings and re-measuring applied ones, and `doc_caps` leaves out the job folders. The dry run went end to end: the answers pass `policy` on `decide/`, and the same diff is refused on `plan/`. Branch `job/W45`, session 8c158f7a.

Usage: 105 tool calls; models: opus; 1 session, counted by hand, about, brief 30 and build 75, 2026-11-06

## What was built
- `schemas/proposals.schema.json`, declared in `wsc.toml` with one file per row. The registry stays empty here: W47's session raises the first real rows.
- `warscape/proposals.py`: the row's logic, the five actions, `overlay` (what `wsc audit` adds to a record) and `view_html`. `applied` is computed, never stored.
- `warscape/verbs/proposals.py` with its header and tools row, and `proposals` in `CORE_VERBS`. `check` runs in `gate_jobs`.
- `warscape/policy.py`: the `decide/` kind (`decide_problems`), the guard on every kind (`proposal_problems`, `proposal_row_problems`, `auto_applied`, `decide_answer_problems`), `answers_path`, and `dir_rows_at` split out of `rows_at`. The docstring is updated. `settings()` gains three values and the judge's arguments do not change, so `JUDGE_API` stays 1.
- `warscape/audit.py`: `suppressed` and `remeasured` in the record, read from the rows at the measured sha; `decide` as a subject kind; `doc_caps` skips `<[jobs] dir>/**`. Both keys are present only when not empty, so `version` stays 1 and old records render as they did.
- `[audit] auto_apply`, `reraise_margin` and `max_questions`; `reg add --mint` works on proposals; `render_view` takes `owner_html`, and both of its callers pass it.
- `docs/PROPOSALS.md`, the one owner of the row, the states and the round, with links from `docs/CONSUMING.md`, `docs/AUDIT_METRICS.md`, `docs/REVIEW.md` and `docs/UPGRADING.md`.
- `tests/test_proposals.py`: 106 tests, no git and no history read, about 0.5 s locally. Three tests in `tests/test_audit.py` use real git: `doc_caps` on a job folder, and rows read at the sha, not the working tree.

## Evidence
**Tests.** Red first: commit `c990892` failed on the import. Green at `41ff1ec`: `python3 wsc.py gates`, 2026-11-06, gave 14 ok, 2 warn, 0 failed, 1428 host tests passed and 5 skipped (the POSIX hook test and four capstone tests, as on W44). The warns are this clone's absolute `core.hooksPath` and those skips.

**The first full run failed, and the partial runs had not shown it.** `python3 wsc.py gates` before the push gave 1 failure and 7 errors: a test pinning the refusal message, and `render_view` reading the registry through a stub `ctx`. The second was a design slip of mine: the renderer took data as arguments and I had made it read. It now takes `owner_html`, as it takes `main_html`.

**CI.** Run 42188698712 at `41ff1ec`, success: `gates (ubuntu-latest)` 15 ok, 1 warn, 0 failed, 1428 tests in 113.8 s; `gates (windows-latest)` the same 1428 in 745.0 s; `harness-windows` passed; `proxy` skipped, correctly, as no proxy input changed. Windows ran the full set, so this is a real run and not a pass marker. It is 335 s under `[tests] timeout_s` (1080). What these tests add is small: `tests/test_proposals.py` about 0.5 s locally, and three audit fixtures in a suite of about 85 s.

**Mutation check.** Most tests passed on their first run, so I mutated the guards to prove they can fail. Of 61 mutants in `warscape/policy.py` and `warscape/proposals.py`, 8 survived the first pass. Six were real gaps in the tests: three `auto_applied` conditions hidden behind a failing record check, closing a row while rewriting its content, a status of `accepted` with no `answer`, and a baseline of 0 unchanged. Two were loose assertions on refusals that still happened. The code did not change; the tests did. The second pass killed 61 of 61, with a baseline run first to prove the copy loads.

**The kill criterion on the numbers.** At `adf9b1a`, the same main measured by the old code and by this branch: 41 findings against 35. The six that went are all `doc_cap:jobs/...`: `W23`, `W24`, `W33`, `W34`, `W9` briefs and the W44 report. No finding was added or changed. `metrics` differ only on `doc_caps` and on `throughput`, whose kinds gain `decide: 0`. The criterion is not tripped.

**The dry run.** In a throwaway clone inside this worktree's ignored `_scratch/`, deleted afterwards, on 2026-11-06. The clone's `origin/main` was moved to the job's head, because `decide/` is judged with the base's rules and the real base does not have them yet. `draft` read `docs/audits/AUDIT_2026-11-05.json`. I kept two rows, filled them, and removed the other 48 skeletons.

```
$ python3 wsc.py proposals draft
proposals: 50 drafted; fill each, then `wsc proposals check`
kept P261106-135a (hot_file:README.md) and P261106-3195 (doc_cap:docs/CONSUMING.md)

$ python3 wsc.py proposals check
proposals check: ok
$ python3 wsc.py proposals ask
| Id | Question | Options | Recommended | Tag |
| --- | --- | --- | --- | --- |
| P261106-135a | hot_file:README.md is hot: split it? | `split` Split the file.; `leave` Leave it. | `split` |  |
| P261106-3195 | doc_cap:docs/CONSUMING.md is near the cap: act? | `leave` Leave it.; `later` Ask again later. | `leave` |  |

$ python3 wsc.py policy --branch plan/dry-fill --base origin/main
policy: plan/dry-fill: ok (2 files changed)

$ python3 wsc.py proposals answer --answers answers.json --quote quote.txt      (on decide/2026-11-06)
proposals: 2 answered, docs/audits/ANSWERS_2026-11-06.md
Commit, then: git push -u origin decide/2026-11-06
gh pr create --base main --head decide/2026-11-06 --title "decide: answers of 2026-11-06"
Only Liam merges it (C41): no auto-merge.
 docs/audits/ANSWERS_2026-11-06.md, registries/decisions/C261106-4361.json, registries/jobs/W121.json, the two proposal rows

$ python3 wsc.py policy --branch decide/2026-11-06 --base origin/main
policy: decide/2026-11-06: ok (5 files changed)

$ python3 wsc.py policy --branch plan/dry-forge --base origin/main              (the same diff)
policy: plan/dry-forge: REFUSED (5 files changed)
policy: docs/audits/ANSWERS_2026-11-06.md: an ANSWERS file quotes the owner, so it changes only on a decide/ branch
policy: P261106-135a: an answer is written only on a decide/ branch, which the owner merges (C41); `wsc proposals answer`
policy: P261106-3195: an answer is written only on a decide/ branch, which the owner merges (C41); `wsc proposals answer`

(the job row set done in a commit `W121: split the hot file`, then)
$ python3 wsc.py audit --offline --since 2026-11-06 --record
`hot_file:README.md`: P261106-135a moved, 0.2821 then, None now
audit: 3 findings, 1 suppressed, 10 metrics, 2 skipped, 0 failed; 6 job merges 2026-11-06 to 2026-11-06, main 8862581
suppressed: [{"proposal": "P261106-3195", "finding": "doc_cap:docs/CONSUMING.md", "status": "declined", "baseline": 30.0, "value": 29.95}]
remeasured: [{"proposal": "P261106-135a", "finding": "hot_file:README.md", "baseline": 0.2821, "value": null, "verdict": "moved"}]

$ python3 wsc.py proposals close
proposals: 1 closed, 0 re-raised
P261106-135a closed moved C261106-4361 W121
P261106-3195 declined None None None
$ python3 wsc.py policy --branch plan/dry-close --base origin/main
policy: plan/dry-close: ok (3 files changed)
```

That dry run was on `53d431b`, before the `render_view` change and the merge of W41; neither touches the paths it used. No proposal row is committed on this branch.

## Deviations from the brief and why
1. **The brief was written on Opus.** The skill says Sonnet for a brief; Liam asked for the brief and the build in one session. The same session wrote both, so a reviewer should not read the brief as a second opinion on the design.
2. **An answered row is tighter than decision 5.** The brief lets `decision` and `job` change after an answer. Nothing needs that, and a `plan/` branch could then point an accepted row at another job, so only `status` and `outcome` change.
3. **W47's order is `close`, `draft`, fill, `answer --auto`, not the brief's `draft`, `answer --auto`, `close`.** `close` drafts re-raised skeletons, which need filling like the others.
4. **`wsc.toml` changes beyond decision 3:** `decide/` in `[docs] path_ignore` (a branch prefix, as `plan/` is) and `registries/proposals/` in `gates_windows`, which `test_every_plan_glob_is_paperwork_to_the_windows_gates` required.
5. **`docs/CONSUMING.md` grew by 9 bytes, not paid for with a cut.** It stays under the cap.
6. **A status alone counts as an answer.** The brief named a change to `answer`; a row set to `accepted` with no `answer` is refused too, on the same line. A mutant showed this was untested.
7. **A row added already accepted is allowed on `plan/` when `auto_applied` passes.** Decision 5 reads as allowing it, and W47 drafts and applies in one branch. With `auto_apply` empty, it is always refused.

**Main was red when this job started, for the record.** The first `jobs next --id W45` could not claim: #135 had removed `docs/DECISIONS.md` while W44's `docs/AUDIT_METRICS.md` cited it, so `doc_paths` failed on every push. Another session fixed it in #143 while I was preparing the same line, and I dropped my branch unpushed. W41 merged during the build and conflicted in `docs/UPGRADING.md`; both sections are kept, and the full gates and CI above are on the merged tree.

## Open questions
1. **Brief question 1:** is 0.25 right for `reraise_margin`? Unchanged. recommended: yes, judged after the first closed proposals; default after: 2026-11-20.
2. **Brief question 2:** should CI refuse auto-merge on a `decide/` pull request? Unchanged. recommended: no, the same standing as `meta/`; tag: risk.
3. **`draft` wrote 50 skeletons from one record, and `check` refuses an unfilled one.** W47 has to either fill 50 or cap them. recommended: `draft --max` in W47, highest severity first, at `[audit] max_questions`; default after: 2026-11-20.
4. **A short window reads as `moved` too easily.** In the dry run `hot_file:README.md` moved because a one-day window cannot reach `hot_file_min`, not because anything improved. W47 uses the default 7-day window, so this should not arise there. recommended: W47 never passes `--since` for `close`, and its brief says so; default after: 2026-11-20.
5. **The merge skew that turned main red has no row.** #135 passed on a base from before W44, so the two passed alone and failed together. Requiring a branch to be up to date before merge would catch it, at the cost of more CI runs. A `job/` branch cannot add another row, so this needs a `plan/` row. recommended: file one; default after: 2026-11-13.

Report question 3 of W44 (`both_sides_min`) is untouched, as the brief says.

## What W47's brief must call, and what a game declares
W47: `wsc audit --record` first, so that `draft` reads a record from after this job (the 2026-11-05 record still holds the six `doc_cap:jobs/...` findings), then `wsc proposals close`, `draft`, fill each, `answer --auto`. A game: `docs/PROPOSALS.md`, "What a game declares". A pin bump to this tag carries no acceptance run for it: no DLL or harness input changed.

# W45 report: Proposals registry, the answer round and the decide/ branch kind

W45 adds the half of C41 between a finding and a change: a proposals registry, `wsc proposals draft|check|ask|answer|close`, a `decide/` branch kind only the owner merges, and a guard on every branch kind so that nothing but `decide/` can write an answer. `wsc audit` now reads the rows, suppressing declined findings and re-measuring applied ones, and `doc_caps` leaves out the job folders. The dry run went end to end: the answers pass `policy` on `decide/`, and the same diff is refused on `plan/`. Branch `job/W45`, session 8c158f7a.

Usage: 205 tool calls; models: opus; 3 sessions, counted by hand, about, brief 30, build 75, fix 25 and fix round 2 75, 2026-11-06

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

## Fix round 1
Fixed on `job/W45`, with origin/main merged first (`ff5f99f`, then `27506b4`, the plan rows W124 to W126). Round 1 had no blockers, and all four should-fix items are done.

1. **Should-fix 1, tag stripped on `plan/`: `96b761b`.** On an existing row, `plan/` may add a `tag`, but may not change or remove one, or change `class`. The check sits before `auto_applied`. Five tests: strip, change, relabel, adding is still allowed, and closing as `gone` keeps the tag.
2. **Should-fix 2, the registry outside `[storage] dir`: `8519300`, `e624dcc`.** `load_config` now refuses that config, so the failure is closed. One step beyond the finding: `wsc reg migrate proposals --to jsonl` would have written exactly that config and left every verb refusing to load, so it is refused too. `e624dcc` corrects the `test_audit.py` fixture, which declared the registry without the storage; the first full gates run caught it.
3. **Should-fix 3, an earlier ANSWERS file rewritten: `4d3c82c`.** The guard refuses a change to or deletion of `record` when the base has the file, and `answer` refuses before it writes anything. Both name the next branch through `next_decide` (`decide/<date>-2`, and `-3` after that). Four tests.
4. **Should-fix 4, `docs/AUDIT_METRICS.md`: `44987ac`.** `decide` is in the subject kinds.

The rule changes are in the `warscape/policy.py` docstring and `docs/PROPOSALS.md`. `docs/CONSUMING.md` is untouched, still 30697 bytes.

**Left, and the reviewer should look at it: should-fix 1 has a second route.** The fix covers an existing row, as the finding asks. One `plan/` branch can still close a tagged row as `gone` and add a new untagged row for the same finding, already accepted by `auto_apply`: with the test module's `AUTO` settings the judge gives `[]` (run this round, not committed as a test). The tag does not stop this, because the new row is a different file. Closing it means reading the base's other rows, and `proposal_problems` has only per-path reads, so it is more than this fix. It is latent while `auto_apply` is empty and is close to W125 (a close on no evidence), which needs the route added or its own row before anyone fills that list. A `job/` branch cannot change W125, so it is left to a `plan/` branch.

**Left as filed:** the review's later items are W124 to W126, and `max_questions` in no doc is unchanged. Report question 5 stays Liam's.

**Evidence.** `python3 wsc.py gates` on this Windows PC at `e624dcc`, merged with origin/main `27506b4`, 2026-11-06: 15 ok, 1 warn, 0 failed, 1439 host tests passed, 5 skipped, 660.7 s. The warn is the known skips. origin/main was checked again after that run and had not moved. `python3 wsc.py policy --branch job/W45 --base origin/main` refuses on only the two expected lines, the missing merge verdict and the done row. The mutation check was not repeated for the new guards.

## Fix round 2
Fixed on `job/W45`, with origin/main merged first (`ae802cb`, `b4aceec`, then `0ac0bf6` before the last push). All four should-fix items are done, and the class is closed but for one route that a judge reading a diff cannot close: route 13 below. Liam's brief for this round was the whole class, not the named route, so the routes are listed and each was run through the real judge.

1. **Should-fix 1, a new row with a class its finding lacks: `0b0c8d4`.** A row is refused at the add, open or not, unless `class` is its finding's rule, and `auto_refusal` checks it again at the acceptance for a row already on a base.
2. **Should-fix 2, a tagged finding through a new row: `0b0c8d4`.** `run_check` reads the rows at the base's tip and the head and passes them to `check` as an optional argument, so the child's arguments and `JUDGE_API` do not change. No row with a tag on that finding may exist, closed ones included. All three forms in the finding are refused, plus the `None` default's test.
3. **Should-fix 3, `decide/` on a row it does not answer: `0b0c8d4`.** More than the one word: the frozen fields below apply to `decide/` as they do to `plan/`.
4. **Should-fix 4, `docs/PROPOSALS.md`: `61ab9e4`.** `registries/decisions/*` is named, and why.

**One rule, three callers.** `auto_refusal` in `warscape/policy.py` is what the judge, `wsc proposals answer --auto` and `wsc proposals check` all call. The verb therefore leaves open what the guard would refuse, where before it would have written a branch the judge refuses (the row `close` re-raises on a tagged finding, a `question` row, which was a `KeyError`). `b4d577e` removed one check of mine the mutation run showed was dead.

**A bug found on the way.** `Registry.save` rewrites every row file, and the guard compared text, so a closed row merely reformatted was refused as "a closed row stays closed". The guard now compares parsed rows (`0b0c8d4`, with a test).

### The routes
`tests/test_proposals_judge.py`: one seeded repo holding this checkout's code, `auto_apply = ["doc_cap"]`. Each case is a real commit on a real branch name, judged by `wsc policy --branch <b> --base origin/main`, the parent and the `--judge` child. "Before" is that same test at `f706ec1` plus origin/main, before the fix.

| # | Route | Before | Now |
| --- | --- | --- | --- |
| 1 | New row accepted, class of another rule (should-fix 1) | passed | refused |
| 2 | The same row added open, to accept later | passed | refused at the add |
| 3 | A row already on the base with a wrong class, accepted | passed | refused |
| 4 | Relabel `class` on an existing row, with or without accepting | refused | refused |
| 5 | Change `finding` on an existing row to fit its class | refused only because the test's `class` moved too | refused on `finding` |
| 6 | Invented finding: `doc_cap:docs/H.md` where the record's finding on that subject is `hot_file` | passed | refused |
| 7 | A real finding under another `metric` | passed | refused |
| 8 | `kind: question`, with no finding (run) or with a real one (test added after the "before" run, so read, not run) | passed | refused |
| 9 | Baseline names a file that is no record (`docs/fake.json`, or a `..` path) | passed | refused |
| 10 | Rewrite or delete a merged `AUDIT_` record to add the finding | passed | refused, every kind but `meta/` |
| 11 | Alias finding, spelled to miss the tag (`docs//T.md`, trailing space, `./docs/T.md`) | passed (read, not run: the test came after the "before" run) | refused, as 6: the record has no such id |
| 12 | Other file names for a row: `%2D` in the name, no extension (both passed); `.JSON`, a subfolder (both refused) | mixed | refused |
| 13 | **A new hand-written `AUDIT_` record holding an invented finding, with its row** | passed | **passes: see Left** |
| 14 | Tagged row left open, new accepted row on its finding | passed | refused |
| 15 | Close the tagged row as `gone` and add the row, one branch | passed | refused |
| 16 | The same in two branches, the close merged first | passed | refused |
| 17 | A row closed long ago still holds its tag | passed | refused |
| 18 | The tag added on another row in the same branch | passed | refused |
| 19 | A stale branch cut before the tag landed (read at the tip, not the merge base) | passed | refused |
| 20 | Move the tagged row off its finding, then add a clean row | passed | refused at the first branch |
| 21 | Change `kind`, `metric`, `date`, `reraises` or `baseline` on a tagged row | passed | refused |
| 22 | Strip a tag as null, `""`, `false`, absent, or change it; strip and accept | refused | refused |
| 23 | A duplicate JSON key, the last one null | refused | refused |
| 24 | The head's `wsc.toml` lists the class | refused | refused |
| 25 | A status outside the states (`Accepted`) | passed | refused |
| 26 | `answer` that is no object | refused | refused |
| 27 | `registries/proposals.jsonl` beside the folder: `plan/` | refused by its globs | refused |
| 28 | The same on `job/` | not named by the guard | refused by name |
| 29 | `meta/` or `job/` adding a row | refused | refused |
| 30 | `decide/` stripping a tag, changing one, relabelling, moving `finding` (should-fix 3) | passed | refused |
| 31 | Two branches each passed alone, one tagging a finding, one accepting it | both pass, and `check` said only "two live" | both still pass; `proposals check` names the tag: see Left |

Controls, all ok through the judge: add, fill, add a tag, close a tagged row as `gone`, auto-accept a listed row, a new row accepted on a branch that also adds its record (W47's flow), and `answer --auto` on a real tree, where the listed row is accepted, the row on a tagged finding stays open and the branch it leaves passes `policy`.

### Left
- **Route 13, open, and not closable here.** The judge reads a diff and cannot re-measure, so a new `AUDIT_` record with an invented finding passes as `wsc audit` output. W47 commits the record on the same `plan/` branch as its rows, so no rule on who adds a record fits. I looked at re-running the metric in the judge: `record` depends on the job and brief branches of the day and on `gh`, so it cannot be reproduced later, and it would be a design change in a last round. `test_the_known_limit_a_new_hand_written_record` pins the behaviour and `docs/PROPOSALS.md` "Traps" says it. It is narrow: a session that can do this can already accept any real finding of a listed class with any recipe, so what it adds is not needing a real finding. It needs an answer before `auto_apply` is filled: for Liam, and for the reviewer to file as a `later` row, which a `job/` branch cannot.
- **Route 31 is caught after the merge, not before.** Neither branch sees the other. `proposals check` fails the `jobs` gate on the tree they leave, so the result is a red main, not a stopped merge. This is the merge skew of report question 5, still Liam's.
- **Not in the class, not touched.** Whether a row should carry a tag is the filling session's judgement, and what an option's recipe says is its word: no rule reads either. A tag holding a finding for good is deliberately strict: a real change of mind goes through `decide/`.
- W124 to W126 stay as filed, and `max_questions` in no doc is unchanged.

### Evidence
- **Mutation check, repeated as round 2 asked:** 23 mutants across `auto_refusal`, `record_holds`, the frozen fields, the add rule, the record rule, the rows read and the verb's and `check`'s use, on 2026-11-06. 20 killed at first; the 3 survivors gave `b4d577e` (one dead check removed, two routes given their own assertion), and those were rerun and killed. The mutants were run before `cb4cb17`, which only moves a test helper.
- **`python3 wsc.py gates`** on this Windows PC at `cb4cb17`, 2026-11-06: 15 ok, 1 warn, 0 failed, 1479 host tests passed, 5 skipped, 897.6 s. The warn is the known skips. An earlier run at `b4d577e` failed one test, `test_core_sources_are_stdlib_only`, on my import of a sibling test: `cb4cb17` fixes it.
- **Test time:** `tests/test_proposals_judge.py` is 35 tests in 110 to 140 s run alone. The gate's 897.6 s is well above the 640 to 660 s of the earlier rounds, by more than this module explains, and other sessions shared this PC. `[tests] timeout_s` is 1080. The reviewer should read the Windows CI time, not this one.
- `python3 wsc.py policy --branch job/W45 --base origin/main`, judged at origin/main `0ac0bf6`: refused on only the two expected lines, the missing merge verdict and the row not `done`.
- The alias test (route 11) came after that gates run: `tests/test_proposals_judge.py` alone passed with it, 35 tests. Merging `0ac0bf6` added only `registries/jobs/W127.json`.

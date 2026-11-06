# W45 review

## Round 3 (2026-11-06, branch job/W45 at 735e3bc)

**Verdict: merge after fixes.**

The fix round holds through the real judge, and routes 13 and 31 do not block a merge. But `735e3bc` could not merge: since its base, W9 and W94 gave it a conflict, and a clean merge of the rest would have failed `doc_size`. Both needed a change outside this folder, so under `docs/REVIEW.md` this verdict is the only one open to me, and in round 3 it blocks the job for Liam. I made both fixes on the branch (`0bfc589`, `0ae0a89`), so no finding is left open on it, and CI is green on the merged tree. No fresh round has reviewed those two commits. My recommendation is to merge at `0ae0a89` or later.

### Findings

**Blocker, fixed in `0bfc589`: the branch conflicted with main.** W9 and W45 each raised the count in `tests/test_schema.py:11` from 11 to 12, so `git merge-tree` reports a conflict. The right count on the merged tree is 13: `proposals` and W9's `acceptance_pass`. CI on `735e3bc` could not show this, because a push run tests the branch alone.

**Blocker, fixed in `0ae0a89`: the merge failed `doc_size` by one byte.** `docs/CONSUMING.md` is 30688 bytes at the merge base; W45 adds 9 and W94 adds 24, giving 30721 against a cap of 30720. `git merge` raises no conflict here, and `python3 wsc.py gates --fast` on the merge fails, so this would have turned main red. "answers:" for "the answers:" brings it to 30717.

**Should-fix, for the review record: `0bfc589` has no readable `Claude-Session` trailer.** My mistake: the trailer was not in the last paragraph, and the hook did not stop the merge commit, though it refused the next commit for the same fault. It is this session's commit. Rewriting it needs a force-push, so it stays. No `policy` line refuses it (run below).

**Later, W130 in pull request #160 (open, not merged: see Notes).** Everything under "Routes 13 and 31" that must hold before `auto_apply` is filled.

### Routes 13 and 31
Run through `python3 wsc.py policy --branch <b> --base origin/main` (parent and `--judge` child) in throwaway repos made from the merged tree, each with real commits on real branch names. The list-empty repo uses the core's own `wsc.toml`; the filled one adds `auto_apply = ["doc_cap"]`.

**With `auto_apply` empty, neither can accept anything.** A forged record with an accepted row, a real finding accepted, and route 31's accepting branch were each refused: "the base's `[audit] auto_apply` does not list doc_cap". That check needs no tag, record or race to fail, so no forgery gets past it. This is why they do not block the merge. No proposal row exists on main yet.

**What route 13 can do today:**
- Add a false question: a forged record with an open row passes, and `proposals check` says ok. Liam would be asked about something unreal.
- **Stop the audit loop quietly, which the report does not name.** `AUDIT_2099-12-31.json` with no findings passes on `plan/`. `newest_record` then reads it for good, so `draft` wrote 0 rows, and `close` closed all three open rows, the tagged one too, on a branch `policy` passed. Deleting the record on `plan/` is refused; only `meta/` can. Closing a tagged row needs no record anyway (W125), but the pinned record is new, and a mistyped date would do it by accident. W130 carries it; it matters once W47 runs.

**What route 31 can do today:** only the plain form, two rows on one finding. Both pass alone, `proposals check` fails on the merged tree, and a `plan/` close repairs it.

**With a class listed, both are worse than the report says:**
- **Route 13 defeats the tag, not only the need for a real finding.** The report's route 11 is refused only because the record lacks the alias. A new record holding it passes: `doc_cap:docs//T.md`, `./docs/T.md`, a trailing space, `docs\T.md` and `DOCS/T.md` were each accepted beside the tagged `doc_cap:docs/T.md`, and `proposals check` said ok on all five. `answer --auto` does the same. The exact finding is still refused. Route 6 reopens the same way: `doc_cap:docs/H.md`, where the audit says `hot_file`, passes.
- **Route 31's red main does not undo anything.** After both branches land, `check` fails, but one `plan/` branch closing the accepted row as `gone`, with no evidence, passes `policy` and turns `check` green, because `check` reads answered rows only. The job and decision rows stay. The report's "caught after the merge" is true of the gate and not of the effect. The same red main comes from an accept landing first and a tag after it, with no forgery.

**The report's limit on route 13 needs one correction.** It is right that `plan/` can already add job and decision rows directly, so a forged accept adds no new power today. What it forges is the record of who approved a thing, and C41's "a tagged proposal never is".

**What must hold before anyone fills `auto_apply` (W130):**
1. A class is listed only if the judge can re-derive its finding from git at the record's sha, and a finding id that is not canonical is refused.
2. A branch is up to date before merge, or the judge reads the merged tree. This is report question 5, and this round's two blockers are the same skew.
3. W125 is closed, so a close needs evidence, and W46 does not start a job whose accept broke the rule.
4. `audit_problem` refuses a non-empty list until 1 to 3 land. Today only prose orders this: C41 says `meta/`, but a `job/` branch may change `wsc.toml` too (read, not run).

### What was checked
- **The fix round through the real judge.** Refused: close a tagged row and add an accepted one, a new row with a wrong class, `decide/` stripping a tag, the head's `wsc.toml` listing a class, a merged record rewritten, accept and close in one diff, a closed row added holding an answer, an answer forged on a row closed as `gone`. Controls ok: fill, accept a listed row, `proposals check` after it. `tests/test_proposals_judge.py` passes in the full gates. All four round 2 findings are answered. I did not repeat the mutation check.
- **CI on Windows covered the fix commits.** Run 42207804357 at `735e3bc` holds all of them: `gates (windows-latest)` job 127858758658 ran 1480 tests in 883.8 s, with marker `commit=735e3bc1df62`, and `harness-windows` passed. The red run 42201717253 at `50ab6e0` failed on `test_core_sources_are_stdlib_only`, which `cb4cb17` fixed, as the report says.
- **CI on the merged tree.** Run 42213144412 at `0ae0a89`, success: `gates (windows-latest)` job 127877111548, 1543 tests passed, 5 skipped, 779.0 s, 301 s under `[tests] timeout_s`, 15 ok, 1 warn, 0 failed. `harness-windows`, `gates (ubuntu-latest)` and `proxy` passed; `proxy` really ran, on W94's input. So the 883.8 s was not a trend.
- **Locally.** `python3 wsc.py gates` on the same tree on this Windows PC, 2026-11-06: 14 ok, 2 warn, 0 failed, 1543 tests, 753.4 s. The warns are this clone's hook path and the known skips. That tree was merged with `68a4cf8`; `0ae0a89` adds `0acddb3`, which brings W81's brief and row and `VERSION`, and CI ran it whole.
- **Against the latest origin/main.** `0acddb3` (release v0.46.0), an ancestor of `0ae0a89`; `git merge-tree` is clean. `python3 wsc.py policy --branch job/W45 --base origin/main` at `0ae0a89` refuses on only the two expected lines, the verdict and the row not `done`.
- **The budget.** 205 calls against the lift to 200 is within 1.25 x, and I accept the lift: Liam widened fix round 2 to the whole class. Workflows: none changed.

### Notes
- **For Liam.** `jobs check` allows three rounds, so a further round needs that limit lifted, and `policy` refuses a merge while this verdict stands. The only unreviewed changes are `0bfc589` (one test line) and `0ae0a89` (one doc line).
- **W130 is not on main.** `gh pr merge --auto` on #160 was denied in this session, so that pull request is open and green for Liam to merge. Do not fill `auto_apply` before it is dealt with.
- Report question 5 stays Liam's; this round is new evidence for it.

## Round 2 (2026-11-06, branch job/W45 at 80d3fb7)

**Verdict: merge after fixes.**

All four round 1 findings are fixed as asked, and each holds through the real judge. CI and the merge state are clean. But should-fix 1's aim is not met: a tagged row can still be auto-accepted, and a row can still get a class its finding does not have, because the same forgery works on a new row file. The fix report names one route and leaves it. I found a second, one commit and one line to close. Neither is live while `auto_apply` is empty, but this guard is what the brief calls the rule that matters most, the fix is small, and no job row orders it before someone fills that list. I changed no file outside this folder and the row.

### What was checked
- **CI on Windows covers every fix commit.** Run 42195881887 at head `80d3fb7`, which holds all of them: no earlier run saw `96b761b` to `e624dcc`. `gates (windows-latest)` really ran: job 127818976180 checks out `80d3fb7bd511`, 1439 host tests passed, 5 skipped, 746.4 s, 334 s under `[tests] timeout_s`, 15 ok, 1 warn, 0 failed. `harness-windows` ran (job 127818976195: 78 tests, 60 unit, 35 integration). `gates (ubuntu-latest)` passed. `proxy` skipped on a pass marker: its input tree passed in run 42184328431, the run round 1 relied on, and no fix commit changed a proxy input.
- **Against the latest origin/main.** origin/main was `27506b4` when this round was written, the branch's merge base, so the CI run above is evidence for that tree. It moved to `ae802cb` as this round was pushed: one `plan/` commit changing only `registries/jobs/W94.json`, and `git merge-tree` is clean. The fix round merges main and checks again. Pull request #148 is a draft and mergeable.
- **Locally.** `python3 wsc.py gates` at `80d3fb7` on this Windows PC, 2026-11-06: 15 ok, 1 warn, 0 failed, 1439 tests passed, 640.6 s. The warn is the known skips. `python3 wsc.py policy --branch job/W45 --base origin/main` refused only on the two expected lines, the missing merge verdict and the row not `done`.
- **The real judge.** A throwaway bare origin whose `main` is this branch's tree, so W45's own rules judge, seeded with a tagged open row, an unlisted-class row, a listed-class row, an answered row and its ANSWERS file, with `auto_apply = ["doc_cap"]`. Each case was a real commit on a real branch name through `python3 wsc.py policy --branch <b> --base origin/main` (the `--judge` child, not `tests/test_proposals.py`'s `judge()`). Nothing was pushed to the real origin. Four controls said ok as they should: fill a row, add a tag, auto-accept a listed row, close a tagged row as `gone`.
- **Mutation check, which the fix report did not repeat.** I undid each fix in a throwaway clone, 10 mutants across the guards, the config check, `migrate` and the verb, and ran `tests/test_proposals.py`: all 10 killed.

### Round 1 findings, each through the judge
- **Should-fix 1 (`96b761b`): fixed as asked, on an existing row.** Refused on `plan/`: strip the tag, change it, set it to null, relabel `class` into or out of the list, strip or relabel and accept in one commit, strip or relabel while closing as `gone`. Nine cases. See should-fix 1 and 2 below for what remains.
- **Should-fix 2 (`8519300`, `e624dcc`): fixed.** `wsc proposals check` and `wsc gates --fast` exit 2 on a head without the storage entry, so `gates` cannot go green on it. `wsc reg migrate proposals --to jsonl` exits 2 and writes nothing. With the bad config on the base itself, and a head that repairs it, a `plan/` branch forging an answer is refused: the child gives no verdict (exit 2) and the parent says REFUSED, so there is no fallback to the head's rules. A `meta/` branch that breaks the config passes `policy`, as it should, because the base judges it; `gates` is what stops it.
- **Should-fix 3 (`4d3c82c`): fixed.** Refused: a reused `decide/2026-11-01` rewriting and deleting its record; `plan/` rewriting, deleting and renaming it out of the name pattern (`--no-renames` shows both halves); `meta/` deleting it; `job/` changing it; another date's branch and `-2` rewriting it. Nine cases. `answer` on the reused name exits 1, names `decide/2026-11-01-2` and writes nothing. On `-2` the verb's output is ok, and the same diff on `plan/` is refused.
- **Should-fix 4 (`44987ac`): fixed.** `docs/AUDIT_METRICS.md` lists `decide`.
- **The dry run again.** `answer --auto` was only in the host tests until now. Through the real verb: one listed row accepted, the tagged row left, `policy` ok on `plan/`, `proposals check` ok.
- **Later items.** W124, W125, W126 are on main. `docs/CONSUMING.md` is untouched.

### Findings

**Should-fix 1: a new row can carry a class its finding does not have, and be auto-accepted.** `warscape/policy.py:293` `auto_applied` reads `class` from the row and never compares it with `finding`. Round 1's relabel is closed on an existing row only (`:341`), and a new file has no old row. Decision 1 of the brief says `class` is the finding's rule, so `auto_apply` names rules: Liam listing `doc_cap` is not Liam accepting `hot_file` findings. To see it, with `auto_apply = ["doc_cap"]`: on `plan/r3` add a row with `finding: hot_file:docs/new.md`, `class: doc_cap`, `status: accepted`, `answer.by: auto_apply`, at its recommendation, plus its decision row. `policy` says `ok (2 files changed)` and `proposals check` says ok. Not in the fix report. Fix: in `auto_applied`, refuse a `finding` row whose `class` is not `finding.partition(':')[0]`, as `skeleton` writes it, with a test.

**Should-fix 2: a tagged finding can still be auto-accepted through a new row (the route the fix report left).** Confirmed, in three forms. Close the tagged row as `gone` and add an accepted untagged row on the same finding: one branch, `policy` ok, `proposals check` ok. The same in two `plan/` branches, the close merged first: both ok, check ok. And with the tagged row left open: `policy` ok, stopped only by `proposals check` in the `jobs` gate. So C41's "a tagged proposal never is" does not hold, and `plan/` merges itself. W125 does not cover this: it is about a close on no evidence and adds nothing to `auto_applied`, and later rows are picked up batched, so nothing orders it before `auto_apply` is filled. The fix is smaller than the report thought, because rows are never deleted and a tag on a closed row stays on the base. Read the base's rows with `dir_rows_at(b, cfg['proposals_dir'], repo)` in `run_check` (`:855`), pass them to `check` as an optional argument, and refuse an `auto_applied` row whose `finding` has a tagged row at the base or in the head. The judge child's arguments do not change, so `JUDGE_API` and the kill criterion are not touched. One test per form above, and one for the `None` default the pure-logic tests pass.

**Should-fix 3: `decide/` can strip a tag or relabel a class on a row it does not answer.** The check at `warscape/policy.py:341` says `kind == 'plan'`, so `decide/2026-11-06` changing only `tag` or only `class` on an open row is `ok (1 files changed)`, and a later `plan/` branch can then auto-accept the row. Liam merges `decide/`, so this is a small risk, but `wsc proposals answer` never does this, so nothing needs it, and the fix is one word: `kind in ('plan', 'decide')`. Update the docstring line and `docs/PROPOSALS.md`.

**Should-fix 4: `docs/PROPOSALS.md` "What a game declares" omits `registries/decisions/*` in `[policy] plan`.** `answer --auto` on a `decision` or `job` option writes a decision row on `plan/`. The core's `wsc.toml` allows that; `DEFAULTS['policy']['plan']` (`warscape/repo.py:97`) does not, so a game declaring only what the doc lists gets its `plan/` branch refused. It fails closed. Read, not run on a game config. One clause, and `docs/PROPOSALS.md` has room.

**Notes.** The fix report's "Left" paragraph was honest and accurate, and its route reproduced at once. Report question 5 stays Liam's. A stale worktree `.claude/worktrees/W45-brief` still holds the local branch `job/W45` at `7f57d5e`, 11 commits behind: a checkout of `job/W45` in a new worktree fails, so this round pushed from a differently named local branch.

## Round 1 (2026-11-06, branch job/W45 at 7f57d5e)

**Verdict: merge after fixes.**

The build is sound: the state machine, the audit overlay and the branch kind do what the brief asks, and I found no blocker. Three holes remain in the guard, which the brief calls the rule that matters most, and one doc line is stale. All are small. I changed no file outside this folder and the row, so the fixes are the fix session's.

### What was checked
- **CI on Windows, not only the last commit.** The head's run 42190430064 skipped `gates (windows-latest)`, `harness-windows` and `proxy`, correctly: `git diff 41ff1ec 7f57d5e` is `jobs/W45/report.md` and the row only. The last code commit `41ff1ec` ran for real in run 42188698712: its log (job 127795185043) checks out `41ff1ec637e2`, and gives 1428 host tests passed, 5 skipped, 745.0 s, 335 s under `[tests] timeout_s`, so it is a run and not a pass marker. `harness-windows` passed there too. The earlier red run 42184328431 at `53d431b` failed on both systems, and the report explains it.
- **Against the latest origin/main.** `ff5f99f` (release v0.45.0) is not in the branch: the merge base is `2d00850`. It changes only `VERSION`, and `git merge-tree` is clean. On a local test merge with `ff5f99f`, never pushed, `python3 wsc.py gates` gave 15 ok, 1 warn, 0 failed, 1428 tests passed in 608.1 s, on this Windows PC, 2026-11-06. The one warn is the known skips. So the merged tree has Windows evidence, including `VERSION` 0.45.0, which no CI run has seen with this code. origin/main was still `ff5f99f` when this round was written; a fix round must check again.
- **`docs/UPGRADING.md`.** Both sections are kept and in order: W45 above W41 above W44. The conflict was resolved in `41ff1ec`.
- **`docs/CONSUMING.md`.** 30697 bytes of the 30720 cap, 23 bytes left, and `doc_size` passes on the merge. The link was to be paid for with a cut and grew the file by 9 bytes; the report names this (deviation 5), so it is accepted. Any further line needs a real cut.
- **The dry run again, on the merged tree.** The report's run predates the last code commit, so I repeated it through the real judge, not the stubs: `draft` (50), two rows filled, `check`, `ask`, then `policy --branch plan/rev-fill` ok; `answer` on `decide/2026-11-06`, `policy` ok (5 files changed); the same diff refused on `plan/rev-forge` (ANSWERS file and both rows) and on `job/W45` (same three). `proposals check` ok after. The report's result stands. I did not repeat `audit` and `close` on a later record; those are read and covered by host tests.
- **Risk-first reading:** I picked `warscape/policy.py` (`proposal_problems` and its helpers), because a mistake there lets something other than Liam answer for him, then `warscape/proposals.py` and the `record` change in `warscape/audit.py`. Read as sound: `base_rows` is the merge base, so a `decide/` branch waiting behind a moving main is not falsely refused for job rows added on main; `merged` in `record` reads all of main's history and the newest merge wins (`a.merges` is newest first and is reversed), so an old job does not stay `too_soon`; a skipped or failed metric is absent from `metrics`, so it reads `unmeasured`; both workflows run for a `decide/` branch (`on: push`, and `pull_request_target`).
- **Claims.** The test count, CI timings and Windows run check out. Not re-run: the mutation check and the kill criterion on audit numbers.
- **Workflows:** none changed, so nothing to clear.

### Findings

**Should-fix 1: a tag can be stripped on `plan/`, then auto-accepted.** `warscape/policy.py:323` `proposal_row_problems` lets `plan/` change anything on an open row, and `auto_applied` compares only with that row at the base. C41 and the schema say a tagged proposal is never auto-applied; the forgery test covers one branch, not two. `plan/` merges itself, so nobody sees this. To see it, with the test module's `AUTO` settings: `judge('plan/x', {path(): text(row(tag='risk'))}, {path(): text(row())}, cfg=AUTO)` gives `[]`, and a second plan branch accepting that row gives `[]`. Relabelling `class` into a listed class gives `[]` too. It is latent while `auto_apply` is empty, but it must be closed before anyone fills that list. Fix: on an existing row, `plan/` may not remove or change `tag`, or change `class`, with a test per forgery.

**Should-fix 2: the guard is off when the registry is not in `[storage] dir`.** `warscape/policy.py:109` sets `proposals_dir` from `[registries]` alone, and the guard reads only that folder. A game that declares the registry and forgets `[storage] dir` stores rows in `registries/proposals.jsonl`, which `proposal_problems` never looks at, and nothing refuses the config. To see it: `settings` with `storage.dir` lacking `proposals`, then `job/W1` adding an answered row to that file: no proposal line among the errors. `meta/` reaches it as well (`registries/*`). In the core itself the second-copy check in `warscape/registry.py` stops this; a game has no such stop. Fix: refuse the config (`proposals` declared but not in `[storage] dir`), so the failure is closed, as the rest of the guard is.

**Should-fix 3: a `decide/` branch can rewrite or delete an earlier ANSWERS file.** `warscape/policy.py:383` allows `p == record` without asking that it be added. Brief decision 4 says "one added". A branch named `decide/<date>` reused after that date's round merged passes with the quotation changed (`judge('decide/2026-11-06', {ANS: 'old quote'}, {ANS: 'new quote'})` gives `[]`), and with it deleted (head `{}` gives `[]`). The verb's `write_text` in `warscape/proposals.py` overwrites too. This file is the only record of Liam's words. Fix: refuse when the base has the file, and in `answer` when it exists; the message names `decide/<date>-2`.

**Should-fix 4: `docs/AUDIT_METRICS.md:17` still lists the subject kinds without `decide`.** The code learned it in `subject_kind`; the owner of the rule did not.

**Later** (filed as rows, see below; none block):
- `warscape/proposals.py:32` hardcodes the registry name `decisions`, though `[policy] decisions = "registry:<name>"` is what `docs/PROPOSALS.md` tells a game to declare. Another name is a `KeyError` in `apply_rows`, and in `check`, so in the `jobs` gate. Read, not run. Napoleon's `wsc.toml` here still says `decisions = "docs/DECISIONS.md"`, so its adoption job must move first.
- `plan/` closes rows with no evidence: an accepted row as `moved` with its job not done, and a tagged open row as `gone`, each `[]` from the judge. Brief decision 5 allows closing, so this is no deviation, but a self-merging branch can drop a question before Liam sees it, or lift a decline's suppression.
- A `decide/` branch may rewrite a row's question and options in the commit that answers it (`[]` from the judge): the record then says Liam answered a question he was not asked. Liam reads the pull request, so this is a small risk.
- `newest_by_finding` (`warscape/proposals.py:74`) breaks a same-date tie on the random id, so a row re-raised on the day of its parent can lose to it; `draft` then writes a second live row and `check` refuses. It fails closed. Read, not run.
- `max_questions` is in no doc (`[audit]` keys: `docs/AUDIT_METRICS.md` "What a game sets", `docs/PROPOSALS.md`).

**Notes on the report.** "`proxy` skipped, correctly, as no proxy input changed" is loose: `wsc.toml` is a proxy input and did change. The skip is right because `proxy` passed on that input in run 42184328431. The report's open questions 3 and 4 are W47's; question 5 (merge skew, the core #135 failure) is Liam's and stays open here.

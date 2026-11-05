# W40 review

## Round 1 (2026-11-05, branch job/W40 at 29b5c8b)

**Verdict: merge after fixes.**

The key, the routing, the C24 behaviour and the scan all hold up. One thing stops a merge: deviation 1 clears a rule A hit by a commit's position in the log, not by whether the fresh round could have seen it, so code round 2 never saw is cleared. This reviewer changed no code; the finding goes to a fix session.

### Findings

**Should-fix 1: a fresh round clears code it never saw.** `warscape/policy.py:391` clears a commit when any newer round's review commit comes later in `reads.commits()`. That list is `git log --reverse --topo-order`, and position in it says nothing about ancestry on a branch with a merge.

- **What fails:** round 1's session commits code locally while round 2 is pushed, then runs an ordinary `git pull`. The merge's first parent is the code, so the log lists the code before round 2's review commit, and rule A says nothing, at `error`.
- **How to see it fail:** on a real temporary repository (`warscape.policy.GitReads`, `reviewer_code = "error"`): a builder commit; `R1` writes round 1 `merge`; a side branch where `R2` writes round 2 `merge`; back on the job branch `R1` commits `late.py`; `git merge --no-edit` the side branch. `git merge-base --is-ancestor <late> <round 2>` says no, the order is S1, R1, R1 (late), R2, merge, and `round_problems` returns `([], [])`.
- **Why it matters:** the report says "Code pushed after the fresh round is still a hit", and C36 and `docs/REVIEW.md` rest on the fresh round having reviewed the change. This is new in W40 and is the part the report asked to have reviewed hardest. The topology is narrow, but the fix is small and the gate is the one that decides what reaches `main`.
- **Fix:** clear a commit only when it is an ancestor of the newer round's review commit: a method on `GitReads` (`git merge-base --is-ancestor`, as `_ok` already allows), with `fake_reads` keeping today's order. Add the case above as a test on a real repository: `tests/test_policy.py` `PolicyOnGit` or `tests/test_policy_base.py`. The fake reads cannot show it.

**Later 1: a round's own later edit clears code that came before it.** Steps at `error`: R1 `merge`, R2 `merge`, R1 code, then R2 edits only its own round. Result `([], [])`, though `test_code_after_the_fresh_round_is_not_cleared_by_it` reads as if this cannot happen. The code is an ancestor of R2's edit, so the fix above does not change it, and R2 could have read it. Say so in C36 or the fix report, or tighten it if that is cheap.

**Later 2: open question 2 is real and wider than finding 1.** Confirmed at `error`: R1 `merge after fixes`, R2 `merge`, then R1 code gives `([], [])`. It predates W40, the report names it, and leaving it out of this job was right. But `docs/REVIEW.md` now says such code is refused, so it needs the later job the report recommends, and a line in `docs/BACKLOG.md` when that can land.

### Checks

- **Machines:** `python3 wsc.py gates` on 2026-11-05, Windows, at 29b5c8b: 14 ok, 2 warn, 0 failed, 1001 host tests passed, 5 skipped. The extra warn against the report is `hooks`, because this worktree's `core.hooksPath` is an absolute path. `python3 wsc.py policy --branch job/W40 --base origin/main` refused only for the missing review and the row, with the expected note on the rule inputs and the `job/W900` fixture warning.
- **CI:** all 9 checks on 29b5c8b passed or skipped (`wsc jobs review`). Run 41930930530 is `gates`, success, on d119bf7, as the report says.
- **Scan, re-run 2026-11-05 with `wsc policy --scan --rule A`:** core 32 judged, 6 hits (W4, W6, W19, W24, W29, W37); since 95f0269, 5 judged (W35 has merged), 1 hit (W29). Napoleon 65 judged, 28 hits, 0 not judged. The rule A numbers match the report; the branch counts are one higher in each repo because one more branch has merged in each. The kill criterion is not met.
- **Red first:** the red-tests commit 55d5e39 fails as claimed in `tests/test_policy.py`: 8 failures and 7 errors. `tests/test_policy_base.py` would not load from my export, so the report's 13 and 11 are only part-reproduced. Its CoreMode tests are green in the gates run above.
- **C24:** `test_w40_a_head_that_flips_the_key_is_judged_with_the_bases_value` and `test_w40_a_warn_base_stays_a_warning_when_the_head_says_error` pass. `reviewer_code` is read from `settings(config)`, the base's config in the judge; `JUDGE_API` is unchanged.
- **Brief:** the key, its default, the core at `error`, wording, file set (`ok` is untouched) and the scan as a mode of the verb are all present. The scan's `gh` call is injected and the pure parts and the not-judged exit are tested. `docs/DECISIONS.md` is outside the brief's scope, and the report names that and says why. Deviation 1 is outside the brief too, but it is needed: I agree a stranded `merge` round could not be cleared without it.
- **Risk-first reading:** I picked `round_problems` and its interaction with rules B and C, because a mistake there lets unreviewed code reach `main`. A phantom round cannot be used to clear a hit: round 2 written and then withdrawn at the head is refused whoever withdraws it (the same session by rule B, R1 or a third session by rule C, no trailer by the trailer rule).
- **In-flight branches, re-checked 2026-11-05:** the report's "only a brief" is out of date, since W31, W34, W36 and W39 now have review rounds claimed. `wsc policy` printed no rule A line for any of them. W34 and W36 are ok. W31 and W39 are refused for other reasons, not rule A.

### For the fix session

Answer should-fix 1 and the two later items in `## Fix round 1` of `report.md`.

### For Liam

Open question 1 (merge now, or wait for reviewers to use `merge after fixes` for a while) is yours. Nothing in this review argues for waiting: going to `error` early costs little, and setting the core's key back to `warn` is one line.

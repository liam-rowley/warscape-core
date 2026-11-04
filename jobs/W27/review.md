## Round 1 (2026-11-04, branch job/W27 at de6207d)

**Verdict: merge.**

Checked cold against the brief, not the report. Machines: `python3 wsc.py gates` on this checkout, 2026-11-04: 13 ok, 2 warn (hooks wiring of this worktree; 5 skipped
tests needing capstone or a POSIX sh), 0 failed, 785 host tests. CI run 41892054570 on the head: gates (ubuntu-latest) green; windows gates and harness were
still running when I wrote this, so auto-merge decides on them. `wsc policy --branch job/W27 --base origin/main` (judged with origin/main at 6e743da, core 0.33.0):
refused only for the missing review and the row not yet `done`, which this commit fixes. VERSION 0.34.0 and C29 are free on main (main has 0.33.0 and C28); main is
an ancestor of the head, so no merge was needed.

I also ran the new claim for real: `wsc jobs review --id W27` pushed the claim ref for round 1 to GitHub and printed "Claimed round 1 of W27", which confirms the
report's probe (GitHub accepts the ref). The claim is released by the next `jobs review` run once this round is on the branch.

Risk-first reading: `warscape/policy.py` (rules A-F, `GitReads`, `check()` wiring) because it is the gate for what reaches main, and `warscape/claims.py` because it is
the only new write to the remote. Read both in full, plus the `jobq.py`/`verbs/jobs.py` wiring and the pre-push hook change.

What I checked and found sound:
- `check()` stays pure; every git read is by sha at the clone; nothing imports or runs a head file (C24); `JUDGE_API` unchanged.
- Rule B (error) compares sessions of the commits that wrote each round, minus the builder's, for every earlier round; a missing trailer still fails closed through
  the old rule. Rule C (error) checks head against base and every `review.md` commit in order; a rewrite then restore is refused at the rewrite, a delete is
  refused for an earlier round, and a different session editing the newest round is refused. Rule D errors only for a run folder missing from both trees; branch and
  sha cites warn. Rules E and F match the brief; F's regex is anchored so `W2` does not match `W27`.
- Claim: the claim commit has the head as parent and the session and time in its message, so two claimers push different non-fast-forward commits and git refuses the
  second; a stale takeover deletes with a lease on the old sha, so two takeovers cannot both win (the loser raises `ClaimError`, fail closed). An unreadable origin
  refuses; `--offline` claims nothing. The pre-push skip applies only when every pushed ref is a claim ref.
- Bootstrap trigger removed from `ci/policy.yml.in` and the rendered workflow; `ci_render` is clean.

Deviations: rule A became a warning and rule D's branch cites became warnings under the brief's kill criterion, after the report's scan of merged job branches (32 and 13
beyond the audit's list). I accept that: the kill criterion says exactly this, the report names it in Deviations and Open questions 1, and the warning text names the
commit, the path and the fix. The consequence, stated plainly for Liam: today the audit's headline repro (reviewer code under `merge`) ends `ok` with a warning, not
REFUSED. The scan script was not committed, so I could not re-run it over the merged branches; the per-rule counts rest on the report. The "merged" test for a cited job
branch (a `done` row on the base, because every job squash-merges) is a sensible extension and is documented.

### Findings

**Should-fix (follow-ups; none blocks the merge)**
1. `warscape/claims.py:44` `session_name` falls back to `user@host`. Two reviewer chats on one machine without `WSC_SESSION_ID`/`CLAUDE_CODE_SESSION_ID` share that name,
   and `take` treats the same session as the holder, so the lock silently fails open for them. Claude Code sets the variable (it is set in this session), so the risk is
   a hand-run `jobs review` in a plain shell. Fix: add a per-process random suffix to the fallback, or refuse to claim with no explicit name.
2. `warscape/claims.py` `take`: a claim whose commit time cannot be read gets `when == 0` and is treated as stale at once (`if c.when and ...`). Unreachable after a
   successful fetch, but unknown age should fail closed (live), not open.
3. Rule A is warning-only (see above). Open question 1 of the report (a later job makes it an error, or a `[policy]` key a game can set) is the right follow-up; a key
   would let Napoleon turn it on now.

**Later**
4. The false-positive scan should be a committed, host-tested tool so the warn/error split can be re-measured as the warnings are worked down.
5. The report says no existing caller or test changed, but two verb tests now stub `print_claims` and `take_claim` (the report does say so under Evidence). Cosmetic.
6. A stale worktree (`job-W27r`) holds `job/W27`, so `git checkout -B job/W27` failed for this reviewer; I reviewed on a local branch `w27-rev` tracking it and push the
   head to the job branch by refspec. Worktree housekeeping, not a code finding.

Game repos (from the report, confirmed): Napoleon's pin bump sets `decisions_cite_job = true`; its hook must allow pushing and deleting claim refs.

# W40 report: Rule A (reviewer code under a merge verdict) becomes an error

W40 adds `[policy] reviewer_code = "warn" | "error"`, default `warn`, and sets the core's own `wsc.toml` to `error`, so a `merge` round over reviewer code is refused here while a game keeps the warning until it opts in. The scan supports the key over outright: 1 core hit since W27 (kill criterion: more than 3), though that sample is nearly empty (see the scan). It also adds one change the brief did not ask for: a fresh round now clears a stranded `merge` round, because without that the error could never be cleared. W27's scan is now a committed tool, `wsc policy --scan`. Branch `job/W40`, session 71f2c148.

## The scan (before any code)
Run 2026-11-04 with W27's method: every merged `job/` pull request judged at its head against its merge commit's first parent, gate modules off, rule F on. The first run was a scratch script, before any code; `wsc policy --scan` then gave the same rule A numbers.

| Repo | Branches judged | Rule A hits | Merged since W27 | Rule A hits since W27 |
|---|---|---|---|---|
| core | 31 | 6 (W4, W6, W19, W24, W29, W37) | 4 (W28, W29, W26, W15) | 1 (W29) |
| napoleon | 64 | 28 | 0 | 0 |

- **Core, the one hit:** W29, a reviewer's `merge` over code (`warscape/release.py` and its test, session bf405dba, attributed to round 1; `wsc policy --scan --rule A` prints the sha). That review was committed at 18:54 UTC and W27 merged at 20:22, so the reviewer could not have seen the rule. It counts under the brief's definition (merged after 95f0269), but it is not a reviewer ignoring it.
- **Do reviewers now write `merge after fixes`? The scan cannot say yet.** Passing the criterion is not evidence of a change in behaviour. W27 merged at 20:22 UTC and this scan ran the same evening, so almost no round was written with rule A on `main`: W15 (18:24), W26 (19:05), W29 (18:54), W28's round 1 (18:40) and open W35's rounds (19:06, 20:19) all came first. Only W28's round 2 (20:23, 20:25) came after, and it wrote no code. Liam's condition was "after reviewers have used `merge after fixes` for a while"; that has not happened yet. See open question 1.
- **Napoleon's 0 says nothing.** Its pin is core 0.10.0 (`c242f2f`), so no pin bump to 0.35.0 or later exists and rule A has never run there. No napoleon `job/` branch merged after core W27 by time either (`--since 8e6eb72`, its main at that moment). Its total is 28 against W27's 27.
- **Napoleon's 28 overstates it:** 11 of them (J1, J13, J18, J19, J20, J22, J40, J45, J52, J54, J56) changed only `registries/jobs.jsonl` and `registries/jobs.md`, the job's own row before rows moved to one file each (J55). They cannot recur.
- **Rule D (open question 2), since W27:** 2 of 4 branches. W26's are branch cites; W29's is a commit cite. Over all 31: D 12, E 2, B, C and F 0.

**Choice: the key, default `warn`, the core at `error` (decision 1).** The kill criterion is not met (1, not more than 3). Outright needs 0 hits in both repos, and the core has 1.

## What was built
- **Key:** `reviewer_code` in `DEFAULTS` and `load_config` (`warscape/repo.py`), read by `settings` in `warscape/policy.py`; `wsc.toml` sets `error`. A bad value is a `ConfigError` naming the key. The base's config decides (C24), so `JUDGE_API` is unchanged.
- **Rule A:** `round_problems` sends its line to `errs` or `warns` by the key, with the wording unchanged (decision 2) and the file set unchanged (C28).
- **A later round clears what it follows** (deviation 1): a commit followed by a newer round's review commit is no longer a rule A hit.
- **Scan:** `wsc policy --scan [--repo DIR] [--base REF] [--since REV] [--rule A-F]`, a mode of the existing verb. The `--rule` flag covers all six rules (open question 3). It exits 1 if any branch was not judged, because a count that left one out is not a number to decide on. It reads the target's `wsc.toml` through `scan_config`, since napoleon's is too old for `load_config` (`[jobs] hooks`). A head whose branch was deleted is fetched as objects only (no ref, no `FETCH_HEAD`).
- **Docs:** `docs/REVIEW.md` "Output", `docs/CONSUMING.md` `[policy]` block (30,618 bytes after merging W35, under the 30,720 cap), the module docstrings, the `wsc.policy` tool row, decision C36. `README.md` does not state rule A.

## Evidence
- **Red, then green:** `tests/test_policy.py` and `tests/test_policy_base.py`, on Windows with the local Python 3.15.2 (CI is the run on the project's version). Red committed first: 106 tests, 13 failures and 11 errors. Green after the build: `Ran 106 tests ... OK`.
- **Full gates:** `python3 wsc.py gates`, 2026-11-04 on Windows, after merging W35: 15 ok, 1 warn, 0 failed; 1001 host tests passed, 5 skipped (the warn is the skips: no POSIX sh for one hook test, no capstone for four).
- **Branch CI:** `gates` run 41930930530 on `d119bf7`, 2026-11-04: success (`gates` on windows-latest and ubuntu-latest, `harness-windows`, `proxy`). That head holds all the code; the commits after it add this report, the row, C36 and a merge of W35. The `policy` check skips drafts, so it runs when the reviewer marks the pull request ready; locally `python3 wsc.py policy --branch job/W40 --base origin/main` is refused only for the missing `review.md` and the row not being `done`, as the brief expects of a job in progress.
- **The repro, real `wsc policy` verb on a temporary repository** (round 1's reviewer commit changes `docs/REVIEW.md` and writes `merge`):

```
--- reviewer_code = "error": exit 1
policy: judged with the rules of origin/main at 0892b76 (core 0.37.0)
policy: job/W900: REFUSED (5 files changed)
policy: round 1 of jobs/W900/review.md says merge, but its own commits change files outside jobs/W900/ and its row: cb83c80 (docs/REVIEW.md): write the verdict `merge after fixes`; a fresh round reviews your change

--- reviewer_code = "warn": exit 0
policy: judged with the rules of origin/main at 1fbdb31 (core 0.37.0)
policy: warning: round 1 of jobs/W900/review.md says merge, but its own commits change files outside jobs/W900/ and its row: 6b428b2 (docs/REVIEW.md): write the verdict `merge after fixes`; a fresh round reviews your change
policy: job/W900: ok (5 files changed)
```

(Shas shortened to 7; the temporary repositories are gone. `policy` warns that this report cites `job/W900`: that is the fixture's name in the pasted output, not evidence.) A head that flips the key is still judged with the base's value, in both directions: `test_w40_a_head_that_flips_the_key_is_judged_with_the_bases_value`, `test_w40_a_warn_base_stays_a_warning_when_the_head_says_error`.

## In-flight branches (decision 3)
None is touched today. W35, the only in-flight branch with a review, printed no rule A line against `origin/main` at 209ca5a and has since merged. W31, W34, W36 and W39 held only a brief when checked. For a branch that does trip the error later, the cost depends on who is left: the round's own session changes its verdict to `merge after fixes`, or a fresh session writes a new round on top. Decision 3's "new round with the verdict changed" only works because of deviation 1.

## Deviations from the brief, and why
1. **Rule A changed in a way the brief did not ask for: a newer round's review commit clears the commits before it.** Decision 3 expected a new round to clear a refusal. On the code as it stood it could not, which I checked before building:
   - a fresh round 2 on top still tripped rule A, which reads round 1's verdict at the head;
   - a fresh session editing round 1 was refused by rule C (`only its own author edits the newest round`);
   - round 2 plus a rewritten round 1 was refused by rule C (`append only`).

   As a warning this was harmless. As an error, a branch whose reviewer session had ended could only pass by rewriting history. The change is one condition in `round_problems` and applies in both modes. It is not a kill criterion: the file set and every other rule's severity are unchanged. Code pushed after the fresh round is still a hit (`test_code_after_the_fresh_round_is_not_cleared_by_it`, `test_only_the_commits_a_later_round_follows_are_cleared`). No historical number moved: every hit in both repos is on a branch's newest round. **This is the part of the diff to review hardest,** since `policy` is the bypass surface.
2. **`docs/DECISIONS.md` is not in the brief's scope, but this adds C36.** C30 says rule A warns, and this job changes that for the core and adds the clearing behaviour.
3. **The first scan ran as a scratch script,** as step 2 requires (before any code), and the tool came after. The brief's `--since` for napoleon ("after its pin bump to 0.35.0 or later") has no such commit, so I used its main at the moment core W27 merged.

## Open questions
1. **Is it too early to merge this? Liam's call.** The brief's number passes, so I built it, but the condition behind that number (reviewers using `merge after fixes` for a while) has had about two hours and one review round to show up. Recommended: merge anyway. Being early costs little, since only the core's own reviewers are affected, the fix is a verdict change or a fresh round, and `wsc policy --scan --since 95f0269 --rule A` can re-measure at any time. If Liam would rather wait, setting the core's `reviewer_code` back to `"warn"` is a one-line change and keeps everything else.
2. **A gap in rule A that predates this job, not fixed here.** A round-1 session that wrote `merge after fixes` can push code after round 2's `merge`, and rule A says nothing, even at `error`: the commit is attributed to round 1, whose verdict is not `merge`. Confirmed with the steps R1 `merge after fixes`, R2 `merge`, R1 code, which gave `([], [])`. Deviation 1 does not widen it, because it only removes hits. Recommended: a small later job that judges such a commit against the newest round. I left it out because it changes what rule A attributes, which the brief did not ask for.
3. **Should rule D's branch cites follow?** The brief recommends no, and I agree. Since W27, 1 branch of 4 cites a branch (W26, whose cite the scan reports as not in this clone); the same timing caveat applies.

## What napoleon must do after the tag
Nothing is forced. Its pin is at 0.10.0, so it meets rule A for the first time at its next bump, as a warning. It may set `[policy] reviewer_code = "error"` in a pin-bump commit, once its open `merge` rounds are done; until then rule A stays a warning there. `python3 core/wsc.py policy --scan --rule A` gives it the count first.

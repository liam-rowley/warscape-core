# W31 review

## Round 2 (2026-11-05, branch job/W31 at 7166f9d)

**Verdict: merge.**

Every blocker and should-fix item of round 1 is answered in `## Fix round 1`, and I checked each against the tree rather than the report. `main` at b8ecfb7 is an ancestor of the head, so the gates below ran on what will merge. This round changes only this file and the job's row.

### Round 1's findings

- **Blocker 1 (C35, the merge):** answered. `git merge-base --is-ancestor origin/main HEAD` holds, and pull request 109 says `MERGEABLE`, `CLEAN`. `docs/DECISIONS.md` has this job's row as C39 after main's C35 to C38. No open `plan/` branch (pull requests 114, 119, 121) has a C39 or later row, or a B104 or later row. The only "B88" and "C35" left in the report are in `## Fix round 1`, which explains the change.
- **Blocker 2 (`registries/tools.jsonl`):** answered. The `registries` and `tools` gates are ok. The merge's combined diff keeps one row of `wsc.jobs` with this job's text and one of `wsc.policy` with main's.
- **Blocker 3 (`docs/CONSUMING.md`):** answered. 30,713 of 30,720 bytes on the merged tree, and `doc_size` is ok. The two passages it dropped are owned by `warscape/jobq.py`, as the report says: `MARKED_URL` at :1298 and the policy docstring at :1305.
- **Should-fix 1 (model id):** answered. `--from-json` with `claude-opus-5-5` exits 1 naming the value and `[jobs] models`. `Opus` writes `opus`, and `opus-5-5` is taken, which agrees with the rule's first-word compare. A game's own `[jobs] models` reaches the check: `haiku` is refused by default and taken once listed.
- **Should-fix 2 (backslash):** answered. A backslash in `usage_cmd` stops `wsc` with the config error, in both TOML string forms. The sentence in `docs/USAGE.md` is gone.
- **Should-fix 3 (Usage line):** answered, see the numbers below.
- **Later 1 and 2:** B102 and B103 are on `plan/w31-review-later` (pull request 121), which is open. This job does not depend on them.
- **`main` red on `proxy` (run 42066067742):** cleared. Attempt 2 of that run is success on every job.

### Findings

No blocker and no should-fix.

The report's hand count is low by 5. Session 9756d055's transcript holds 54 tool calls, all on `claude-opus-5-5`, against "about 49"; with the build's 87 that is 141, not 136. The report says the count was taken before its last calls and that no reader measured it, which is what the brief's acceptance asks for. Both numbers are far below the 187 the rule allows, and W31 is under `usage_from`, so I leave the line as it stands.

### What I ran (2026-11-05, on this PC, at 7166f9d)

- **Gates:** `python3 wsc.py gates`: 15 ok, 1 warn, 0 failed; 1137 host tests passed, 5 skipped (a POSIX sh with symlinks for one, capstone for four: the `tests` warn).
- **Policy before this round:** refused only for the missing merge verdict and the `done` row. The branch changes `warscape/gatemods.py`, `gates.py`, `jobq.py`, `repo.py`, `verbs/jobs.py` and `wsc.toml`, so `policy` notes them; their new rules are proven by the host tests, and none of them is `warscape/policy.py`.
- **CI:** run 42078112387 at 7166f9d passed `gates` on both systems, `proxy`, `harness-windows` and `changes`; `wsc jobs review` printed all 9 checks passed or skipped. No workflow changed.
- **Fixtures, on a throwaway copy:** the model check disabled fails `test_a_bad_record_is_refused`, and the backslash guard disabled fails `test_bad_values_are_refused`, as the fix round says. The ceiling at 1.5 x still goes red on the merged code. `tests.test_usage` and `tests.test_jobs.UsageRule` passed on the unchanged copy first.
- **Acceptance:** `parse_usage` reads 136 calls and `opus` from the report, and `brief_budget` gives 150. With `usage_from = 31`, `usage_problems` is empty for W31 and fails only the `done` rows W33 to W40, which merged without a line. That is five rows more than round 1's W33, W37 and W38, because W34, W35, W36, W39 and W40 reached this tree with the merge of `main`; `usage_from = 42` in `wsc.toml` exempts them all. `git log --all -- registries/jobs/W42.json` is empty, so no W42 row exists on any ref and 42 is still the first free number. `jobs view --offline` draws `usage 136 / 150 calls · opus`.
- **The Usage line's numbers:** the build session's transcript holds 87 tool calls, as the line says, and the fix session's 54, as above.
- **Read in depth, as the code that changed since round 1 and that every game's queue reads:** the fix commits 9e8ee38 and 0dbd030, the combined diff of merge 0133efa for `registries/tools.jsonl`, and `warscape/verbs/jobs.py` against `main` (the `usage` action, the bare-id guard). Round 1 read the rule and `--write` in depth, and they have not changed since, so I did not repeat that.
- **The brief:** no kill criterion fired. `wsc.toml` sets `usage_from = 42`, and `jobs check` on the core's own queue is ok. I did not probe the report's open question 3 (`jobs next` reading the working tree's rows).

## Round 1 (2026-11-05, branch job/W31 at e12011e)

**Verdict: merge after fixes.**

The code does what the brief asks, and I found no defect in the rule, the verb or the view. The branch cannot merge as it stands: it is 8 commits behind `main`, it conflicts in two docs, its decision number is taken, and the merged tree fails two gates. All of this comes from the branch being behind. CI could not show it, because the gates run on the branch's own tree and a draft skips `policy`. This round changes only this file and the job's row.

### Blockers

1. **`docs/DECISIONS.md:43`: C35 is taken, and the branch does not merge.** `main` at b8ecfb7 has C35 to C38, so `python3 wsc.py policy --branch job/W31 --base origin/main` refuses with `docs/DECISIONS.md is append only: rows C35, C36, C37, C38 were changed, moved or removed`. `git merge-tree --write-tree --name-only HEAD origin/main` reports content conflicts in `docs/DECISIONS.md` and `docs/BACKLOG.md`. Merge `origin/main`, keep main's rows and put this job's row after them under the next free number (C39 at b8ecfb7; read `main` again when you do it). Change the C number nowhere else: only `docs/DECISIONS.md` carries it. B88 is free on `main` but not in flight: open pull request 114 adds B88 and B89, and 119 adds B96 to B101. Give this job's row the next number free across `main` and the open `plan/` pull requests (B104 once this review's own rows are counted), and change every "B88" in `jobs/W31/report.md` to match.
2. **`registries/tools.jsonl`: the merge leaves the registry and the tools gate red.** A trial merge of b8ecfb7 auto-merges this file with no conflict. `python3 wsc.py gates --fast` on that tree then fails `registries` (`duplicate id 'wsc.jobs'`, `duplicate id 'wsc.policy'`, not canonical) and `tools` (`warscape/verbs/jobs.py: row differs from the file header in usage, when`). Keep one row of each and rerun `wsc reg add tools warscape/verbs/jobs.py`. Check that the `usage:` and `when:` lines hold both main's text and this job's.
3. **`docs/CONSUMING.md:175`: the merged file is over the cap.** `main` has it at 30,711 bytes and this line adds 154, so the merged file is 30,865 of 30,720 and `doc_size` fails. Deviation 1 assumed 30,507, which was true before `main` moved. Make room in the file (shorten something, or move a passage to the doc that owns it). Then read the size from the merged tree, not the branch.

### Should-fix

1. **`warscape/jobq.py:329`: `usage_record` takes a model id that `jobs check` then refuses.** `{"models": ["claude-opus-5-5"]}` passes the check. `wsc jobs usage --write` writes `models: claude-opus-5-5`, and `usage_problems` calls that a mismatch with the row's `opus`, because `model_family` gives `claude`. Probe output on 2026-11-05: `usage model claude-opus-5-5 is not the row's model opus`. Decision 1 says models are family names, and decision 3 makes any other answer an exit 1. It will bite: per the brief, napoleon's `usage_reader.py` keys `models` by model name, and B88 does not say to map them. Refuse a model whose family is not in `S.models` (`[jobs] models`), name the bad value, and add a case to `Record.test_a_bad_record_is_refused`.
2. **`warscape/jobq.py:356`: the backslash trap is prose (`docs/USAGE.md`, "Write its paths with forward slashes").** A Windows game's `usage_cmd = 'python3 tools\reader.py'` loses the backslash in `shlex.split`, and the reader then fails on a path nobody wrote. Refuse a backslash in `usage_cmd` in `load_config`, beside the type check at `warscape/repo.py:197`, with a case in `Config.test_bad_values_are_refused`. The sentence in `docs/USAGE.md` then goes.
3. **`jobs/W31/report.md` Usage line.** The fix session counts too (decision 1, and this job's own `fix_steps`). Rewrite the line with the build and fix totals, as `--from-json`, and say the numbers are by hand. W31 is below `usage_from`, so no gate holds you to it, but the brief's acceptance does.

### Later

1. **`warscape/jobq.py:1265`: no chip on a job in review.** This is the report's open question 1: `card()` reads the working tree, so the lane where budget matters most shows nothing. Into `docs/BACKLOG.md` (B102, branch `plan/w31-review-later`).
2. **`wsc jobs review` says all checks passed on a branch that cannot merge.** On this job it printed `all 9 checks passed or were skipped`, and a review round went on a branch that `policy` refuses. A `git merge-tree` test in `jobs review`, and in the `--auto` start, would send it to a fix session first. Into `docs/BACKLOG.md` (B103, same branch).

### What I ran (2026-11-05, on this PC, at e12011e unless stated)

- **Gates:** `python3 wsc.py gates`: 14 ok, 2 warn, 0 failed; 995 host tests passed, 5 skipped. The report's 15 ok and 1 warn differs only by the `hooks` warning, which comes from this worktree's absolute `core.hooksPath`.
- **Policy:** refused as in blocker 1, plus the two refusals every branch has before its merge verdict.
- **Trial merge with origin/main b8ecfb7** (never committed, then undone): blockers 1 to 3 come from this tree. `tests.test_usage` and `tests.test_jobs` still passed on it, 214 tests, so the code itself survives the merge.
- **CI cited by the report:** run 41927317973 is red at f5d7d31; run 41928676211 is green at 1b50727 on `gates` for both systems, `proxy` and `harness-windows`. e12011e adds only the report and the row, as stated, and `wsc jobs review` shows its checks passed or skipped.
- **Fixtures:** I reapplied three of the report's six (the 1.5 x ceiling, the case-sensitive model, `usage_from` ignored) and nine of my own, one at a time: fence ignored, card text unescaped, chain check dropped, oldest lift used, status check dropped, `shell=True`, bools counted, `problems` not calling the rule, the bare-id guard dropped. All twelve went red.
- **Acceptance:** with `usage_from = 31` in the working tree (restored after), `jobs check` reports only W33, W37 and W38, as the report says, and nothing for W31. `jobs view --offline` draws `usage 85 / 150 calls · opus`.
- **The Usage line's numbers:** session 4efda02d's transcript holds 87 tool calls, all on `claude-opus-5-5`. The hand count of 85 was taken before the last calls of the session, so it is honest and within budget.
- **Read in depth, as the code a game's queue depends on:** `usage_problems`, `lift_problems`, `set_usage_line`, `paragraph_end`, `run_usage_cmd` and the `problems` call. I chose these because a wrong rule blocks every game's `jobs check` and `--write` edits a report. Edge inputs behaved: CRLF, no final newline, a title with no paragraph, `W5` against a `W51` heading, a note with a newline and a second `Usage:` in it, junk lifts, malformed cards.
- **The brief:** all nine decisions are present, and no kill criterion fired. The seven deviations are named with reasons, and I accept them apart from the number in deviation 1 (blocker 3). No brief on this branch states two budgets, so `brief_budget` taking the first match bites nothing today. No workflow changed.
- **`main` is red** on `proxy` (run 42066067742). That is unrelated to this branch, but a later `merge` round must see it cleared or rerun.

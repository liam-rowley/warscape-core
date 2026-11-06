# W41 review

## Round 1 (2026-11-06, branch job/W41 at 2c63ab4)

**Verdict: merge.**

No blocker and no should-fix. The cap rule Liam chose holds against the real session list and the real processes on this PC. Three later items go to a `plan/` row; one needs W46's attention.

### The cap rule against the real list (Claude Code 2.1.319, read 2026-11-06)
- `claude agents --json --all`: 181 rows, 310 ms. background 180 (done 158, stopped 16, working 3, blocked 2, failed 1), interactive 1.
- `capped_sessions` returned 3: J32-build (pid 11688), W45-build (22472), W41-review (21956). It left out the interactive row, which has a pid (11268), and the two `blocked` rows with no pid (J64-build, W41-build).
- Those 3 match the processes. `Win32_Process` showed four session `claude.exe`: the 3 counted and the interactive one. The others are the daemon and one `--bg-pty-host` per session (94 to 131 MB each, not counted: the rule is a count, D59). J64-build and W41-build have no process, as answer 3 says.
- The real launch path, dry run, on the live list (`JobServer.start`, only `not_ready` stubbed): cap 0 gives 200; cap 3 gives `429 refused: 3 of 3 background sessions are live (J32-build, W45-build, W41-review); wait or run wsc jobs sessions --stop-finished`; cap 4 gives 200. `next_sessions` at cap 3: plain says wait, `--id` goes on. This closes the report's "the refusal at the cap ran only against stubbed lists".
- A throwaway session of this review's own (`cap probe w41r1`, id f02517ef, haiku, one word, left in the list as `done`): `claude --bg` returned in 0.9 s; `working` with no pid at +0.3 s; pid 9968 at +1.2 s; `done`, status `idle`, pid still there at +5.2 s and still there past +45 s. `stop_finished` with the real `stop_session`, given only that row, stopped it: the row stayed `done` and the pid cleared. That is answer 4 through the job's own code, which the build did not run. No other session was stopped.

### Machines
- `python3 wsc.py policy --branch job/W41 --base origin/main` before this round: only the two refusals a review clears (no review yet, row not done); judged with main's rules, and the branch changes `warscape/jobq.py`, `repo.py` and `verbs/jobs.py`, so its rules are proven by the host tests.
- `python3 -m unittest tests.test_jobs` at 2c63ab4: 174 tests, OK. Red first, checked: the branch's test file on main's code (adf9b1a) gives 37 failed or errored, 36 of them in the six new classes, which is the report's number; the 37th is `BranchRows`, because that copy had no `.git`.
- No old assertion changed: the test diff removes no line (the kill criterion).
- CI: run 42182495196, cited by the report, is `gates` success at b836059. At the head, run 42184071869: `changes` and `gates (ubuntu-latest)` pass; windows, `proxy` and `harness-windows` are skipped on the draft and run on the ready head before auto-merge.
- `python3 wsc.py gates` at 2c63ab4 on this Windows PC, 2026-11-06: 14 ok, 2 warn, 0 failed; 1319 host tests passed, 5 skipped. The warnings are the hook path in this worktree and the skipped tests (no POSIX sh, no capstone).

### Against main
- `git merge-base origin/main origin/job/W41` is adf9b1a, main's tip, so the head already holds W44, #135, #143 and #144, and head's gates are the merged result. Main's ruleset has `strict_required_status_checks_policy: false`, which is how #135 passed alone: a green head proves nothing once main moves. Fetched again after the gates, just before this round was written: main is still adf9b1a.
- The other open pull request, #140, touches only `proxy/`. W45 is building and shares five files. A trial merge with `job/W45` at 53d431b: `warscape/jobq.py`, `repo.py` and `docs/CONSUMING.md` merge clean, `docs/CONSUMING.md` comes to about 30,697 bytes (cap 30,720), and `docs/UPGRADING.md` conflicts because both add a section at the top. Git refuses that one, so it cannot land silently; W45 merges main and keeps both sections.

### The brief
Every deliverable is present, the six test classes cover each case of deliverable 4, and the out-of-scope items were left alone. Decisions 1 and 4 changed by Liam's answers. The `next --id`, unreadable-lock, background-rows-only and not-run-on-the-PC deviations are named with reasons and are sound; `next --id` has to go on, or a full cap would stop the session it had just let in.

### Risk-first reading
I picked `stop_finished`, since it ends processes, then `capped_sessions` and `auto_tick`, since a wrong count stalls the queue or runs the PC out of memory, then `read_pc_lock`.
- `stop_finished` calls `claude stop` only on `state == 'done'` with a pid, and `claude rm` appears nowhere; `_claude` turns a timeout or OS error into the `ValueError` the pass catches, so one failed stop does not end it.
- Every reader of the `--all` list other than the cap filters on `LIVE_STATES` (`start`, `auto_tick`), so `done` rows do not reach the same-name or PC holder checks.
- `auto_tick` adds each start to its own copy of the list, dry runs included.
- `read_pc_lock` on napoleon's real harness (`core/harness/job.sh status`, read-only) returned `{owner: j32, purpose: "J32 S3 and S4", age_s: 100, stale: false}` and `pc_busy` None; the same lock with purpose `acceptance pass` defers. In the core it returns None. `job.sh` finds the adapter from its own path, so the cwd does not matter. With the watcher down it exits 1, so `--auto` holds `needs_pc` starts until the watcher is back, as the report's deviation says.

### Findings

**Later** (filed as `later` rows on a `plan/` branch):
1. `warscape/jobq.py` `capped_sessions`: a session just launched is `working` with no pid for about 1 s (probe above), so a second button press in that window, or a press during a tick, sees one too few and goes over the cap by one. It is the same size of overshoot as answer 3 accepts, and `auto_tick`'s own starts are safe. Fix if it matters: the server remembers its launches for a few seconds.
2. `capped_sessions` fails open if a Claude Code update drops `pid` or `kind` (the report's open question 2). The check it recommends, "a `working` row with no pid warns", would fire on every launch because of finding 1: it must allow a few seconds, or look for no pid on any row.
3. For W46. A finished session keeps its slot: the probe's `done` row held a pid past 45 s, and nothing stops it unless someone runs `--stop-finished`. With napoleon at 4, an autopilot can sit at a full cap of `done` rows with only a log line. Before `--stop-finished` runs on a tick, check two things no one has tested: what state a session shows while it waits for a background task (if `done`, the stop ends live work), and how long a `done` row keeps its pid unstopped. Also, a `failed` or `stopped` row with a pid counts and no verb stops it; this PC has none today.

For the record, nothing to change:
- `jobs/W41/report.md` line 5 says decisions 3 and 4 changed; its deviations, and the answers, say 1 and 4.
- D59 says "sessions or subagents". The list has no rows for subagents, so a session counts as one whatever it spawns. Brief decision 1 defines the count as the list, so this is as briefed.

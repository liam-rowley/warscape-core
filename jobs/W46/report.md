# W46 report: autopilot starts briefs and builds under the session cap, with held phases

A repo can now opt in to `--auto` starting builds and briefs, in a fixed order, under the session cap, with `[jobs] auto_hold_phases` to freeze a phase. By default nothing starts that did not start before. The probe found a session waiting on a background task reads `working`, not `done`, so `[jobs] auto_stop_finished` is built (default off). All open questions took their recommended defaults. `wsc.toml` here is unchanged.

Usage: 50 tool calls; models: opus; 1 session, counted by hand, about; the probe session on haiku is not counted, 2026-11-07

## What was built
- **Keys** (`warscape/repo.py`, `auto_problem`): `auto_actions`, `auto_hold_phases`, `auto_phase_order`, `auto_stop_finished`. The loader refuses an unknown action, anything but whole numbers of at least 0 in the phase lists, a non-boolean stop key, and `build` or `brief` while `max_sessions` is 0. `Settings` and `configure_from` carry them.
- **Order** (`warscape/jobq.py`): `Candidate`, `auto_order` (one pure function), `branch_candidates`, `main_candidates`, over `AUTO_ACTIONS` (fix, review, build, brief).
- **The tick** (`JobServer.auto_tick`): reading order kept (snapshot, prune, agents, one lock read), then `fresh_main`. Per candidate: hold, restart memory, cap, main's CI (build and brief), `defer_reason`, then `start(..., family=True)`. New helpers: `defer_once`, `cap_full`, `stop_done`, `main_waits`, `brief_hold`.
- **Reading origin/main:** `main_head` (fetch, then `policy.rows_at` at the sha) and `read_at`; the verb passes them as the seams `main_head`, `main_ci` and `read_at`. Each fails closed: a server without them starts no build.
- **`brief_tags`:** tags under `## Open questions`, outside fences, either case.
- **`pc_holders`** skips `-brief` names; a brief started this tick holds nothing.
- **Stop:** with the key on, at a full cap with a candidate in hand, `stop_finished` runs once a tick and the pids are cleared in the tick's copy. A `failed` or `stopped` row with a pid is never stopped, and is named on the cap-full line and on the page.
- **Words:** `--auto` help, the verb header, the `wsc.jobs` row, the page's autopilot line (from `auto_actions`, with held phases), the idle line, the `jobq.py` docstring and the `BRANCH_ACTIONS` comment, `docs/CONSUMING.md`, `docs/CONSUMING_OPTIONS.md` "What `--auto` starts" (the owner of these rules), `docs/UPGRADING.md`.

**W123's two answers** (for the `plan/` branch that closes the row):
1. A session waiting on a background task is `working`, status `busy`, with its pid. It is not `done`, so a stop of `done` rows does not end that work.
2. An unstopped `done` row keeps its pid with no sign of letting go: it still had pid 25980 at 01:16:22, at least 19 minutes after it finished, and lost it only to `claude stop`. A finished session does hold its slot until something stops it.

**What W47 calls to add a candidate:** add its action to `repo.AUTO_ACTIONS` (its place there is its place in the order), give it a line in `PROMPTS` and `LABELS` and a rule in `not_ready`, and add its `Candidate(action, row)` to the list `auto_tick` hands to `auto_order`. If it decides on origin/main, add it to the set in `fresh_main` too.

## Evidence
Tests: `python3 -m unittest tests.test_jobs`, 2026-11-07. Red at b737acc: 235 tests, 61 failed or errored, all in the 13 new classes (AutoClaim 3, AutoDefaults 3, AutoFreshRows 6, AutoHold 4, AutoKeys 4, AutoModels 1, AutoNeverStarted 2, AutoOrder 7, AutoPc 6, AutoRedMain 5, AutoRestart 4, AutoStop 9, AutoTagged 7). Green after the build: 236 tests, OK (235 plus `AutoWiring`). No existing assertion changed; `Autopilot.make` gained `**seams` and a list of argvs.

Gates: `python3 wsc.py gates` on 2026-11-07 before the last merge of main, 15 ok, 1 warn, 0 failed; the warn is the 5 known skips (no POSIX sh for one hook test, no capstone for four). An earlier full run failed only `test_the_queue_passes_jobs_check`, as this report was on disk before its row was set. `wsc policy` refuses until a review exists, as expected before review. CI: CI_LINE.

**The probe (W123),** 2026-11-07, Claude Code 2.1.319, session `w46-probe` (id a9383abd, haiku), one `sleep 180` as a background task, read by hand with `claude agents --json --all`. Keys in the row: `pid`, `id`, `cwd`, `kind`, `startedAt`, `sessionId`, `name`, `status`, `state`, the shapes W41 recorded, so the first kill criterion did not fire.

| UTC | `state` | `status` | pid | Note |
|---|---|---|---|---|
| 00:53:11 | working | busy | 25980 | started about 00:52:58 |
| 00:55:09 | working | busy | 25980 | |
| 00:55:29 | working | busy | 25980 | `claude logs` shows `1 shell` running |
| 00:56:55 | done | idle | 25980 | the sleep had ended (due just after 00:56:00); no shell in the log |
| 01:02:34 | done | idle | 25980 | |
| 01:08:40 | done | idle | 25980 | |
| 01:09:58 | done | idle | 25980 | |
| 01:16:22 | done | idle | 25980 | last reading before the stop |
| 01:16:24 | done | none | none | after `claude stop a9383abd`: the row stays, `pid` and `status` are gone, `tasklist` has no 25980 |

**The dry run,** this PC, 2026-11-07, `python3 wsc.py jobs view --serve --auto --dry-run --no-open --interval 30`, keys set by hand in the worktree's `wsc.toml` and restored with `git checkout` (never committed). Each server was ended by `timeout`; `netstat` showed none of the three ports listening afterwards. `git ls-remote` showed no branch for W32 or W47: nothing was claimed or pushed, and no session started. `job/W141` exists now, made by session 9371181e, not by this job (see open question 6).

Run 1, `max_sessions = 4`, all four actions, `auto_hold_phases = [7]`, `auto_phase_order = [1]`, `auto_stop_finished = true`, three ticks. W141 is a row my checkout did not have yet, read from origin/main; W32's brief has a real `tag: risk` question:

```
2026-11-07 01:05:09 UTC jobs auto: on, every 30 s (dry run: nothing is started)
2026-11-07 01:05:11 UTC jobs auto: would prune dead worktree registrations
2026-11-07 01:05:18 UTC jobs auto: W32-build: deferred, its brief has an open question tagged risk
2026-11-07 01:05:18 UTC jobs auto: W141-build: dry run, would start: C:\Users\liamr\.local\bin\claude.EXE --bg --name W141-build --model opus --effort medium "Pick up job W141: git pull, then run python3 wsc.py jobs next --id W141 and follow it."
2026-11-07 01:05:50 UTC jobs auto: would prune dead worktree registrations
2026-11-07 01:05:55 UTC jobs auto: W141-build: started, waiting for the row or main to move
2026-11-07 01:06:28 UTC jobs auto: would prune dead worktree registrations
```

Run 2, `max_sessions = 3`, so the cap was full, two ticks:

```
2026-11-07 01:07:13 UTC jobs auto: would stop w46-probe (a9383abd): finished, still holding a process
2026-11-07 01:07:13 UTC jobs auto: deferred, 3 of 3 background sessions are live (W46-build, J95-build, w46-probe); wait or run wsc jobs sessions --stop-finished
2026-11-07 01:07:48 UTC jobs auto: would stop w46-probe (a9383abd): finished, still holding a process
2026-11-07 01:07:48 UTC jobs auto: deferred, 3 of 3 background sessions are live (W46-build, J95-build, w46-probe); wait or run wsc jobs sessions --stop-finished
```

Run 3, `auto_hold_phases = [1]`, two ticks, each hold logged once:

```
2026-11-07 01:07:58 UTC jobs auto: W32: held, phase 1 is in [jobs] auto_hold_phases
2026-11-07 01:07:58 UTC jobs auto: W141: held, phase 1 is in [jobs] auto_hold_phases
2026-11-07 01:08:29 UTC jobs auto: would prune dead worktree registrations
```

## Deviations from the brief and why
- **A new seam beyond the brief: `read_at(sha, path)`.** Decision 9 needs the brief's text, and the snapshot's `read` is the working tree, so a checkout that is behind would miss a tag. It reads at the tick's sha; a missing or unreadable brief defers the build.
- **A red main is one line per change, not one per job.** With 12 ready rows it would be 12 lines saying the same thing. A line comes again if main goes red after going green.
- **`pc_absent` gets a line.** `not_ready` would have dropped such a build in silence, so `main_candidates` keeps it and `defer_reason` logs it.
- **A `fix` or `review` now starts in `order_key` order, where it was by job number,** for repos that did not opt in as well. Decision 2 says so; `docs/UPGRADING.md` names it.
- **The cap-full cause is on the page as well as in the log** (`auto['stall']`): the brief says "on the page", and the page shows no log lines.
- **Phase lists refuse negative numbers,** as `max_sessions` does.
- **`docs/CONSUMING.md`** went from 30,645 to 30,699 bytes (cap 30,720), part paid by two small cuts; the detail is in `docs/CONSUMING_OPTIONS.md`.
- **A stop can come before a deferral.** The stop runs when a candidate meets a full cap, before the checks for main's CI, the PC and tags, so a stop may free a slot that this tick then cannot use. Stopping a finished session costs nothing, and a later tick uses the slot.

## Open questions
All four of the brief's questions took their recommended answers, as Liam's pickup message said.
1. **Decision 4:** the session claims, not the tick. Built that way. Default after: 2026-11-13.
2. **Decision 9:** a tagged question holds an automatic build. Built. It bites today: W32 is queued with a `tag: risk` question, so it would wait for a button. Default after: 2026-11-13.
3. **Who opts in:** napoleon at its pin bump; the core stays on review and fix through a `meta/` change. `wsc.toml` untouched here. Default after: 2026-11-13.
4. **`auto_stop_finished` on in napoleon:** recommended on. New limit for that choice: the probe read one kind of wait, a background shell, on one session. A session waiting on something else (a scheduled wake-up, a subagent) was not read, and `done` might mean something else there. recommended: on, as queue sessions run to an end and D59 says finished sessions are stopped; if a session that sleeps between turns becomes normal, read that state first; default after: 2026-11-13.
5. **New: a stop acts on a list a few seconds old.** A person who attaches to a `done` session in that window could lose it. recommended: accept it, the same window `--stop-finished` has; default after: 2026-11-20.
6. **New, seen in the dry run: a job taken by a session of another name is invisible to the tick until its branch is on origin.** Run 1 would have started W141-build at 01:05:18. Session 9371181e (`J95-build`) was already working on W141: `job/W141` has its commit dated 01:02, and that branch was not on origin when the tick read the branch list. The live-session check goes by name, so it could not see this. A real start would have run a second session on the job until its claim or push failed. recommended: keep the rule, and sessions that pick up a job claim first, which `jobs next` does; a session that takes a job by hand under another name is the gap, so say so in the opt-in note if it happens again; default after: 2026-11-20.

## What napoleon must do at its pin bump
Set in `[jobs]`: `max_sessions = 4` (if W41's bump has not), `auto_actions = ["fix", "review", "build", "brief"]`, and `auto_stop_finished = true` if question 4 stands. `auto_hold_phases` and `auto_phase_order` as Liam wants. No DLL or harness input changes, so no acceptance run for this job (rule 79). `docs/UPGRADING.md` "The autopilot can start builds and briefs (W46)" has the rest.

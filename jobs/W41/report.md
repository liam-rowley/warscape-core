# W41 report: session cap, jobs sessions, the acceptance lock deferral

The session cap is built. The first session stopped at the brief's second kill criterion (`claude agents --json` no longer listed `done`, Claude Code 2.1.318)
and asked four questions; Liam answered them on 2026-11-06 ("Yes your pick"), and a second session built the job from those answers. Decisions 3 and 4 of the brief
changed as a result; the rest are built as written. No existing test assertion changed.

## Liam's answers, 2026-11-06
1. **Build decisions 1, 2, 3, 5 and 6 as written, with the `kind == 'background'` test added.** Yes.
2. **Decision 4: as the first session recommended.** `jobs sessions` reads `--all` and shows every state. `--stop-finished` stops only `done` rows that still have a `pid`,
   reports the rest as already exited without counting them as failures, and never calls `claude rm`. The first session said no such row exists today. **That was
   wrong:** on 2026-11-06 W43-build was `done` with a live 404 MB process, and W43-review, W44-review and others the same.
3. **The cap differs from the recommendation.** A session counts only if it has a `pid`, whatever its state: a `blocked` row with no pid does not count, a `blocked` or `done` row
   with a pid does. The cap exists for RAM (D59), and a row with no process uses none. Accepted cost: a blocked session with no process that resumes can go over the cap by one for a while.
4. **`claude stop`, settled by Liam's tests on 2026-11-05 and 2026-11-06.** On a `done` row with no pid it exits 0 and changes nothing. On a `done` row with a pid it ends the
   process, the row stays `done` and the pid clears. A session can also lose its pid by itself while blocked (W41-build did).

## What was built
- **`[jobs] max_sessions`** (`warscape/repo.py`, default 0 = no cap; the loader refuses anything but a whole number of at least 0). `capped_sessions` in `warscape/jobq.py` is the one
  rule: `kind == 'background'` and a `pid`.
- **`list_agents` reads `claude agents --json --all`.** Answer 3 counts a `done` row with a pid, and plain `--json` lists active sessions only. Every older reader still filters on
  `LIVE_STATES`, so the same-name and PC holder checks behave as before.
- **The check in `JobServer.start`** (decision 2): after the same-name check, before the claim and the launch; 429 with the brief's message, at most 5 names. `auto_tick` works on a
  copy of the list, adds each start to it, and logs one deferral line per tick when the cap is full.
- **`jobs next`** (decision 3): `sessions: <n> live of <cap>`; at the cap it says to wait and claims nothing; an unreadable list is printed and blocks nothing.
- **`wsc jobs sessions [--stop-finished] [--json]`** (decision 4): `session_rows`, `stop_finished` and `stop_session` in `jobq.py`, the sub-verb in `warscape/verbs/jobs.py`.
- **The acceptance lock** (decision 5): `read_pc_lock` runs `harness/job.sh status`, the reader `harness/ctl.py` and `harness/acceptance.py` use, and takes its `lock`. `JobServer.pc_busy` reads
  it once per tick through a new `pc_lock` seam, and `defer_reason` holds a `needs_pc` start. Buttons never read it. `ACCEPTANCE_PURPOSE` is held to `harness/acceptance.py` by a host test.
- **Docs:** `docs/CONSUMING.md` (the key and one line, paid for by cuts in the same section: 30,662 to 30,688 bytes, under the 30,720 cap), `docs/UPGRADING.md`, the `jobq.py` module docstring, the verb header and
  its `wsc.jobs` tool row.

## Evidence
Tests: `python3 -m unittest tests.test_jobs` on 2026-11-06. Red before the build: 174 tests, 36 failed or errored, every one in the new classes (`SessionCap`, `AgentList`,
`NextAtTheCap`, `Sessions`, `AcceptanceLock`, `MaxSessionsKey`). Green after it: 174 tests, OK. The six classes cover each case of deliverable 4.

CI: the `gates` workflow, run 42182495196 at commit `b836059` (the build): `gates (ubuntu-latest)`, `gates (windows-latest)` and `harness-windows` success; `proxy` skipped, as nothing it watches changed. Local: `python3 wsc.py gates` at the same commit, 14 ok, 2 warn, 0 failed, 2026-11-06.

Read on the PC on 2026-11-06 with Claude Code 2.1.319, read-only (no session was stopped by this job):

`python3 wsc.py jobs sessions`, its head and last line:

```
name                                  id        state    pid     job
J32-build                             1f457253  working  11688   -
W41-build2                            2d13416a  working  17216   W41
W45-build                             8c158f7a  working  22472   W45
j19 pickup                            6eecf913  done     -       -
...
sessions: 178 background (blocked 2, done 156, failed 1, stopped 16, working 3); 3 with a process, no cap set
```

The answer to the brief's second open question: the PC had 156 finished sessions at that reading, none with a pid, so `--stop-finished` would have stopped none. Liam's reading
earlier the same day found several with a pid, so the number moves through the day.

With `S.max_sessions` set by hand against the live list: 4 printed `sessions: 3 live of 4` and `cap_line` was None. The refusal at the cap ran only against stubbed lists.

The lock, read through a real game: `core/harness/job.sh status` in napoleon-remastered returned the watcher's status with `lock: {owner: j32, purpose: "J32 S3 and S4", age_s: 2, stale: false}`,
the shape `read_pc_lock` parses; that purpose is a sitting, not acceptance, so it defers nothing. In this repo `job.sh status` exits 64 (no adapter), and `read_pc_lock` returned None. The lock
purpose `harness/acceptance.py` takes is `acceptance pass`; `Parse-KV` in `harness/watcher.ps1` keeps the two words.

The first session's reading, 2026-11-05, Claude Code 2.1.318:

| Command | Rows | `state` values | `kind` |
|---|---|---|---|
| `claude agents --json` | 5 | working 3, blocked 1, none 1 | background 4, interactive 1 |
| `claude agents --json --all` | 168 | done 147, stopped 15, working 3, failed 1, blocked 1, none 1 | background 167, interactive 1 |

Row keys: `cwd`, `id`, `kind`, `name`, `pid`, `sessionId`, `startedAt`, `state`, `status`. The interactive row has no `id` and no `state`.

The CLI help the brief asks for:

```
claude agents --help
  --all    With --json: also include completed background sessions
  --json   Print active sessions (interactive and background) as a JSON array and exit (for scripting; does not require a TTY)

claude stop --help
  Usage: claude stop <id>
  Stop a background session. Its conversation is kept; resume it later with `claude attach <id>`.

claude rm --help
  Usage: claude rm <id> [--discard-unpushed <commit>@<worktree-id>] [--force-remove-worktree <worktree-id>]
  Delete a background session and its worktree. Unlike `stop`, works on already-exited sessions.
```

## Deviations from the brief and why
- **Decisions 1 and 4 follow Liam's answers,** not the brief: the count is rows with a pid, not `state` in `LIVE_STATES`, and `--stop-finished` skips `done` rows with no pid.
- **`jobs next --id` goes on at the cap**; only plain `jobs next` says wait. The brief does not make this exception. A session launched from the view runs `jobs next --id <id>` and is
  itself a live row, so at a full cap the wait would stop every session the launch had just allowed. Plain `next` at the cap exits 0, as it is an answer and not a failure.
- **An unreadable lock defers a `needs_pc` start** under `--auto`. The brief does not say. A harness that cannot answer cannot prove the PC is free, and a deferral costs one tick (decision 6's reasoning).
  No harness at all (`job.sh` exits 64, or no bash) means no lock and no deferral, as the first session recommended. A stale lock defers nothing, as the watcher is about to expire it.
- **`jobs sessions` lists background rows only,** so the interactive row is not shown.
- **`--stop-finished` was not run on this PC.** It would end other sessions' processes, and nothing in the brief needs it; `claude stop`'s behaviour is Liam's own test above, and the verb's is stubbed.
- **The brief's "two keys" is one key,** `max_sessions`, as its own parenthesis says.
- `origin/main` was merged into the branch, first 10 commits behind and again before the final push. Main's own fix to `docs/AUDIT_METRICS.md:41` (`b776a3c`) won over the same fix made here, so this job does not change that file.

## Open questions
1. **The core and other games stay uncapped by default.** The count sees every background session on the PC, but only a repo with `max_sessions` set refuses. A core or empire autopilot can still launch
   past napoleon's 4. Recommended: set `max_sessions = 4` in the core's `wsc.toml` in the same change as napoleon's pin bump; default after: 2026-11-13. Not done here, as the brief says a game opts in.
2. **If a Claude Code update drops `pid`, the cap goes quiet:** nothing counts, so nothing is refused. `kind` has the same exposure. Recommended: a later row for a check that a `working` row with no pid
   warns; `state` already changed shape once. Default after: 2026-11-13.
3. The brief's own two questions: Liam's `claude --bg` sessions count (the list cannot tell them apart), and `--stop-finished` does not run on the autopilot's tick. Both took the recommended answer; W46 can revisit the second.

## What napoleon must do at its pin bump
Set `max_sessions = 4` in `[jobs]` of its `wsc.toml` (D59). No DLL or harness input changes, so no acceptance run for this job (rule 79). `docs/UPGRADING.md` "Session cap (W41)" has the rest.

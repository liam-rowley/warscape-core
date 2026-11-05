# W41: Session cap: [jobs] max_sessions, jobs sessions --stop-finished

Phase 1 (the pipeline). Liam decided on 2026-11-04 (napoleon D59) that at most 4 background Claude sessions or subagents run at once on his PC.
The orchestrating session and his own interactive sessions do not count; a PC job counts as one; finished sessions are stopped. About 20
live sessions (350-850 MB each) plus WSL and Docker had left 4.6 GB of 31 GB free, and Claude Code killed napoleon J64's gate run for low
memory. Today the launch path has no count cap (`warscape/jobq.py` `JobServer.start` docstring: "then the launch (no count cap)"). This job
adds the cap, and it is the prerequisite for W46: the autopilot may only start briefs and builds once it cannot exceed the cap (C41).

Model: Opus, reason: the launch path every background session goes through; a wrong count either stalls the queue or lets the PC run out of memory again (D52: builds on Opus).
Budget about 90 tool calls: about 15 reading, 25 for the red tests, 30 to build, 10 for docs and gates, 10 for the report and the pull request.
Semver: minor
No DLL or harness input changes: `warscape/jobq.py`, `warscape/verbs/jobs.py`, `warscape/repo.py`, tests and docs only, so a game's pin bump to this tag carries no acceptance run for it (napoleon rule 79, J58).
Subagents: none; do the work in this session.

## Start
1. `git pull`; `python3 wsc.py jobs next --id W41` and follow its mechanics. If this session's model is not Opus, stop and say so.
2. `python3 wsc.py gates --fast` for a baseline.
3. Read W26's report (`jobs/W26/report.md`: the autopilot's tick, the claim, the PC one-holder rule, its open questions) and napoleon J52's
   report (`git -C ../napoleon-remastered show origin/main:jobs/J52/report.md`, read-only: why `done` sessions stay listed).

## Target facts (check each again before relying on it)
- `warscape/jobq.py`: `list_agents` (`claude agents --json`, fails closed), `LIVE_STATES = {'working', 'blocked'}`, `_session_job` (a
  session name to its job), `JobServer.start` (the one launch path for the buttons and `--auto`: readiness 409, same-name 429, then the
  launch), `JobServer.auto_tick` (reads the agent list once per tick and passes it to `start`), `defer_reason` (the PC holder rule).
- `warscape/repo.py` `DEFAULTS['jobs']`: where the new keys go, each with a comment, the way `claim_hours` and `pc_state` are.
- `warscape/verbs/jobs.py`: the sub-verbs and their `--help` text.
- `tests/test_jobs.py`: the `Autopilot` and `JobServer` cases and how they stub `agents`, `launch`, `ci`, `claim`.
- The `claude` CLI on this PC: `claude --help` and `claude agents --help` name the command that stops a background session by id. Paste
  both outputs in the report. If no such command exists, see the kill criteria.
- The acceptance lock: `harness/` (the watcher's lock file and its `purpose`, core W10, C26). Find where the lock's holder and purpose are
  read (`python3 wsc.py find lock`) and reuse that reader; do not parse the file a second way.

## Decisions already made for this job
1. **`[jobs] max_sessions`**, an integer, default `0` meaning no cap (a game opts in; napoleon sets 4 at its next pin bump). The count is
   the live sessions of `claude agents --json` (`state` in `LIVE_STATES`), all of them, not only the queue's: Liam's D59 counts every
   background session and subagent. Interactive sessions are not in that list, so they are not counted.
2. **One check, in `JobServer.start`**, after the same-name check and before the claim and the launch, so the buttons and `--auto` share it:
   at or over the cap is HTTP 429 `refused: <n> of <cap> background sessions are live (<names, at most 5>); wait or run wsc jobs sessions
   --stop-finished`. `auto_tick` counts its own starts in the same tick against the list it read (a second start in one tick must see the
   first), and logs one deferral line per tick when the cap is full, not one per job.
3. **`jobs next`** prints `sessions: <n> live of <cap>` when a cap is set, and, at the cap, says to wait instead of naming a job to start.
   An agent list that cannot be read prints that and does not block `jobs next` (it is the interactive path; only launches fail closed).
4. **`wsc jobs sessions [--stop-finished] [--json]`** lists live and finished background sessions (name, id, state, the job when
   `_session_job` finds one). `--stop-finished` stops each `done` session by id through the CLI command found in the target facts, and
   never a `working` or `blocked` one; it prints one line per stop and exits 1 if any stop failed. `--json` for scripts.
5. **The acceptance lock:** while the PC lock is held with an acceptance purpose, `--auto` starts nothing that opens a window (any session
   of a `needs_pc` row) and logs the deferral once per head and reason, the way `defer_reason` already does (J64 run 20261104_j64pc4 lost a
   pass to a window on the virtual display). Buttons are not blocked by this: Liam pressing one is his choice.
6. **Fail closed stays:** an unreadable agent list refuses a launch (503), as now.

## Deliverables
1. The two keys in `DEFAULTS['jobs']` (`max_sessions`; no new key for decision 5) and the check of decision 2 in `JobServer.start`, with
   the per-tick count in `auto_tick`.
2. Decision 3 in `jobs next`; decision 4 as a sub-verb in `warscape/verbs/jobs.py`, its logic in `warscape/jobq.py`.
3. Decision 5 in `defer_reason`.
4. Host tests, red first then green, in `tests/test_jobs.py`, with a stubbed agent list: cap 0 never refuses; cap 2 with 2 live refuses
   naming them; `done` sessions do not count; two starts in one tick at cap 2 with 1 live start one and defer one; an unreadable list is 503;
   `jobs next` at the cap says wait; `sessions --stop-finished` stops `done` only (stub the CLI call) and exits 1 on a failed stop; the
   acceptance lock defers a `needs_pc` start under `--auto` but not a button.
5. `docs/CONSUMING.md` "The job pipeline": one line for `max_sessions` and one for `jobs sessions`. The file is at the `doc_size` cap, so
   pay for the lines with a cut of the same size in that section.

## Out of scope
- Starting briefs or builds from `--auto` (W46, which depends on this).
- Napoleon's `wsc.toml` (its pin bump sets `max_sessions = 4`; name it in the report under what napoleon must do).
- Memory measurement or any per-session weight: the cap is a count (D59).

## Open questions
1. Should Liam's own `claude --bg` sessions started by hand count? recommended: yes, the list cannot tell them apart and D59 counts every
   background session; default after: 2026-11-08.
2. Should `--stop-finished` run on every autopilot tick? recommended: no, not in this job; report how many finished sessions the PC has
   when you run it, and W46 can decide; default after: 2026-11-08.

## Kill criteria
- The `claude` CLI has no command to stop a background session by id: build decisions 1 to 3 and 5, make `--stop-finished` print the ids
  and the manual step instead, and say so under deviations.
- `claude agents --json` on this PC no longer lists `state` with `working`, `blocked` and `done`: stop and report the new shape before
  building on it.
- Any existing `tests/test_jobs.py` assertion has to change for a reason other than the new refusal: stop and report why.
- Over about 90 tool calls: stop, commit, report what is left.

## Finish
Report in `jobs/W41/report.md` with `## What was built`, `## Evidence` (the tests red then green, the branch's CI run id, the two `--help`
outputs, a `jobs sessions` listing from this PC), `## Deviations from the brief and why`, `## Open questions`, and what napoleon must do at
its pin bump. Write the usage line: `python3 wsc.py jobs usage W41 --write --from-json <file>` (the core has no usage reader: write the JSON
from this session's own count). Then:
`wsc reg set jobs W41 status=review report=jobs/W41/report.md` (`python3 wsc.py`)
Push `job/W41`, open the draft pull request, and stop: an independent reviewer merges (C18); the release workflow tags (C27).

# W41 report: stopped at a kill criterion, nothing built

The session cap is not built. This session stopped at the brief's second kill criterion: `claude agents --json` no longer lists `done`
(Claude Code 2.1.318; J52 saw it listed on 2.1.316). The change breaks decision 4 only. Decisions 1, 2, 3, 5 and 6 read `working` and
`blocked`, which are unchanged. No code or test changed on this branch. The row is `blocked` until Liam answers the questions below.

## What was built
Nothing. This report and the row change are the whole diff. `python3 wsc.py gates --fast` was green at the start (15 ok, 2026-11-05).

## Evidence
Read on the PC on 2026-11-05 with Claude Code 2.1.318, read-only unless stated.

The kill criterion that fired: "`claude agents --json` on this PC no longer lists `state` with `working`, `blocked` and `done`: stop and
report the new shape before building on it."

| Command | Rows | `state` values | `kind` |
|---|---|---|---|
| `claude agents --json` | 5 | working 3, blocked 1, none 1 | background 4, interactive 1 |
| `claude agents --json --all` | 168 | done 147, stopped 15, working 3, failed 1, blocked 1, none 1 | background 167, interactive 1 |

Row keys: `cwd`, `id`, `kind`, `name`, `pid`, `sessionId`, `startedAt`, `state`, `status`. The interactive row has no `id` and no `state`.

Which rows have a process, from `--all`:

| `state` | `kind` | Has `pid` | `status` | Rows |
|---|---|---|---|---|
| done | background | no | none | 147 |
| stopped | background | no | none | 15 |
| failed | background | no | none | 1 |
| working | background | yes | busy | 3 |
| blocked | background | no | none | 1 |
| none | interactive | yes | busy | 1 |

The CLI help, the parts that matter here:

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

## What this changes in the brief
1. **`done` needs `--all`.** `list_agents` calls plain `--json`, so `jobs sessions` would see no finished sessions and `--stop-finished`
   would do nothing. The `jobq.py` comment on `LIVE_STATES` ("done" stays listed: J52) is out of date for the same reason.
2. **`--stop-finished` probably has nothing to stop.** All 147 `done` rows have no `pid`, so their processes have already exited and hold no
   memory. The `rm` help implies `stop` does not work on an exited session. If so, decision 4 as written would try 147 stops, fail them all
   and exit 1. **This is unverified:** the one test `claude stop` on the oldest `done` session was denied by the session's permission
   classifier, so `stop` was never run and no session was changed.
3. **`claude rm` is not a substitute.** It works on exited sessions but deletes the session and its worktree, which the brief never asked
   for. It would also free disk, not memory.
4. **The memory problem behind D59 may not come from finished sessions.** On this reading only `working` sessions hold a process. The cap
   is still needed, but "finished sessions are stopped" may now need no action. This is one sample on one day.

Other facts that differ from the brief. None of them is a kill criterion:
- **Interactive sessions are in the list**, against decision 1's "not in that list" (J52 already said so). The `state` filter still leaves them
  out, because they have no `state`. The count should also test `kind == 'background'` so it does not depend on that.
- **`stopped` and `failed` are new states.** Neither is in `LIVE_STATES`, so neither would count, which is correct. `jobs sessions` should show them.
- **A `blocked` session can have no process.** `J64-build` is `blocked` with no `pid`, so it would take a slot while using no memory.
- **The orchestrating session is listed if it runs with `--bg`.** D59 excludes it, but the list cannot tell it apart.
- **Decision 5 has no Python lock reader in `warscape/`.** The purpose `acceptance.py` writes is `acceptance pass`, and `game.lock` is read through
  `job.sh` and the watcher's `status` (`st['lock']` in `harness/acceptance.py`). `jobq.py` has no adapter to find that root, so the builder must work out how
  to reach it. A game with no harness needs a defined answer as well: recommended, no lock means no deferral.

The first kill criterion did not fire: `claude stop <id>` exists.

## Deviations from the brief and why
- Stopped at the second kill criterion, so all five deliverables are not done, no red tests exist, and no draft pull request was opened.
- The row is `blocked`, not `review`, because there is nothing to review. There is no usage line, as the job is not finished.
- A `claude stop` was attempted on one `done` session (`6eecf913`) to settle point 2. The brief allows stopping `done` sessions, but this
  was a test on a live PC, and it was denied before it ran.

## Open questions
For Liam, each with a recommended answer:
1. **Build decisions 1, 2, 3, 5 and 6 as written?** Recommended: yes, with the `kind == 'background'` test added. They do not read `done`.
2. **What should decision 4 become?** Recommended: `jobs sessions` reads `--all` and shows every state; `--stop-finished` stops only `done` rows
   that still have a `pid` (none today), reports the rest as already exited without counting them as failures, and never calls `claude rm`.
3. **Should a `blocked` session with no `pid` count against the cap?** Recommended: yes, as decision 1 says. It can resume, and it shows up in
   `jobs sessions`. The cost is that a few of these could fill the cap and hold the queue.
4. **Who confirms `claude stop` on an exited session?** Recommended: Liam runs `claude stop 6eecf913` once, or allows it for the next session, and
   the result goes in this report. Question 2's answer does not depend on it.

The brief's own two open questions are unchanged. The second asks whether `--stop-finished` should run on every tick; if answer 2 is taken, that
matters less, as there may be nothing to stop.

## What napoleon must do at its pin bump
Nothing yet. Once this job is built, napoleon sets `max_sessions = 4` as the brief says.

# W46 review

## Round 1 (2026-11-07, branch job/W46 at 8c03f22)

**Verdict: merge after fixes.**

The default path and the dry run hold, and the probe's answer holds for more kinds of wait than the builder read. Three things must change first: a tagged brief can slip through, a freeze does not reach a running server, and a stop can land on a session that has just woken. The cap can also be passed by a start the tick cannot see. No code was changed in this round; a fix session answers it.

### What was run
- `python3 wsc.py gates` at 8c03f22, 2026-11-07: 15 ok, 1 warn (the 5 known skips), 0 failed, 463 s.
- `python3 wsc.py policy --branch job/W46 --base origin/main` before this round: refused only for the missing review and row, as expected. Its one warning is the citation of `job/W141`, now on main (#185).
- CI on the head 8c03f22, run 42324893203: `changes` and `gates (ubuntu-latest)` success; `gates (windows-latest)` and `harness-windows` skipped, as only `report.md` changed since 5540142, where both passed (run 42323968678). `policy` is skipped on the draft and is not a pass: it has never run on this branch.
- A real dry run, 2026-11-07 01:45 to 01:46 UTC, three ticks, keys set by hand in this round's worktree and restored: `git ls-remote origin` and the session ids were the same before and after, no `would stop` line (no row was `done` with a pid), and the cap-full line every tick.
- The adversarial cases below were run against the job's own `Opted` test base, from a script outside the repo.

### The questions this review was asked
| Question | Answer |
|---|---|
| Can the cap be exceeded? | **Yes**, see should-fix 1. Inside one tick it holds: each start counts in the tick's copy, and `start` checks again. |
| Does a held phase ever start a build? | **Yes, on a running server**, see blocker 2. The check in the tick is right for the config the server loaded. |
| Does a red main ever start a build? | Not in normal use: red and unknown both wait, and a failed read is unknown. **With `--offline`, yes**, see should-fix 2. |
| Does a dry run start or push anything? | No. Read in `start`, `stop_done` and `prune_tick`, and shown by the run above. Its only write is the local `git fetch` of origin/main. |
| Does anything new start by default? | No. `fresh_main` reads nothing, `main_candidates` gets no rows, and the stop key is off. The order change is the one difference, and `docs/UPGRADING.md` names it. |
| Can `auto_stop_finished` stop a working session? | **Yes, through a stale list**, see blocker 3. The meaning of `done` itself held up, as below. |

### The probe, widened (W123, Claude Code 2.1.319, 2026-11-07, run w46r)
The builder read a background shell only. Three more throwaway haiku sessions, read with `claude agents --json --all` every 15 s and stopped with `claude stop`:

| Wait | Session | While waiting | After |
|---|---|---|---|
| One-shot cron, fired 01:46 | `w46r-cron` b2a930cb | `working`, status `idle`, pid kept, turn over | still `working idle` at the last read, after 01:47:54, having fired and answered |
| Background subagent, about 3.5 min | `w46r-agent2` 5205a6ac | `working`, status `busy` | `done idle` by 01:47:00, after it answered |
| Monitor, about 3 min | `w46r-mon` 32917402 | `working`, status `busy` | `done idle` by 01:47:00, after it answered |

So no wait read so far is `done`, and a stop of `done` rows ends none of them. Two things the report does not have:
- A session that has used a cron stayed `working` after it fired, so it did not reach `done`: it holds a cap slot and no tick stops it. That is the safe way round, but it can stall a full cap with no named cause.
- A first subagent probe, 8df35550, read `failed idle` with a pid by 01:41:32, after its subagent's `sleep` was refused and the session reported that. So `failed` with a pid is a normal row, and the stall line is worth having.

Not read: `/loop` wake-ups (`ScheduleWakeup`). A session waiting on one may read differently, so question 4 stays conditional on that.

### Blockers
1. **A tagged question under a longer heading does not hold the build.** `warscape/jobq.py:771` matches only a heading of exactly `## Open questions`. 53 of the 137 briefs in core and napoleon use a longer one, J95's among them: `## Open questions (for Liam; each has a recommendation this brief follows)`, `## Open questions for Liam`. See it fail: `brief_tags('## Open questions for Liam\n1. q. Tag: risk.\n')` returns `[]`, so the build starts on a question that must never default. No brief today has a tag under such a heading (a looser scan of all 137 agreed with `brief_tags` on every one), so this has not bitten yet. Fix: match the start of the heading, with a test for each of those shapes. `Tag: **risk**`, `**Tag:** risk` and `tags: risk` are missed as well; take them in the same regex or refuse them in `jobs check`.
2. **A freeze does not reach a running server.** `[jobs]` is read once, at `warscape/verbs/jobs.py:156`, from the working tree. Add a phase to `auto_hold_phases`, merge it, and the running `--auto` keeps starting that phase until someone pulls and restarts it. The row asks for a freeze in one config line, and nothing in `docs/CONSUMING_OPTIONS.md` says a restart is needed. The same goes for taking `build` out of `auto_actions`. Fix: `fresh_main` reads `auto_hold_phases` and `auto_actions` from `wsc.toml` at the tick's sha (`read_at` is there), and an unreadable file starts no build or brief. If that is judged too much, the least is a doc line and the page saying which holds the server loaded, with the reason under deviations.
3. **A stop acts on the list read at the top of the tick.** `stop_done` (`warscape/jobq.py:1965`) uses the list read before `fresh_main`'s fetch, the CI reads and any launches earlier in the tick. That was 2 to 7 s in the dry runs, but the fetch alone may take 300 s, so report question 5's "a few seconds" is the usual case, not the limit. See it fail: flip a `done` row to `working` from inside the `main_head` seam, and `stop` is still called on it: a session at work is ended. Fix: re-read the list in `stop_done`, stop only ids still `done` with a pid, and if the read fails stop nothing. Host test: that flip.

### Should-fix
1. **The cap can be passed from outside the tick.** The tick's list is not re-read before a launch (`warscape/jobq.py:1814`, `agents` passed in), so anything started after that read is unseen: a button, or the second repo's `--auto`, as the list is the whole PC's (the report's run 2 shows `J95-build` in the core's list). See it fail: cap 2, one live session, add one from inside `main_head`, and the tick still starts `J7-build`: 3 live. W41 had this gap, but this job makes the tick longer and gives it many more candidates. Fix: read the list again under `self.lock` before each launch, keeping this tick's own starts, and refuse if it cannot be read. That leaves W121's second or so, and the brief's reading order at the top of the tick is unchanged. Say in `docs/CONSUMING_OPTIONS.md` that the cap is close but not absolute.
2. **`--auto --offline` starts builds with main's CI unread.** `main_state` answers `off`, which waits for nothing, and `main_head` reads rows as last fetched (`warscape/verbs/jobs.py:219`). Decision 7's `off` is right for the seam, but no build should start blind. Fix in the verb: with `--offline` the `main_head` seam raises, so the tick starts no build or brief, and the host test of `off` stands.
3. **A stop can free a slot nothing can use.** With main red and a full cap, the tick stops the `done` row and then starts nothing (`warscape/jobq.py:1908` runs before `:1912`). The report names this and calls it free. It is cheap, but the tick should not end sessions for no start. Fix: stop only when the candidate has passed main's CI and `defer_reason`.
4. **The stop reaches sessions that are not the queue's.** `session_rows` is every background row on the PC, so the tick would stop a person's own finished `claude --bg` session: the report's run 2 logged `would stop w46-probe`, the builder's own probe. It is finished and `claude stop` keeps its conversation, so only the process is lost. Fix: stop only names of the queue's shape, `<id>-<action>`, from any repo, so a game's tick can still free a slot held by a core session.
5. **Merge main.** `docs/UPGRADING.md` conflicts with origin/main at 96735f9 (`git merge-tree`). Keep both sections.
6. **Correct the report and the docstring.** Question 6 says a second session would run "until its claim or push failed", but `job/W141` was not on origin, so the tick's session would have claimed cleanly: the first session's push would be the one refused, after a duplicate build. The `jobq.py` module docstring says what `done` means from one wait: give it the table above, the cron case included.

### Report questions 5 and 6
- **5, a stop on an old list:** do not accept as written. Blocker 3 closes most of it. What remains is the moment between the re-read and the stop, and `claude stop` keeps the conversation (`claude attach` resumes it), so a person loses little.
- **6, a job taken under another name:** the report's reading is right. GitHub's activity log has `job/W141` created at 01:10:41 with commit 69d7b98, after the tick's 01:05:18. That session made no claim push, so "sessions claim first" did not hold for it. It bites only a repo that opted in and has its jobs built under other names, which is the core (`J95-build` built W141), not napoleon as far as this job shows. Accept it for napoleon, and answer it before any `meta/` change opts the core in.

### Later
- **W122 should come before napoleon opts in.** The cap fails open if `pid` or `kind` leaves the list. That was mild for reviews; with 12 ready rows it is up to `max_sessions` new sessions a tick, every tick, each uncounted by the next. The brief kept it out of scope, rightly for this job, but the row's priority has changed.
- W121 stands as the remaining gap once should-fix 1 is done.

### Checked and fine
Order and `auto_order`; `later`, `blocked` and `done` rows; `depends_on` read from main's rows; a snapshot failure skips the tick rather than reading an empty branch list; `read_at` on a missing brief gives `None`, and that defers; a missing seam fails closed; the `needs_pc` rules, and a brief holding nothing; the first model for a brief; `gates.yml` does not cancel runs on main, so `main_state` is not misled by a cancelled run. No workflow changed.

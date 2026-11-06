# W46: Autopilot starts briefs and builds under the session cap, with held phases

Phase 1 (the pipeline). On 2026-11-05 Liam said the work had slowed: napoleon had 12 ready rows and nothing building, because `--auto` starts only reviews and fixes and every
brief and build waits for someone to say "pick up the next job". W41 built the cap this waited for (C41: accepted job options become rows the autopilot briefs and builds, after the
cap). This job lets a repo opt in to the tick starting briefs and builds, in a fixed order, under that cap, with one config line to freeze a phase. The default stays today's behaviour,
so nothing changes for a repo that does not opt in. Most of the job is the rules a human applied without noticing when they said "pick up the next job": is main healthy, are these rows
current, does this brief still wait on Liam.

Model: Opus, reason: the launch path of every background session; a wrong rule here starts sessions nobody asked for, on stale rows, or stops one that is still working (builds run on Opus).
Budget about 150 tool calls: about 15 reading, 10 for the probe, 35 for the red tests, 40 to build, 15 for docs and gates, 10 for the report and the pull request, and 25 for one fix round. The median total of W41, W43, W44 and W45, fix rounds included, is about 150; the first two were narrower than this and the last two wider.
Semver: minor
No DLL or harness input changes: `warscape/jobq.py`, `warscape/repo.py`, `warscape/verbs/jobs.py`, tests and docs only, so a game's pin bump to this tag carries no acceptance run for it (napoleon rule 79). `harness/` is read, never changed. No game is launched: `needs_pc` is false, and the probe in deliverable 1 is one throwaway `claude --bg` session.
Subagents: none; do the work in this session.

## Start
1. `git pull`; `python3 wsc.py jobs next --id W46` and follow its mechanics. If this session's model is not Opus, stop and say so.
2. `python3 wsc.py gates --fast` for a baseline.
3. Read `jobs/W41/report.md` (the cap rule as Liam changed it, the `claude agents` shapes, `claude stop`), `jobs/W41/review.md` (the cap rule read against real processes, and Later 3, which is row W123), and the rows W123, W72, W93, W121 and W122 (`python3 wsc.py find <id>`). Read `jobs/W45/report.md` only for W47's section: nothing here calls `wsc proposals`, but W47 builds on this tick (see Out of scope).
4. Read C32, C34 (its W26 answers) and C41 (`python3 wsc.py reg render decisions`, then `_scratch/registries/decisions.md`).

## Target facts (check each again before relying on it)
- `warscape/jobq.py`:
  - `JobServer.auto_tick`: walks `on_branch` only, so it can never see a row with no job branch. `start`: the one launch path; already takes any action and `family=True`. `defer_reason`: the PC rules, then the head's CI, and it reads CI for every action. `self.started`: `(id, action)` to the head, kept in this process only.
  - `not_ready`, `ACTIONS`, `BRANCH_ACTIONS` (its comment says "the only ones --auto starts"), `order_key`, `pick_next`: the existing rule and order to reuse, not copy.
  - `PROMPTS` and `launch_argv`: a brief runs on the first of `[jobs] models`, a build on the row's model; both prompts run `jobs next --id <id>`. `next_claim` with `jid` calls `not_ready`, which refuses once `job/<id>` or `brief/<id>` exists. Decision 4 follows from this.
  - `main_rows` reads the rows of the **working tree**, not of origin; `snapshot` in `warscape/verbs/jobs.py` uses it. Decision 6 follows from this. `fetch_main`, `_blobs` and `branch_row_spec` are the tools to read rows from a ref.
  - `main_state` (`red`, `green`, `unknown`, `off`): main's CI, a few `gh` calls each read. `session_rows`, `stop_finished`, `stop_session`, `cap_line`, `capped_sessions`, `_session_job`, `pc_busy`, `pc_absent`.
- `warscape/repo.py` `DEFAULTS['jobs']` and the validation after it: where the keys go, each with a comment, as `max_sessions` did.
- `warscape/verbs/jobs.py`: its header and the `--auto` help say "never a brief or a build"; the page's `refresh` text in `render_view` and the tick's `nothing ready for review or fix` line say the same. All of them go stale here.
- `tests/test_jobs.py`: `Autopilot.make`, `Capped`, `SessionCap`, `AutopilotGates`, `AcceptanceLock` show how `agents`, `launch`, `ci`, `claim` and `pc_lock` are stubbed. `jobs next` at the cap: `NextAtTheCap`.
- `docs/CONSUMING.md` sits a few bytes under the `doc_size` cap. Run the gate before writing there. `docs/CONSUMING_OPTIONS.md` has room, and the key table's detail can go there with a link.
- `git` on this repo does not delete a branch on merge, so do not assume a merged `brief/<id>` or `job/<id>` branch is gone, or that it remains: read the branch list.
- Windows host tests are near `[tests] timeout_s` (row W139): a Windows timeout on an otherwise clean run is that row, not this job. Rerun once and say so; do not touch the limit.

## Decisions already made for this job
1. **Three keys in `[jobs]`.** `auto_actions` (a list, default `["review", "fix"]`: today's behaviour), `auto_hold_phases` (a list of phase numbers, default empty), `auto_phase_order` (a list of phase numbers, default empty: the plain `order_key`). The loader refuses an unknown action, anything but whole numbers in the phase lists, and `build` or `brief` in `auto_actions` while `max_sessions` is 0: C41 and W41's brief allow these starts only once the cap holds.
2. **Order.** Each tick lists every candidate in the order fix, review, build, brief. Inside one action: the phases named in `auto_phase_order` first, in that order, then the rest by `order_key`. This is one pure function, tested on its own. Fix and review go first so that a finished job is never kept waiting behind a new one; a later tick reaches them first again when a slot frees.
3. **A held phase is never auto-started, in any action,** a pipeline freeze being what the row asks for. The phase is the main row's. A held row is one log line per id and reason, as a deferral is. A button and `jobs next` ignore the hold, as they ignore the acceptance lock: a person is looking.
4. **The session claims, not the tick.** The row says a build or brief claims its branch first. That already holds: the launched prompt's first command is `jobs next --id <id>`, which claims before it prints a step. A claim pushed by the tick would make that command refuse ("in progress on job/<id>"), so the session would end at once and the job would sit on an empty branch; a claim carries no owner, so `next` cannot tell its own from another's; and no tool releases a claim (C32, C34), so a failed launch would need Liam. The window between launch and claim is covered by the live-session check (`family=True`) and `self.started`; a person who picks the same job in that window loses the create-only push and is told so. Host test: after a tick starts a build, `next_claim(jid=...)` still claims. See open question 1.
5. **Not restarted until the row or main moves.** For build and brief, `self.started` holds the pair (main's sha, the row's canonical JSON) where review and fix hold the head. Same pair: one `waiting for the row or main to move` line and no start. A session that claimed and then died leaves the branch, so `not_ready` holds the job and the empty-claim line reports it after 24 h: no new rule. The memory stays this process's: a restarted server may start such a job once more, the cost J52 review 1 accepted.
6. **Build and brief decisions read `origin/main`, not the working tree.** A new `JobServer` seam, `main_head()` -> (sha, rows), fetches and reads the rows at `origin/main`, once per tick and only when `build` or `brief` is in `auto_actions`. Otherwise a checkout that is behind starts a brief for a row already briefed, or a build for one already done. If it fails, the tick starts no build and no brief, logs one line, and goes on with fixes and reviews. Review and fix keep reading as they do.
7. **The rules per action.**
   - The head's CI (`defer_reason`) applies to review and fix only. A build or brief has no head.
   - A build or brief waits while main is `red` or `unknown`, read once per tick through a seam over `main_state` and only if a candidate reached this step (`off` waits for nothing). W45 could not claim while main was red, and every branch taken then inherits the fault. Fix and review do not wait: the fix for red main may be one of them.
   - A build obeys the `needs_pc` one-holder rule, `pc_absent` and the acceptance lock. A brief obeys none of them and holds nothing: writing about a `needs_pc` row needs no PC, so a `<id>-brief` session is not a PC holder. Today's `pc_holders` counts every live session of a `needs_pc` row, and that changes for `-brief` names only.
8. **`later` rows are never started.** `not_ready` already says so for every action (`later` is neither `queued` nor `needs_brief`). A host test holds it, with `blocked` and `done`.
9. **A tagged question holds a build.** A brief's open question tagged `taste`, `risk` or `legal` must never default, and the builder starts on the recommended answer of the others. A person read that before "pick up the next job"; the tick does not. So a build whose brief has `tag: taste`, `tag: risk` or `tag: legal` under `## Open questions` is deferred with one log line naming the row, and a button still starts it. See open question 2.
10. **The cap stays W41's.** `capped_sessions` does not change, Liam's rule is not reopened, and each start still counts in the tick's copy of the list. One line per tick when full.

## Deliverables
1. **The probe (W123), first, before the code that depends on it.** Start one throwaway session, `claude --bg --name w46-probe --model haiku`, asked to run a shell `sleep` of about 3 minutes as a background task and wait for it. Read `claude agents --json --all` every 30 to 45 seconds, by hand, while it waits and after it ends. Record: the `state` and `status` during the wait, the Claude Code version, and how long the `done` row keeps its pid unstopped (look again near the end of the job). Stop it with `claude stop` when done; never `claude rm`. It counts as one session (D59), so read `python3 wsc.py jobs sessions` first and wait if four are live.
2. **The tick stops a finished session only if the probe allows it.** `[jobs] auto_stop_finished` (default false).
   - If a session waiting on a background task is **not** `done`: build it. When the key is on and the cap is full with a candidate waiting, the tick runs `stop_finished` over `session_rows`, once, then clears those pids in its copy of the list and carries on. Each stop is a log line. A dry run only logs.
   - If it **is** `done`: do not add the key. A `done` row cannot be told from live work, so report that, and the cap-full line stays as it is.
   - Either way a `failed` or `stopped` row with a pid is never stopped; the tick names it in the cap-full line, so a stall has a cause on the page.
3. **The keys and the loader rules** (decision 1), with `Settings` and `configure_from` carrying them.
4. **The tick**: candidates (decision 2) over the branch rows and, when opted in, the rows from `main_head`; holds (decision 3), restart memory (decision 5), the per-action rules (decisions 7 and 9), all through `start(..., family=True)`. Read `S` values, not new globals. Keep `auto_tick`'s reading order: snapshot, prune, agents, one lock read.
5. **The words**: `--auto` help, the verb's header and its `wsc.jobs` tool row, the page's autopilot line (it should say what this repo's tick starts, from `auto_actions`), the tick's idle line, the `jobq.py` module docstring and the `BRANCH_ACTIONS` comment, `docs/CONSUMING.md` (paid for by cuts or moved to `docs/CONSUMING_OPTIONS.md`), a `docs/UPGRADING.md` section saying how a game opts in.
6. **Host tests** in `tests/test_jobs.py`, red first, with stubbed `agents`, `launch`, `claim` and git, no real session. At least:
   - Defaults: with no key set, a tick with queued and needs_brief rows starts neither.
   - Order: fix, review, build, brief across jobs; `auto_phase_order`; the cap taken by the first in the order and the rest deferred with one line.
   - Holds: a held phase in each of the four actions; the button path unaffected.
   - Claim: a tick pushes no claim; `next_claim(jid=...)` claims after it; a claimed `job/<id>` is not started again.
   - Restart: same row and main, no start; main moved, a start; row moved, a start.
   - Fresh rows: working tree says `queued`, `origin/main` says `done`, no start; `main_head` raising starts no build or brief and still starts a review.
   - Red main: `red` and `unknown` hold builds and briefs, not reviews or fixes; `off` holds nothing; not read when nothing reached that step.
   - PC: a build under another holder, under the acceptance lock and with `pc_absent`; a brief for a `needs_pc` row starts under all three and is not counted as a holder.
   - Never started: `later`, `blocked`, `done`; a `depends_on` not done.
   - Tagged brief: `tag: risk` under `## Open questions` defers, the same words elsewhere in the brief do not.
   - Models: a brief's argv carries the first model, a build's the row's.
   - Loader: each refusal in decision 1.
   - Stop (if built): off by default; only `done` with a pid; only at a full cap with a candidate; a dry run stops nothing; a failed stop does not end the tick.
7. **A real dry run** on this PC: `python3 wsc.py jobs view --serve --auto --dry-run --no-open` with the three keys set in a scratch copy or by hand (never committed to `wsc.toml`), over at least two ticks. Paste the log lines into the report. Stop the server afterwards.

## Out of scope
- **`wsc.toml` of this repo:** no key changes here, `max_sessions` included. See open question 3.
- **`capped_sessions` and its gaps:** W121 (a launch uncounted for about 1 s) and W122 (fails open if `pid` or `kind` goes) stay `later` rows; the probe's list reading is a check on W122's shape, no more.
- **W72** (snapshot lock, Stop button and the rest) and **W93** (`merge-tree` before a review): each stays its own row, whatever W72 says about the next job in `jobq.py`.
- **W47:** no audit session and no `[audit]` key. Leave the candidate list easy to extend, nothing more.
- **Slots reserved for reviews**, a per-tick start limit, and any priority beyond decision 2.
- **W123's row:** a job branch changes only its own row, so the report says what the probe answered and a `plan/` branch closes it.

## Open questions
1. **Decision 4 reads the row's "claims its branch first" as the session's first command, not a push by the tick.** Should the tick claim instead, which needs a claim with an owner and a way to release it? recommended: no, keep the session's claim; default after: 2026-11-13.
2. **Decision 9 is not on the row.** Should a tagged open question hold an automatic build? recommended: yes, and the hold ends when the tag leaves the brief or Liam presses the button; default after: 2026-11-13.
3. **Who opts in, and when?** recommended: napoleon sets `auto_actions = ["fix", "review", "build", "brief"]` at the pin bump to this tag, with its `max_sessions = 4`; the core sets `max_sessions = 4` (W41 open question 1) and stays on review and fix until a `meta/` change says otherwise, as its queue changes the tool that runs it; default after: 2026-11-13.
4. **`auto_stop_finished` on in napoleon, if it is built?** recommended: on, as D59 says finished sessions are stopped; default after: 2026-11-13.

## Kill criteria
- The probe shows `claude agents --json --all` no longer has `state`, `kind` or `pid` in the shapes `jobs/W41/report.md` records: stop and report the new shape before building on it.
- The probe session cannot be run (`claude --bg` exits non-zero, or four sessions stay live for an hour): build everything but deliverable 2, leave W123 open, and say so under deviations.
- An existing assertion in `tests/test_jobs.py` has to change for any reason but the start order of decision 2: stop and report which and why.
- A dry run in deliverable 7 logs a real start, or `git push` from the tick: stop the server at once, and report it.
- `doc_size` cannot be met in `docs/CONSUMING.md` by moving text to `docs/CONSUMING_OPTIONS.md`: stop and report the bytes.
- Over about 150 tool calls: stop, commit, report what is left.

## Finish
Report in `jobs/W46/report.md` with `## What was built`, `## Evidence` (the tests red then green with counts, the branch's CI run id, the gates, the dry-run log lines, the probe's readings with its date and Claude Code version), `## Deviations from the brief and why`, `## Open questions`, and what napoleon must do at its pin bump. The report states W123's two answers plainly, as a `plan/` branch closes that row from them, and what W47 calls to add a candidate. Write the usage line: `python3 wsc.py jobs usage W46 --write --from-json <file>` (the core has no usage reader: write the JSON from this session's own count). Then:
`wsc reg set jobs W46 status=review report=jobs/W46/report.md` (`python3 wsc.py`)
Push `job/W46`, open the draft pull request, and stop: an independent reviewer merges (C18); the release workflow tags (C27).

## Registry gaps
None.

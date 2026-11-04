# W26: Job claim and autopilot: atomic claim, phase and needs_pc, red CI, stale worktrees

Model: Opus, reason: napoleon D52 (a job's build runs on Opus; the row's model is changed from sonnet to match). The work is plain standard-library Python with host tests, but it
changes how every session picks up work and what the unattended autopilot starts, so a slip costs duplicated or lost jobs. No DLL, no PC (`needs_pc` false). Budget about 120
tool calls (a queue change in `jobq.py`, one new library module, two git-backed test fixtures, docs). At the cap, stop, commit what is green, and report what is left. Kill
criteria are at the end.

## Goal
Audit 2026-11-03 (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`, read-only: `git -C ../napoleon-remastered show origin/main:docs/audits/AUDIT_2026-11-03.md`): the rule rows "two
sessions build one job" and "status machine, `phase` and `needs_pc` ignored", finding H2's autopilot half ("two PC jobs can start at once"), "Smaller: `--auto` reviews a red branch",
automation item 7, and the two worktree rows (125 registered worktrees on napoleon's PC clone, 47 on the core's; a `~/repos/.git` above every clone). Today:
- **Two terminals running `jobs next` get the same job.** A claim is "push early" (`build_steps`: "push early so the branch claims it"), and readiness reads `remote_branches` (`not_ready`, the
  `f'{prefix}/{jid}' in branches` test). Nothing happens between printing the steps and the first push, which can be minutes, and both sessions start building.
- **`pick_next` orders by id and ignores `phase` and `needs_pc`.** A phase-2 job with a lower number is handed out before a phase-1 job, and a `needs_pc` row is handed out on a machine with no
  PC state folder (a cloud session), where the builder can only fail.
- **The autopilot starts a review of a branch whose CI is red or still running.** `branch_checks` reads the checks but only feeds the prompt text; `auto_tick` never looks at it. The reviewer
  then spends a session on a branch the CI is about to refuse, or reviews a head that moves under it.
- **The autopilot starts any number of `needs_pc` reviews and fixes at once** (a PC review runs the acceptance flow on the one game install; W10's lock refuses the second, wastefully).
- **Dead worktree registrations pile up** and nothing says so; a `.git` above the repo root makes git commands in a clone act on the wrong repository.

## What exists (read before building)
`CLAUDE.md`, `docs/DECISIONS.md` (C18, C24, C26, C27), `docs/CONSUMING.md` "The job pipeline", `docs/BACKLOG.md` (B75 lists latent `jobq.py` serve problems: it is **not** in scope, but do not make
them worse: one snapshot per tick stays as is), `jobs/W22/report.md` (what W22 added to `jobq.py`; this job builds on it). Line numbers in the row are stale (W22 moved them); re-find by name.
In `warscape/jobq.py`: `ACTIONS` and `BRANCH_ACTIONS`; `not_ready` (the one readiness rule, used by `jobs next|review|fix`, `--id`, the view's buttons, the server and `--auto`); `pick_next`;
`remote_branches` and `branch_rows`; `branch_checks` and `check_lines` (the CI read: `gh api repos/{owner}/{repo}/commits/<sha>/check-runs`); `build_steps` and `brief_steps`; `JobServer.start`
and `auto_tick` (state: `self.started`, the agent list read once per tick, `family=True` starts); `list_agents` and `LIVE_STATES`. In `warscape/verbs/jobs.py`: `run` (the `next` branches, `--id`, `--offline`).
Tests: `tests/test_jobs.py` (fakes for `snapshot`, `agents`, `launch`; `pick_next` and `not_ready` cases). `phase` is an int on every row (absent on an old row: treat as 99, last).
`wsc setup` is **not** in the core: it is each game's verb (napoleon `tools/verbs/setup.py`, which imports the core's `warscape.gitbash`). The worktree and `.git` checks therefore live in a core library
module the game's setup verb calls (decision 10); wiring the call is a napoleon change this job names but cannot make.

## What this PC can and cannot run (the builder)
Windows, Git Bash, `python3` (if it hangs, `C:\Users\liamr\AppData\Local\Python\pythoncore-3.15-64\python.exe`), `git`, `gh`. Everything here is a host test: git cases run in temp folders with a **local bare
repository as `origin`** (`git init --bare` in a temp dir, two clones); no network, no `gh` (inject `run=`, as the existing tests do), no game, no PC state folder (a temp folder stands in). Never run the
autopilot against the real remote; never push a `job/` or `brief/` branch to the real origin to test the claim (the unit tests use the bare temp origin; step 8 says what to do about a live claim).

## Decisions already made (follow them; a deviation goes in the report with its reason)
### The claim (two sessions never build one job)
1. **`jobs next` claims before it prints.** For a build it runs `git push origin origin/main:refs/heads/job/<id>`; for a brief, `origin/main:refs/heads/brief/<id>`. No `--force`, no `--force-with-lease`:
   git refuses an existing remote branch atomically, and that refusal is the lock. Reason: the push is the only operation both sessions share, and the server serialises it. The ref pushed is the
   remote-tracking `origin/main` of the fetch `jobs next` just did (it already fetches via `remote_branches`); it never pushes the working tree's HEAD.
2. **A refused claim moves on.** Refusal means git's "rejected" / "already exists" / "fetch first" on that ref (match on the `!` line of `git push --porcelain` rather than on prose). `jobs next` then
   re-reads the branches (one fetch) and picks the next ready job with the same rule; at most 5 attempts, then it prints "Nothing is ready" naming the contested ids. Any other failure (no network, no
   permission, a hook refusal, a missing `origin`) is **not** a lost race: print the git line, claim nothing, exit 1; never hand out an unclaimed job as if it were claimed.
3. **What the steps then say.** `build_steps(r, claimed=True)`: "Claimed: job/<id> now exists on origin at <sha7>. Take it: `git fetch origin job/<id>`, `git checkout -b job/<id> origin/job/<id>`" and the rest unchanged;
   the "push early so the branch claims it" clause goes. Same for `brief_steps`. `--id <J>` claims too (it is a pickup). A claimed branch equal to `main` carries no row change, so `branch_rows` and
   the lane logic must treat it as "in progress, nothing to review yet" (it already does for a row that is still `queued`; add the test).
4. **`--peek` and `--offline` never claim.** `jobs next --peek` prints what would be picked and the exact push it would run, claiming nothing (for a human looking, and the view's links). `--offline` reads
   local refs only, so it cannot claim: it behaves as `--peek` and says "(not claimed: --offline)". `jobs view` and every other reader never claim. The view's "start" buttons start a *review or fix*, which
   need an existing branch, so they have no claim to make.
5. **A stale claim is visible, not auto-released.** Releasing means deleting a remote `job/` branch, which agents must not do (napoleon's hook denies it) and which could destroy work. Instead `jobs next`
   prints, below the steps or the "Nothing is ready" list, one line per **empty claim** (a `job/<id>` or `brief/<id>` branch whose head is an ancestor of `origin/main` with no commits of its own) older than 24 hours
   (committer date of that head commit): "J<n>: claimed <age> ago, nothing pushed; `git push origin --delete job/<n>` releases it (Liam, or a session he asks)". Reason: a session that died after claiming
   must not block the job forever, and the person who can release it must be told.
### Order, `phase` and `needs_pc`
6. **`pick_next` sorts by (phase, number)** within each kind (builds first, then briefs, as today). An absent `phase` sorts as 99. A job whose `depends_on` are not all done stays not ready, whatever its phase.
7. **A `needs_pc` row is not ready where there is no PC.** New config `[jobs] pc_state = "<path>"` (a game sets it; the core's own `wsc.toml` leaves it unset). `$VAR` and `~` are expanded; the environment variable
   `WSC_PC_STATE` overrides it (empty string = "no PC here", so a cloud environment can say so). Rule in `not_ready` for the `build` action only (a brief is written anywhere, and review and fix of a `needs_pc` row
   are the PC's business: rule 12 covers them in the autopilot): key unset and no override = no gating (today's behaviour, so a game that has not configured it is unchanged); key set and the folder does not exist =
   `"<id> needs the PC (<path> is absent here)"` and the row is skipped to the next one. The folder test is `Path.is_dir()`. Add the key to `warscape/repo.py` `DEFAULTS['jobs']`, the config check that
   lists allowed keys, and the `wsc.toml` comment block in `docs/CONSUMING.md`. Reason: `needs_pc` is on every row and read by nothing but a tag on the page.
8. The view shows the same reason where it shows a row that is not ready (`lane`), so a cloud session looking at the page sees why a PC row is not offered.
### Stale worktrees and a `.git` above the repo
9. **New library module `warscape/worktrees.py`** (standard library; git by `subprocess` with `git_env`, C12), with injectable runners:
   - `registered(root)` -> list of `(path, branch_or_None, prunable_reason_or_None)` from `git worktree list --porcelain` (git itself marks `prunable`).
   - `stale(root, rows, branches)` -> `(gone, merged)`: `gone` = registered worktrees whose folder does not exist (what `git worktree prune` removes); `merged` = worktrees (other than the main one) whose branch is
     `job/<id>` with the row `done` on main, or `brief/<id>` with a row past `needs_brief`, or any branch that is an ancestor of `origin/main`, or whose remote branch is gone after a fetch --prune.
     `merged` is **reported, never removed**: a worktree can hold unpushed work.
   - `stray_git(root)` -> the first folder **above** the main worktree's root that contains a `.git` (directory or file), or None. The main worktree's root is the parent of `git rev-parse --path-format=absolute --git-common-dir`,
     so a linked worktree under `.claude/worktrees/` does not count its own repository as "above". Stop at the filesystem root; a `.git` in a Windows drive root counts.
   - `report(root, rows, branches)` -> the warning lines (`N registered worktrees have no folder: git worktree prune removes them`; `N worktrees' branches are merged: <up to 5 paths>, remove them with
     git worktree remove <path>`; `a .git sits above this repository at <path>: git commands run from <root> may act on that repository; delete it or move the clones`).
10. **A game's `wsc setup` calls `worktrees.report`** and prints the lines as warnings. The core ships the function and a `wsc jobs worktrees` action (prints `report`, exit 0; with `--prune` runs `git worktree prune`
    only and prints how many it removed); it adds **no** `setup` verb. Napoleon's `tools/verbs/setup.py` wiring is a follow-up row for napoleon (say so in the report; do not edit napoleon).
### The autopilot
11. **Review waits for green CI; fix waits for CI to finish.** In `auto_tick`, before `start()` for a branch ready for `review`: read the branch's checks through one new function `branch_ci(root, sha, offline, run=...)`
    -> `('green'|'red'|'running'|'none'|'unknown', lines)`, with `branch_checks` rebuilt on top of it (same text out, so its tests stay). Only `green` starts a review; `red`, `running`, `none` (no check run yet) and `unknown`
    (the read failed: fail closed, as the agent-list read already does) defer, each logging `J<n>-review: deferred, CI <state> at <sha7>` once per head (the existing `started` memory pattern; a deferral is not a start and
    does not set `started`). A `fix` is deferred only while `running` or `none` (a fix may exist precisely because CI is red); `red`, `green` and `unknown` do not defer it. Reason for the split: the audit asks that a *review* not
    run on a red or moving branch; a fix is the answer to a review and is what makes a red branch green. (The row says "review or fix" for both: this is a deliberate narrowing, open question 1.)
    A skipped check and a neutral conclusion count as passed, exactly as `check_lines` does today; `policy` on a draft pull request is skipped by design and must not read as red or running.
12. **One `needs_pc` row at a time.** In `auto_tick`, a branch whose row has `needs_pc` true is not started when any session named `J<m>-*` (m a *different* `needs_pc` row) is in `LIVE_STATES`, nor when one was started earlier in
    the same tick. The row's own `needs_pc` is read from main's row. Log `J<n>-<action>: deferred, J<m> holds the PC`. Non-PC rows are unaffected. The manual buttons keep the existing same-name guard only.
13. **The tick prunes.** At the start of every tick (after the snapshot) run `git worktree prune` once in the repo root, logging one line only when it removed something (compare `worktree list` before and after, or
    use `prune -v` output). A failure logs one line and never aborts the tick. `--dry-run` skips it and logs "would prune".
14. A tick's decisions use the same `snapshot()` and `agents()` it already reads: no second fetch per job. The only new network read is the check-runs call per *candidate review or fix branch* (at most one per
    branch per tick, none for a branch already started at this head).

## Out of scope
Release of a claim by tool (decision 5); the buttons gaining a claim; B75 (serve snapshot cache and lock, the same-name guard window, `--prune` scope); W31's usage line and W32's later registry (both after this job,
same file; they will merge `main`); napoleon's `wsc setup` call and its doc line; deleting the stray folders or the `~/repos/.git` (Liam); the PC game lock (W10, done). No game names or paths in core files.

## Scope: files this job touches
`warscape/jobq.py`, `warscape/verbs/jobs.py` (`--peek`, the `worktrees` action, the claim loop), `warscape/worktrees.py` (new), `warscape/repo.py` (the `pc_state` default), the config-key check wherever `[jobs]` keys are
listed (find it with `grep -rn id_prefix warscape`), `tests/test_jobs.py`, `tests/test_worktrees.py` (new), `docs/CONSUMING.md` (the `[jobs]` key, "claim", the worktree hook for a game's setup, what a consumer must do),
`docs/DECISIONS.md` (one row, the next free `C<n>`, proposed, reversible: claim on pick-up, review defers on a not-green branch), `docs/BACKLOG.md` (a row for the napoleon follow-ups if none exists), the `semver` field of
row W26 (see VERSION). A new library module is not a tool (no registry row), but `wsc jobs worktrees` is an action of the existing `jobs` verb: update its `HELP` and header `Usage:` line.

## Steps (host tests first)
1. `git pull`; read the files above; run `python3 -m unittest tests.test_jobs` once for a baseline.
2. **Failing tests first, committed red (one commit).**
   - `tests/test_jobs.py`, claim (real git: temp bare `origin`, clones A and B each with `origin/main`): A's `jobs next` pushes `job/<id>` and prints "Claimed"; B, started before A's push but fetched after
     (stub `remote_branches` to return the stale list once), gets a refused push and is handed the next ready job, whose branch it then holds; every candidate refused -> "Nothing is ready" naming them;
     a non-race failure (the `origin` url removed) -> exit 1, no branch created, steps not printed; 5 contested jobs -> stops at 5; `--peek`, `--offline` and `view` push nothing; `--id J` claims and a claimed `--id`
     is refused with "in progress"; the claim pushes `origin/main`'s sha, not HEAD (HEAD one commit ahead in the test); a claimed empty branch is "in progress" for `not_ready`/`pick_next` and nothing to review for
     `branch_rows`; the stale-claim line appears only past 24 h and only for an empty claim (a branch with a commit of its own never).
   - Order: phase 2 id 1 vs phase 1 id 5 -> id 5; an absent `phase` last; `depends_on` still blocks a lower phase.
   - `needs_pc`: `pc_state` unset -> unchanged; set to a missing folder -> skipped with the reason and the next row picked; set to an existing temp folder -> picked; `WSC_PC_STATE=""` beats a set key;
     `WSC_PC_STATE=<dir>` beats an unset key; the reason text appears in `lane`; review and fix of a `needs_pc` row are not blocked by `not_ready`.
   - Autopilot (fakes for snapshot, agents, launch, and a `branch_ci` seam): a review with `red`, `running`, `none`, `unknown` is not started and logs the deferral once per head; `green` starts; a skipped-only
     rollup counts green; a fix with `running` and `none` defers and with `red` starts; a second `needs_pc` branch in the same tick is deferred, a live `J<m>-review` session of another `needs_pc` row defers, a live
     session of a non-PC row does not; a deferral does not set `started`, so the next tick with `green` starts it; the tick calls `git worktree prune` (recorded runner) once, logs only on a removal, survives a failing
     prune, and under `--dry-run` runs nothing.
   - `tests/test_worktrees.py` (temp repo with real `git worktree add`): a worktree whose folder is deleted -> `gone`; a worktree on a merged `job/<id>` -> `merged`, not removed by `--prune`; the main worktree never
     listed as stale; `stray_git` with a `.git` folder two levels above the main root -> found; with the clone itself and a linked worktree under `.claude/worktrees/x` -> None; a `.git` *file* above counts; `report`
     lines exact; `wsc jobs worktrees --prune` removes only the missing-folder registrations.
3. Build `worktrees.py`, then `branch_ci` and the autopilot rules, then the claim and the order/`needs_pc` rules, then the verb flags. Keep `not_ready`'s signature (callers pass `by, branches, on_branch`): the PC rule
   reads `S` state set by `configure` (add `S.pc_state`), not a new positional argument.
4. Docs, the `DECISIONS.md` row, `BACKLOG.md`, the row's `semver`.
5. Push early (after the red commit and after each step); read CI's `gates (windows-latest)` log: git behaves differently on Windows (path forms, `.git` files, CRLF in porcelain output), and the claim and worktree tests
   must run there too.
6. `python3 wsc.py gates` (full) and `python3 wsc.py policy --branch job/W26 --base origin/main`.
7. Run `python3 wsc.py jobs view --serve --auto --dry-run --no-open` for two ticks against the real repo (a dry run starts nothing and prunes nothing) and stop it; copy the log lines into the report.
8. **No live claim from the builder.** Run `python3 wsc.py jobs next --peek` and paste it. Do not claim a real job from this session (job/W26 itself already exists): the first real claim happens at the
   next `jobs next`, and the report says so.

## Tests and acceptance
- Every new case red first (the red commit's run listed in the report), then green; every existing case in `tests/test_jobs.py` still green, or changed with a stated reason (the `next` cases that assert the old
  "push early" text change; say which).
- **Failing fixtures**, throwaway commits (not pushed) each turning a named test red: the claim pushing `HEAD`; the claim with `--force`; "any push failure is a lost race" (moving on instead of exit 1); `pick_next`
  sorting by id alone; `not_ready` ignoring `pc_state`; `WSC_PC_STATE` ignored; the review start ignoring `branch_ci`; `unknown` starting a review; a fix deferred on `red`; the `needs_pc` serialisation dropped;
  `stray_git` counting a linked worktree's own repo; `merged` worktrees removed by `--prune`. Name them in the report.
- Done means: CI's `gates` (both OS), `proxy` and `policy` green on `job/W26`; nothing outside "Scope" changed; no game name or path added; the report states which cases ran only on the Windows leg; the dry-run
  autopilot log and the `--peek` output are in the report; decision 5's age threshold and decision 11's split are listed under Deviations or Open questions as the builder found them.

## VERSION
A minor bump (new CLI flag, config key and behaviour: **0.31.0 expected**; `main` is 0.30.0 when this is written). If W29 (release tags by workflow, C27) has merged by the time you branch, job branches no longer edit
`VERSION`: set `semver=minor` on row W26 and leave the file alone. If it has not, bump `VERSION` yourself and re-read `origin/main` `VERSION` and the open `job/*` branches before the last commit; the second to merge takes
the next free number and merges `main` (never rebase a pushed branch). Say which route you took. Tags are not yours.

## What consumers must do after the tag (napoleon-remastered)
- Set `[jobs] pc_state` in its `wsc.toml` to the PC state folder (the adapter's value; the core names none), so cloud sessions stop being handed `needs_pc` builds. Until set, nothing is gated.
- A job pick-up now creates `job/<id>` on origin at once. Two terminals no longer get the same job; a session that dies after claiming leaves an empty branch that `jobs next` lists after 24 hours.
- Napoleon follow-up row (not this job): `tools/verbs/setup.py` calls `warscape.worktrees.report` and prints its lines (the 125 registrations, the merged-branch worktrees, the `~/repos/.git`).
- The autopilot (`jobs view --serve --auto`) waits for green CI before starting a review, and runs one `needs_pc` row at a time; its tick prunes dead worktree registrations.
- Liam: delete `~/repos/.git` and clear the worktree folders by hand (the audit's Liam item).

## Kill criteria
- `git push origin origin/main:refs/heads/job/<id>` to a bare temp origin does not give a distinguishable "rejected" result in `--porcelain` on this PC or in CI's Windows leg after two designs: stop and report the
  observed output; do not fall back to a check-then-push (that is the race).
- The claim cannot be made without changing `not_ready`'s public signature in a way that breaks the view or the server: stop and report what you need.
- A test pushes to the real `origin`, runs `gh` against the real repository, or deletes a real branch or worktree: stop at once and report what it touched.
- CI's `harness-windows` or `proxy` goes red for a cause outside this change: report it with the run id; do not fix it here.
- Three red CI rounds for a cause in this change: stop and report.
- Version collision as in VERSION; never rebase a pushed branch.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **Does the red-CI deferral apply to a fix?** The row says "a review or fix"; the audit says review. Recommended: review waits for green, fix waits only while CI is running (decision 11), because the fix is what repairs a red
   branch. Reversing it is one line in `auto_tick`.
2. **Should an empty claim be released automatically after N hours?** Recommended: no, list it after 24 hours and let Liam release it (decision 5): deleting a remote `job/` branch is denied to agents by design.
3. **`needs_pc` gating with the key unset.** Recommended: no gating, so an unconfigured game is unchanged; the core's own PC rows are not gated until a repo sets `pc_state`.
4. **Should `merged` worktrees be removed by `--prune`?** Recommended: no, report only; one may hold unpushed work, and `git worktree remove` refuses a dirty one anyway when Liam runs it.
5. **Does a claimed branch equal to `main` trigger CI on push?** If the workflow runs on every `job/**` push it will run once on an empty branch. Recommended: accept it (the cost is one cached run); if the builder finds it
   makes the claim slow or noisy, report it rather than changing the workflow here.

## Finish
Write `jobs/W26/report.md` (what was built, evidence with run ids, deviations from this brief and why, open questions), then run
`wsc reg set jobs W26 status=review report=jobs/W26/report.md`, commit with the `Claude-Session` trailer, and push `job/W26`. Never mark the job done.

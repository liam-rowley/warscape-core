# W10: Watcher and pc_deploy race fixes; the lock owner is the session

Model: Sonnet, reason: none needed (Sonnet is the default). Every item is a local fix in a script that already has host tests (`tests/test_job_sh.py`,
`tests/test_pc_deploy.py`, `harness/tests/Test-Unit.ps1`, `Test-Integration.ps1`); the races are made deterministic with a seam, not with timing. No DLL,
no reverse engineering, no PC (`needs_pc` false). Budget about 170 tool calls (nine items over three languages, three test suites; `test_job_sh.py`
alone takes about 90 s a run on Windows). At the cap, stop, commit what is green, and report what is left. Kill criteria are at the end.

## Goal
Backlog B20, B21, B27, B30, B39 and audit 2026-11-03 H2, H11 and H12's stale-lock age (`napoleon-remastered` `docs/audits/AUDIT_2026-11-03.md`, read-only; the
job row `registries/jobs/W10.json` lists them). Two things go wrong today on a shared PC:
- **Two sessions share a lock by name.** Free-text owners with shared defaults (`claude-acceptance` in `acceptance.py:472`, `claude-ctl` in `ctl.py:974`) mean
  two sessions that both use the default hold "the same" lock; the watcher compares owners with `-ne` (case-insensitive) while `job.sh` uses `!=`
  (case-sensitive); `job.sh ctl` and `shot.sh` never look at the lock; `touch` refreshes anyone's lock.
- **Races and stale answers.** A stale lock can be taken over by two takers, or expired by the watcher under a lock taken a moment earlier (B20); a ps1 job
  exits with an old native code (B21); `kill` returns before the process list is clean (B27); the prefs overlay sets one of two copies of a key (B30);
  `pc_deploy set` is undone by a deferred profile restore (B39); `job.sh` waits 900 s where the Bash tool gives up at 120 s and leaves the request queued (H11).

## What exists (read before building)
`CLAUDE.md`, `docs/DECISIONS.md`, `docs/CONSUMING.md` ("The job pipeline", "The proxy, the harness and the save tools"), `docs/BACKLOG.md` (B20, B21, B27, B30,
B39), `docs/PROXY_CTL.md`, `jobs/W8/brief.md` and `report.md` (W8 moved the harness host tests here; read its "Evidence" for what runs where). Citations were
checked against `origin/main` (0.22.0); two moved and one is mis-worded:
- **`harness/job.sh`:** scratch owner pattern line 38; `lock` 115-136 (the owner and age check 117-119, the `line=` at 121, `create()` 125, same-owner rewrite 129-131,
  the stale check at 133 and the `mv` at 135, which the B20 row calls line 134); `touch` 137-139; `unlock` 140-146; `ctl` 85-107 (default wait 170 at 89, withdraw 95-103);
  plain jobs from 148 (`t="${3:-900}"`), the wait 166-167 and the timeout branch 168-171, which says "The request stays queued". The two `1200` literals are lines 119 and 133
  (H12 cites 118, the `age=` line).
- **`harness/shot.sh`:** line 4 says "no game lock needed"; it submits a read-only ps1 job through `job.sh` with `owner=`.
- **`harness/watcher.ps1`:** `$Version = '1.3.0'` line 11; `lock_stale_min = 20` line 33 (read by `Get-Lock` 235); `Check-Owner` 238-246 (**the H2 row says it "compares
  case-sensitively": it does not, PowerShell `-ne` ignores case; `job.sh` is the case-sensitive side**); `Expire-StaleLock` 247-256 (the move at 251, no check of what was moved);
  `Kill-Game` 306-338; `Apply-PrefsOverlay` 460-485 (`$rx.Replace($text, $ev, 1)` at 475 sets only the first copy) and `Get-PrefsValue` 488 (first copy);
  `Auto-Restore` 681-700 (`$l.owner -ne $active.owner` at 691); the script guard's `Check-Owner` at 1296; the ps1 tail at **1309-1311** (the B21 row says 1296);
  the owner gate for launch, kill and profile at 1340-1349. The status file (`Write-Status` 1108) is rewritten every 2 s and holds `processes`, `game_state`, `lock`.
- **`proxy/tools/pc_deploy.py`:** `watcher_view` 464, `running_check` 494, `set_keys` 718-738, the `set` parser 829. A pending restore is
  `<state>/watcher/profiles/_active.json` (`$ActivePath`, watcher.ps1 202; `Auto-Restore` removes it once the game is closed and the lock released, expired or changed owner).
- **Callers:** `harness/ctl.py` `Pc.job` 244, `job_sh_transport` 426, `Pc.shot` 378 (`shot.sh`), `--owner` 974; `harness/acceptance.py` `PcEnv.lock/release` 236-258 (`sh('lock', owner, session, ...)`,
  a bare `sh('touch')`, `sh('unlock', owner)`), `--owner`/`--session` 472-476.
- **Tests:** `tests/test_job_sh.py` (15, bash with a thread as the watcher), `tests/test_moved_tools.py:134` (the exclusive-create race), `tests/test_pc_deploy.py` (`Deploy`,
  `HarnessKit` with a fake `watcher.alive`/`watcher.status` at 448-453), `tests/test_ctl.py`, `tests/test_acceptance.py`, `harness/tests/Test-Unit.ps1` (game lock 118-141, prefs overlay 462-492),
  `Test-Integration.ps1` (real watcher with fake games: refusals 282, launch and kill 331, auto-restore 573; helpers `Set-Lock`, `Run-Job`, `Get-St`).

## What this PC can and cannot run (the builder)
This PC has Windows PowerShell 5.1, Git Bash and Python. **Locally:** `python3 -m unittest tests.test_job_sh tests.test_pc_deploy tests.test_ctl tests.test_acceptance tests.test_moved_tools`
(if `python3` hangs, use `C:\Users\liamr\AppData\Local\Python\pythoncore-3.15-64\python.exe`); the PowerShell unit suite,
`powershell -NoProfile -ExecutionPolicy Bypass -File harness\tests\Run-HostTests.ps1 -Suite unit` (seconds; 5.1, as CI); `python3 wsc.py gates`. **Never locally:** the integration
suite (`-Suite integration`): it starts and kills `Fake*.exe` and sets the machine's time zone while it runs; it runs only in CI's `harness-windows` job (`ci/gates.yml.in`, 25 min, Windows
PowerShell 5.1, fake games compiled there). Push early and read that log for every integration case you add; say in the report which cases ran only there. Every `job.sh` test uses
`--adapter <temp adapter>` or `$WATCHER_ROOT`: never run `job.sh lock/ctl/kill` against the PC's real state folder or its live watcher.

## Decisions already made (follow them; a deviation goes in the report with its reason)
### The lock owner is the session (H2)
1. **One owner rule everywhere.** `^[a-z0-9][a-z0-9_-]{0,39}$`, one helper in `job.sh` used by `scratch`, `lock`, `touch`, `unlock`, `holds`, `ctl` and plain jobs. 40, not scratch's
   current 32, because a session id is a 36-character UUID; the scratch test moves from 32/33 to 40/41. The watcher compares owners **case-sensitively** (`-ceq`/`-cne`) in `Check-Owner` and
   `Auto-Restore`; the pattern is lower case, so the only owners this refuses are mixed-case ones, and the refusal text says to lower-case it. Reason: the case-insensitive watcher and the
   case-sensitive shell disagreed about who holds the lock.
2. **The holder is the pair (owner, session).** `lock` on a lock held by the same owner but a different `session=` is refused like another owner's, until it is stale. This is what keeps two sessions
   that both pass `--owner claude-acceptance` apart. The lock file's line format does not change (a deployed watcher and a new `job.sh` meet in the middle). `lock -` means "owner = the session id".
3. **The watcher also accepts the lock's `session=` as the request owner**: `Check-Owner` passes when the request `owner=` equals the lock's `owner` or its `session` (exact match). A holder that took the
   lock under a free-text name can still send its jobs as its session id.
4. **A lock is required where it was missing.** New `job.sh holds <owner>` (exit 0 when the lock is held, fresh, and owner or session equals `<owner>`; else 2 with the one-line reason and the
   command to take it); `job.sh ctl` calls it before writing the request, `shot.sh` before submitting (its header and line 4 say it needs the lock). `touch <owner>` and `unlock <owner>` refresh and
   release only that owner's (or session's) lock; a bare `touch` is refused (64) naming `touch <owner>`, never a silent refresh of someone else's lock. `status`, `noop`, `scratch`, `root`, `adapter` need none.
5. **`lock --wait <s>`:** poll every 2 s until the create succeeds, a stale lock is taken over, or `<s>` has passed (capped at 100, the Bash tool's limit minus a margin); timeout is 124 ("no
   answer", as the other waits), a plain refusal stays 2. Default: no wait.
6. **The stale age is the watcher's (H12).** `job.sh` reads `lock_stale_min` from `$ROOT/watcher.ini` (`key=value` lines, as `Load-Settings`; absent or unparsable = 20) instead of `1200`; the
   "refresh at least every 10 min / expires after 20 min" message is built from the same number.
7. **Free-text owners keep working; the shared defaults go.** An explicit `--owner claude-acceptance` (a valid name) is still accepted by `acceptance.py`, `ctl.py` and `job.sh`, under the pair rule of
   decision 2. What changes is the default: `acceptance.py run|measure` and `ctl.py` take `--owner` defaulting to the session id, and `--session` (acceptance's is `'acceptance'` today; ctl gets the flag) defaulting to the
   same. The session id comes from `--session`, else `$WSC_SESSION_ID`, else the variable Claude Code exports to its Bash tool (look in `env` for a `*SESSION*` name in this session and use what you find;
   if none exists, `WSC_SESSION_ID` is the only route and the docs say how a session sets it). With none, both tools **refuse** (exit 2, a JSON `refused` result in ctl's shape) saying: pass `--session <id>`
   or set `WSC_SESSION_ID`, or pass `--owner <name>` knowing that two sessions with that name exclude each other only through the pair rule. Reason: a refusal that names the fix is better than a silent
   shared default, and an explicit name is the caller's own choice. **Consumer migration** (goes in `docs/CONSUMING.md`, a short section "The game lock is the session's (0.23.0)"): set `WSC_SESSION_ID`
   in the session (or pass `--session`) and drop `--owner`; scripts that name an owner keep working and need only a session; `job.sh touch` gains the owner argument; hand-run `job.sh ctl` and `shot.sh` need
   `job.sh lock` first; the watcher on the PC must be updated to 1.4.0 (`update kit=`), because the `session=` match and the exact-case compare live in it.

### Races
8. **B20, both sides take the same three steps.** Read the lock (its line and mtime), move it aside to a unique name, then check what was moved: the same line, and its mtime still older than the stale
   limit (`touch` changes the mtime and not the line, so the line alone is not enough). If the check fails, the mover **put it back** (a no-clobber rename: `mv -n` in `job.sh`, `Move-Item` without
   `-Force` in the watcher), logs it, and `job.sh` refuses (exit 2, "was refreshed or taken at the same moment"). If the put-back finds the name taken, the moved file stays in `_to_delete` and the log
   says so. `job.sh` creates its own lock only after the check passed. `Expire-StaleLock` takes the record it read as a parameter (`Expire-StaleLock $seen`, default `Get-Lock`) so a unit test can hand it
   a stale record while the disk holds a fresh one. `job.sh` gets a test seam: when `JOB_SH_TEST=1`, `$JOB_SH_TEST_HOOK` is `eval`ed once between reading the stale lock and moving it. The seam is ignored otherwise.
9. **H11, waits.** The plain-job default wait is 100 s, and `job.sh ctl`'s 170 s becomes 100 s for the same reason (the Bash tool gives up at 120 s; `ctl.py` and `acceptance.py` pass their waits explicitly and
   do not change). A plain job that timed out is **withdrawn** exactly as the ctl path does: `mv $J/$id.request $J/$id.request.expired`; if the rename fails the watcher took it, and the message says the result
   will still land in `$J/$id.done`. The watcher ignores `*.request.expired` (it lists `*.request` and checks `EndsWith('.request')`; keep that and test it). The usage line and the header say so.
10. **B21, the ps1 exit code comes from the last statement.** The watcher's wrapper (a pure function, `Wrap-Ps1Body`, so the unit suite tests the text) puts `$global:LASTEXITCODE = 0` before the body and, after it,
    `if ((-not $?) -and $LASTEXITCODE) { exit $LASTEXITCODE }`. An explicit `exit N` still wins; a native failure handled earlier no longer fails the job; a last native call that failed still does, with its code.
    A tool whose non-zero code means success (`robocopy` 1 to 7) is handled by the script ending in `exit 0`; no new header (open question 3). The wrapper's comment and `job.sh`'s header say this. Check under 5.1
    that `$?` after a native command reads the exit code and after a cmdlet reads the error stream; the four cases of step 5 prove it.
11. **B27, `kill` returns when the world agrees.** After `Kill-Game` succeeds the kill job runs `Watchdog` and `Write-Status` until `Get-GameProcs` is empty and `$Game.state` is `not_running` (bounded by
    `zombie_wait_s`; a timeout is the existing ZOMBIE failure), then writes the status once more, and only then `Finish-Job`. So when `.done` appears, `watcher.status` already says `not_running` with no game image in
    `processes`, and `pc_deploy sync-lua` right after it is not refused. (Where there is no watcher, `running_check` falls back to `tasklist`; that is W25's lock work and not this job's.)
12. **B30, the prefs overlay sets every copy.** `Apply-PrefsOverlay` replaces every `key value;` line of a key (a prefs file may hold a key twice; the game read the second), all other bytes unchanged,
    and appends only when there is none. `Get-PrefsValue` returns the **last** copy (what the first consumer's game read). Refusing a duplicated key is not chosen: the game wrote that file, and a refusal would
    block every profile on it (open question 2).
13. **B39, `pc_deploy set` waits for a pending restore.** With `--state` and a usable watcher (`watcher_view` says so), `set` first looks for `<state>/watcher/profiles/_active.json`. Present: poll once a second
    up to `--wait-restore <s>` (default 30; 0 refuses at once) for it to go; still present: refuse (`SystemExit`, ini untouched) with the profile name, its owner, whether the lock is held and whether the game
    is running, and say the restore waits for the game to close and the lock to be released. Gone, or no watcher folder, or no `--state` (print one line that a pending restore cannot be seen): write as today. Reason: a
    restore that runs after `set` puts the old keys back (napoleon J9, run `20261101_j9pc`, raw chains 1-3). `set` taking the lock itself and writing the ini atomically are W25's.

## Out of scope (W25 follows W10 on the same files)
`pc_deploy` taking the lock in `install`, `uninstall`, `set` and `sync-lua`, the atomic ini write, `--assume-closed` needing the lock, `status` seeing a stray ini, the watcher refusing a weakened `watcher.ini`,
`verify_kit` traversal, the exe sha cache, `&` in save names, `load_save.sh`, ESF index. Do not touch them; if a W10 change makes one of them harder, say so in the report. The autopilot serialising `needs_pc`
(W26) and the deny list (a game's `.claude/settings.json`) are not here either. W9 (`acceptance.py`, `ctl.py`) and W30 (`ctl.py` yaw) edit nearby lines: whoever merges second merges `main`, never rebases.
No game names or paths in core files (`tests/test_moved_tools.py` lints them); the audit's paths are evidence for the report only.

## Scope: files this job touches
`harness/job.sh`, `harness/shot.sh`, `harness/watcher.ps1` (and `$Version` 1.3.0 to 1.4.0), `harness/ctl.py`, `harness/acceptance.py`, `proxy/tools/pc_deploy.py`, `tests/test_job_sh.py`, `tests/test_pc_deploy.py`,
`tests/test_ctl.py`, `tests/test_acceptance.py`, `harness/tests/Test-Unit.ps1`, `harness/tests/Test-Integration.ps1`, `docs/CONSUMING.md`, `docs/PROXY_CTL.md` (job.sh ctl needs the lock; 100 s default),
`docs/DECISIONS.md` (one row C23: the lock owner is the session, proposed, reversible), `docs/BACKLOG.md` (remove B20, B21, B27, B30, B39), `VERSION`. `ci/gates.yml.in` only if a new test file needs listing.

## Steps (host tests first)
1. Read "What exists"; run the local suites once to know the baseline (note the seconds each takes).
2. **Failing tests first, committed red** (one commit): in `tests/test_job_sh.py`: owner pattern shared by every command (scratch 40/41, mixed case refused in `lock`/`ctl`); `lock` same owner different session refused,
   `lock -` uses the session, `lock --wait` takes a lock released after 2 s and times out with 124; `holds`; `ctl` refused without the lock and with another's, accepted with it; `touch` bare refused, `touch other`
   refused, `unlock` by session; `lock_stale_min` from `watcher.ini` (`lock_stale_min=1` makes a 100 s lock stale; no ini keeps 20); the B20 seam: a hook that replaces the stale lock with another owner's fresh one, and one
   that only `touch`es it, both end refused with the lock intact and `_to_delete` holding nothing of it; four takers over a stale lock, exactly one 0 and the winner's line in the file; default wait 100 (read the
   usage text or run with a fake clock via `JOB_SH_WAIT`-free means: assert on the printed header and the timeout message with an explicit short wait); a timed-out plain job leaves no `.request` and one
   `.request.expired`; the old queued-request test flips. In `tests/test_pc_deploy.py`: `set` with `_active.json` present and a live fake watcher refuses and leaves the ini byte-identical; removed after 1 s by a
   thread, it writes; `--wait-restore 0` refuses at once; no `--state` writes and says why. In `tests/test_ctl.py` and `tests/test_acceptance.py`: the default owner and session come from `--session`/`WSC_SESSION_ID`, none
   refuses with the fix named, an explicit `--owner` still works, `PcEnv` passes the owner to `touch`. In `Test-Unit.ps1`: `Check-Owner` is case-sensitive and accepts the lock's session; `Expire-StaleLock $seen` with a stale
   record and a fresh lock on disk keeps the lock (and puts back a moved one); `Wrap-Ps1Body` text; the prefs overlay on a file with a key twice sets both and `Get-PrefsValue` reads the last; `.request.expired`
   is not queued (static or by listing). In `Test-Integration.ps1` (CI only): request `owner=<lock session>` accepted, a different-case owner refused; the four ps1 exit cases (an early handled native failure and a
   last statement that succeeds is `ok`; a last native failure is `failed` with its code; `robocopy` of an empty folder ending in `exit 0` is `ok`; `exit 7` stays 7); `kill` then an immediate read of
   `watcher.status` (no waiting) says `not_running` and lists no game image; a duplicated prefs key through a real `profile` job sets both copies.
3. Build the shell side: owner helper, `lock` (pair rule, `-`, `--wait`, `lock_stale_min`, the B20 protocol), `holds`, `touch`/`unlock`, `ctl` and `shot.sh`, the waits and the withdraw. Header lines (`purpose/usage/when`) updated.
4. Build the watcher side: `-cne` and the session match, `Expire-StaleLock $seen` and the check-after-move, `Wrap-Ps1Body`, the kill postcondition, the prefs overlay, `$Version` 1.4.0 (a watcher change the kit must carry).
5. Python side: `ctl.py` and `acceptance.py` defaults, the refusal, `PcEnv.lock` passing the owner to `touch`; `pc_deploy.py set` and `--wait-restore`.
6. Docs (CONSUMING section, PROXY_CTL, C23), backlog, `VERSION`. Push early; read CI's `harness-windows` log and fix integration cases there (each failure: copy the case's log tail into the report).
7. `python3 wsc.py gates` (full), `python3 wsc.py policy --branch job/W10 --base origin/main`.

## Tests and acceptance
- Every new case red first, then green; every existing case in the five Python suites and both PowerShell suites still green, or changed with a stated reason (the scratch length, the queued-request test, a bare `touch`).
- Failing fixtures, scratch commits in a throwaway worktree (not pushed), as W8 did, each turning its test red: `Check-Owner` back to `-ne`; the B20 check-after-move removed from `job.sh`; the same from `Expire-StaleLock`;
  the ps1 tail back to `if ($LASTEXITCODE)`; the kill postcondition removed; `Replace(..., 1)` back; `set` ignoring `_active.json`. Name them in the report.
- Done means: CI's `gates` (both OS), `proxy`, `harness-windows` and `policy` green on `job/W10`; the report says which cases ran locally and which only in CI; nothing outside "Scope" changed; no game name added.

## VERSION
A minor bump (new `job.sh` commands and arguments, changed defaults, watcher 1.4.0): 0.23.0 when written (`origin/main` is 0.22.0; other W rows may claim minors first). Re-read `origin/main` `VERSION` and the open `job/*` branches before the last
commit; the second to merge takes the next free number and merges `main` (never rebase). Say which number you took. Tags are not yours.

## What consumers must do after the tag (napoleon-remastered)
- These are harness inputs: the pin bump that crosses this tag needs acceptance passes on the new build (train 1, J78), and the PC's watcher must be updated to 1.4.0 first (`pc_deploy.py kit --what harness`, `send`, `update kit=<id>`).
- Set `WSC_SESSION_ID` (or pass `--session`) in every PC session; drop `--owner claude-acceptance` and `--owner claude-ctl` or keep them knowing the pair rule; add the owner to `job.sh touch`; take the lock before a hand-run
  `job.sh ctl` or `shot.sh`; a timed-out `job.sh` request is withdrawn now, so a script that relied on it staying queued must pass a longer wait and run in the background.
- Nothing else: no adapter, config key or ini change.

## Kill criteria
- A fix needs the `game.lock` line format to change, or a lock on any file other than `game.lock`: stop and report (deployed watchers and new scripts must interoperate across the bump).
- The B20 put-back cannot be made safe on Windows (a rename onto an existing file overwrites, or the watcher's `Move-Item` has no no-clobber form under 5.1): stop and report with what you tried; do not ship an unchecked move.
- The ps1 tail's `$?` does not give the four step-2 results under 5.1 after two designs: stop; open question 3's `#job exit=` opt-in is the fallback only if Liam says so.
- An integration case is red in CI after three fix attempts for a cause in this change: stop and report; never run the integration suite on this PC.
- A local test touches the real state folder or the live watcher: stop at once and report what it touched.
- Version collision as in VERSION; never rebase a pushed branch.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **Free-text owners: keep working or refuse?** Recommended: keep working (decision 7), under the pair rule, with the shared defaults removed. Refusing every non-session owner would break napoleon's scripts for no
   safety the pair rule does not already give.
2. **B30: set every copy or refuse a duplicated key?** Recommended: set every copy (decision 12); the game's own file is the input and a refusal would block the profile it was meant to serve.
3. **B21: robocopy-style success codes.** Recommended: document ending the script with `exit 0` (decision 10), no new header. A `#job exit=native` opt-in is a protocol addition for one tool.
4. **Lower `job.sh ctl`'s default wait from 170 to 100 as well?** Recommended: yes (decision 9); the same Bash limit applies and the Python callers pass their own waits.
5. **Where the session id comes from.** Recommended: `--session`, then `$WSC_SESSION_ID`, then whatever Claude Code exports to Bash if it exports one (decision 7). If it exports none, Liam decides whether a hook should
   set `WSC_SESSION_ID`; until then the tools refuse and say how.

## Finish
Report in `jobs/W10/report.md` (what was built per item, which tests were red then green and where they ran, the failing fixtures, the version taken, deviations, open questions, what napoleon must do), then
`wsc reg set jobs W10 status=review report=jobs/W10/report.md` (`python3 wsc.py`). Push `job/W10`, open the draft pull request, and stop: an independent reviewer merges (C18); tags follow the merge.

# W94: `pc_deploy uninstall` refuses while a profile is active

Phase 1 (the pipeline). `pc_deploy.py uninstall` can run while a watcher profile is still active. The profile's restore runs only after the game lock is
released, so it runs after the uninstall and writes back the config files it saved when the overlay was applied, the mod ini included. The uninstall has
already printed "identical", the ini is back in the game folder, and any later snapshot counts it as vanilla. It has happened twice in napoleon: J67 (report
open question 4) and J32 (review round 2, S6: the fix session ran `uninstall`, `status`, then `job.sh unlock` in one command, and the restore ran three seconds
after the unlock). Napoleon's `play.py` `uninstall` already refuses on `_active.json`; this job gives the core tool the same guard. Host tests only: no PC
(`needs_pc` false), no DLL, no change under `harness/`. `proxy/tools/pc_deploy.py` is under `proxy/`, so say in the report that the pin bump crosses a
`proxy/` file and that whether napoleon's rule 79 applies to a tool change (its trigger is new DLL bytes and a new build id) is the game's call, not this job's.

Model: Sonnet, reason: none needed (Sonnet is the default). A guard in one Python tool that already has the pending-restore code and host tests for `set`.
Budget about 35 tool calls: about 8 reading, 10 for the red tests, 8 to build, 5 for docs and gates, 4 for the report and the pull request.
Semver: patch
Subagents: none; do the work in this session.

## Start
1. `git pull`; `python3 wsc.py jobs next --id W94` and follow its mechanics. If this session's model is not Sonnet, stop and say so.
2. `python3 wsc.py gates --fast` and `python3 -m unittest tests.test_pc_deploy` for a baseline.
3. Read W25's report (`jobs/W25/report.md`: `game_lock`, the order "pending-restore check, then lock, then the running check", `--assume-closed`) and the
   B39 tests in `tests/test_pc_deploy.py` (`SetWaitsForRestore`).

## Target facts (check each again before relying on it)
- `proxy/tools/pc_deploy.py`: `uninstall` (takes `game_lock`, then `require_closed`, then `_uninstall`), `pending_restore(state)` (reads
  `<state>/watcher/profiles/_active.json`), `wait_for_restore(state, wait_s, sleep)` (waits, then refuses; its text says "pc_deploy set" and its docstring is
  written for `set`), `watcher_view`, `set_keys` (the one caller today), the `--wait-restore` flag on `set`, `lock_args`.
- **`pending_restore` and "no active profile".** Napoleon's guard (`upscale/pc/play.py` `profile_active`, read-only) treats a missing file, a JSON `null` and
  an empty object as "none". `pending_restore` treats a non-dict that parses, and an unreadable file, as pending (`{'name': '?'}`), and returns `{}` for an
  empty object (not `None`, so a caller that tests `is not None` sees a pending restore). Read the watcher's own writer (`harness/watcher.ps1`, the
  `Get-Active` and `Set-Active` functions or whatever clears `_active.json`) and settle what an idle watcher leaves on disk. If it writes `null` or `{}` when
  no profile is active, `pending_restore` is wrong for `set` too (it would refuse every time): fix it in this job, a test per shape, and say so in the report.
- `harness/acceptance.py` reads the same fact as `st['profile_active']` from `watcher.status` (the watcher's `Write-Status` writes it): a second source.
  Decision 1 says `uninstall` uses the file, as `set` does.
- `tests/test_pc_deploy.py`: `SetWaitsForRestore` (how it builds a fake watcher folder, heartbeat and `_active.json`) and `Lock` (the fake `job.sh`).

## Decisions already made for this job
1. **`uninstall` refuses while a profile restore is pending.** Same fact, same file as `set`: `pending_restore(state)`; no second reader. The refusal text
   names the profile and owner, the lock holder, whether the game runs, and the way out (release the lock that applied it, wait for `job.sh status` to show
   `profile_active` null, run the uninstall again). It says that an uninstall now would end with the config files put back.
2. **Order: the pending-restore check first, then the lock, then the running check** (W25 decision 5, the same order as `set`). The check before the lock lets
   a restore that is waiting on someone else's lock finish during the wait. After the lock is taken, check once more with no wait: a profile applied between
   the first check and the lock is refused too, and `game_lock`'s `finally` releases the lock as for any refusal. Nothing is moved and the install record is
   untouched on a refusal.
3. **`--wait-restore N` goes on `uninstall` with the same meaning as on `set`** (seconds, default 30, 0 refuses at once). Generalise `wait_for_restore` with a
   verb name so the printed text says `pc_deploy uninstall:` or `pc_deploy set:` and the refusal says what that verb would have done; `set`'s existing
   messages and tests keep passing unchanged.
4. **No watcher, nothing to see: proceed.** `uninstall` already needs `--state`. When `<state>/watcher` does not exist or the watcher is unusable, print one
   line that a pending restore cannot be seen (the `set` rule, `wait_for_restore`'s existing branch) and go on. Reason: a bare host, CI and a game folder with
   no watcher must still be able to uninstall.
5. **`--assume-closed` does not skip this check.** It vouches for "no game process" only (W25 decision 4); a pending restore is a fact about the watcher's
   files, not about the process list.
6. **`install`, `sync-lua` and `status` keep their behaviour** (open questions 1 and 2).

## Deliverables
1. Red tests first, in one commit (`tests/test_pc_deploy.py`, a class beside `SetWaitsForRestore`, reusing its fake watcher): `uninstall` with `_active.json`
   present refuses (`SystemExit`, text names the profile) and leaves the game folder, the install record and `_to_delete` as they were; with the file
   removed during the wait it proceeds and ends identical; `--wait-restore 0` refuses at once; no `<state>/watcher` proceeds with the one line;
   `--assume-closed` still refuses; a profile that appears after the first check and before the lock is refused and the lock is released (lock file gone);
   the CLI parser accepts `--wait-restore` on `uninstall`; one test per `_active.json` shape from Target facts (missing, `null`, `{}`, a named profile,
   unreadable), each with the answer the watcher's writer makes correct.
2. `uninstall` and `wait_for_restore` as in the decisions; `pending_restore` fixed if the Target facts show it wrong. `set`'s tests pass untouched.
3. `proxy/tools/pc_deploy.py` header: add the guard to `purpose:` (one clause) and `[--wait-restore N]` to the `uninstall` part of `usage:`; the row in
   `registries/tools/` follows the header (`python3 wsc.py reg add tools proxy/tools/pc_deploy.py --id proxy.tools.pc_deploy`, then `reg render` and look at
   the row in `_scratch/registries/tools.md`). Commit the file and its row together.
4. `docs/CONSUMING.md`, "The proxy, the harness and the save tools": one line that `uninstall` refuses on a pending profile restore, and the safe order
   (release the lock, wait for `profile_active` null, then uninstall). The file's size is gated (`doc_size`): pay for the line with a cut of the same size.
5. `python3 wsc.py gates` in full, then the report.

## Out of scope
- The game's own `play.py` and its tests (napoleon; it already has the guard, and its text is the model for this one).
- Any change under `harness/` (for example a watcher that does not restore an ini the kit owns): the guard is the fix; that is a different design and needs a
  decision row first.
- Removing a stray ini from a game folder (W25's `--move-stray` and `status` already name it; the two leftovers in napoleon are Liam's to clear).
- `install`, `sync-lua` and `status` (open questions 1 and 2).

## Open questions
1. Should `pc_deploy status` print a pending restore ("profile 'headless' (owner X) pending")? recommended: yes, one line and the exit code unchanged, but as its
   own later row (it changes `status` output, which agents parse); default after: 2026-11-13. Tag: taste.
2. `install` also snapshots the game folder, and a restore that lands after the snapshot changes what "vanilla" means. Should `install` refuse on a pending
   restore too? recommended: yes, the same helper, filed as a `later` row once this lands (a second guard with its own tests); default after: 2026-11-13.
   Tag: risk.
3. Should the default `--wait-restore` for `uninstall` be 30, as for `set`? recommended: yes, one rule for both verbs; default after: 2026-11-13.

## Kill criteria
- The watcher's writer leaves a shape on disk when idle that no reading of `pending_restore` can tell apart from a pending restore: stop and report the file
  contents; do not guess.
- Any existing `SetWaitsForRestore` or `Lock` assertion has to change for a reason other than the generalised wording: stop and report why.
- `python3 wsc.py gates` fails on a gate this job did not touch (a red `main`): stop and report the gate and the run.
- Over about 35 tool calls: stop, commit, report what is left.

## Finish
Report in `jobs/W94/report.md` with `## What was built`, `## Evidence` (the tests red then green, the branch's CI run id, the refusal text as printed, what the
watcher writes when idle), `## Deviations from the brief and why`, `## Open questions`, and what napoleon must do at its pin bump (nothing beyond the bump
itself; say whether `play.py`'s `profile_active` and `pending_restore` now agree). Write the usage line: `python3 wsc.py jobs usage W94 --write --from-json <file>`
(the core has no usage reader: write the JSON from this session's own count). Then:
`wsc reg set jobs W94 status=review report=jobs/W94/report.md` (`python3 wsc.py`)
Push `job/W94`, open the draft pull request, and stop: an independent reviewer merges (C18); the release workflow tags (C27).

## Registry gaps
- path: napoleon-remastered jobs/J67/report.md; owner: liam; reason: another repo's job report, read-only evidence (open question 4)
- path: napoleon-remastered jobs/J32/review.md; owner: liam; reason: another repo's review (round 2, S6 names the step that wrote the ini), read-only evidence
- path: napoleon-remastered upscale/pc/play.py; owner: liam; reason: the game's guard that this job mirrors; read-only, never edited from the core

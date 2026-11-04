# W38: Three CI flakes: the watcher's refused-launch race, the restore-wait test, the capture stress check

Model: Sonnet, reason: none needed (Sonnet is the default). One watcher function, two host tests, each change checked in CI; no DLL
source change, no PC. Budget about 50 tool calls.

## Goal
Three required checks went red on 2026-11-04 and passed on a plain rerun. Each one has a cause that can be read from the code, so each is
fixed at that cause instead of being rerun again. Liam asked for this on 2026-11-04 ("Fix now"). One of the three is a real watcher bug;
the other two are races inside a test's own checks.

## What exists and what goes wrong
1. **The watcher loses the proxy's refusal (a product race).** `harness/watcher.ps1` `Headless-Wait` first runs `Get-GameProcs`. If no
   game process is left, it returns "HEADLESS FAILED: <image> is not running after the start (exit code 2160 = the proxy refused; read
   <status_file>)" without reading the status file. A proxy that refuses writes `state: refused` with a `detail` and exits with 2160, so a
   fast refusal reaches the job as the generic line and loses its reason. The same race exists at the bottom of the loop: the status is read,
   the game writes `refused` and exits, then the process check returns "the game exited before reporting on_virtual". Seen in CI: PR 62's
   `harness-windows` (run 41852870156). `harness/tests/Test-Integration.ps1` case "headless launch: the proxy refusing (status refused, exit
   2160) ..." writes the status and kills the fake game at once, so it hits the race whenever the watcher is slow to look. That case's
   assertions threw before its cleanup ran (`Clear-Lock`, the file restore), so five later cases failed on its leftovers.
2. **The restore-wait test races its own timer (a test race).** `tests/test_pc_deploy.py`
   `SetWaitsForRestore.test_a_restore_that_finishes_during_the_wait_lets_set_write` starts `threading.Timer(1.0, unlink _active.json)`,
   while `pc_deploy.wait_for_restore` polls the same file once a second (`pending_restore` reads it). The two meet at 1.0 s. On Windows a
   delete fails while another thread has the file open, the timer thread dies, the file stays, and the 20 s wait ends in SystemExit. Seen
   on `main` `gates (windows-latest)` at the W22 merge (run 41857256437; core W22's `main_health` opened issue 74 for it).
3. **The capture stress check reads `waiting` too late (a test race).** `proxy/tests/test_capture.cpp` `Stress`, `case CapStep::start`:
   `if (open || waiting.load() != 1) ++errors;` runs after the render thread's CAS from Armed to Recording. If the render thread is
   preempted between the CAS and that load, the ctl thread can time out twice, abandon the capture (Recording to Abandoned) and store
   `waiting = 0`, all legitimately. The check then counts an error the state machine did not make. Seen on W20's `proxy` job (run 41844358937:
   "stress seed 3: 1 errors, final state 0", the same for seed 4, with all 6000 captures run, so it is not the refusal cap).

## Decisions already made
1. **Watcher: read the status before giving up, and only trust a status written for this launch.** In `Headless-Wait`, when no game
   process is found at the start, and when the game is found gone in the loop, read the status file once more (`Read-JsonRetry`). If it says
   `refused` and was written for this launch, return the refused line with its detail and exit code, exactly as the in-loop branch does.
   "Written for this launch" means its `pid` matches the pid the launch saw, or, when no pid was seen, the file's last write time is not
   older than the launch's start (pass the start time in, or record it in `Do-Launch`). Otherwise keep today's lines. Bump `$Version` to 1.4.1.
2. **Watcher test: cover both orders.** Keep the existing case and make it deterministic for the race: one launch where the fake game writes
   `refused` and exits before the watcher's first look, and one where it exits just after a status read. Both must end in "the proxy refused
   the launch: <detail> (exit code 2160". A stale `refused` from an older launch (an old pid, an old write time) must still be ignored.
   Move each case's cleanup (`Clear-Lock`, the file restore) where a failed assertion cannot skip it, if `Test-Case` allows, so one failure no
   longer fails the cases after it.
3. **Restore-wait test: no shared tick, and a delete that survives the reader.** Fire the timer between polls (for example at 1.5 s), and
   make its delete retry on `PermissionError` for a short while, so the test proves "a restore that finishes during the wait lets set write"
   on any runner. Keep the 10 s bound. `pc_deploy.py` does not change.
4. **Capture stress check: tie the waiter check to the state.** Count the start as waiter-less only while the capture is still Recording:
   the ctl thread stores `waiting = 0` only after it has moved the state out of Recording (abandon) or seen Done (only the render thread
   makes Done, after the start), so `waiting == 0` together with `c.Load() == kCapRecording` is a real break and the race above is not. Put
   a comment on that reasoning. No change to `proxy/src/capture.h`.
5. **Prove each fix.** For the stress check, run `test_capture` many times in a loop under load (for example 200 runs, or a build with a
   `std::this_thread::yield()` storm right after the CAS) and quote the counts in the report. For the restore-wait test, run it 50 times on
   Windows. For the watcher, run `Test-Integration.ps1` (or the cases you touched) on Windows at least 10 times.
6. **VERSION 0.30.1** (a fix release: no interface or schema change); merge `main` and take the next free number if it moved. No decision row.

## Out of scope
- Any change to `pc_deploy.py`, the capture state machine, or the DLL.
- The other `harness-windows` cases, unless they share the cleanup fix in decision 2.

## Done when
- The three changes are in, with the loop runs above quoted in `jobs/W38/report.md`.
- `python3 wsc.py gates` is green, and CI's `gates` (both), `proxy` and `harness-windows` are green on the branch.

## Kill criteria
- A fix can only work by changing `pc_deploy.py`, `capture.h` or a DLL input: stop, commit what is done, and report.
- A loop run still shows the failure after the fix, or CI is red after three fix attempts, or more than about 50 tool calls: stop, commit,
  and report what is left.

## Finish
Report in `jobs/W38/report.md` (each cause, each fix, the loop counts, the red and green runs, the version taken, deviations, open questions), then
`wsc reg set jobs W38 status=review report=jobs/W38/report.md` (`python3 wsc.py`). Push `job/W38`, open the draft pull request, and stop: an
independent reviewer merges (C18).

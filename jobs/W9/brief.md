# W9: Acceptance and scene launches: build id after launch, staged saves, hist_nile retry, flakes, evidence shas, watcher preflight

Model: Sonnet, reason: none needed (Sonnet is the default). Every item is Python in two harness tools that already have host tests (`harness/acceptance.py`,
`harness/ctl.py`; `tests/test_acceptance.py`, `tests/test_ctl.py`), the new behaviour is pure functions plus injected seams, and the PC part is measurement, not
reverse engineering (no DLL, no engine memory). Budget about 190 tool calls: about 150 for steps 1-9 (host side) and about 40 for the PC part (steps 10-12).
At the cap, stop, commit what is green and report what is left. Kill criteria are at the end.

## Goal
Backlog B26 (B31 is the same defect), B51, B60, and audit 2026-11-03 H3 (core half), H4, H5, H10 (`napoleon-remastered` `docs/audits/AUDIT_2026-11-03.md`, read-only;
the row `registries/jobs/W9.json` lists them). The 20-pass acceptance run (rule 79 of the first consumer) is the evidence a harness or proxy change is good, and today it is
weak and expensive in six ways:
1. **Pass 1 is labelled with the previous launch's build** (B26/B31, H5): `acceptance.py:361` reads the identity before the launch from `proxy.log`, which is the *last* launch's
   log (the DLL opens it with CREATE_ALWAYS, one log per launch); on a fresh install it falls back to the kit id (`ctl.py:371`). Napoleon J8 hand-edited a ledger line for it.
2. **One flake restarts the run from zero** (H4, B60): the hist_dresden to hist_nile relaunch sometimes gets no `on_virtual`, the pass fails, and a streak of 9 or 16 is lost. Napoleon J24
   needed 49 ledger lines for 20 passes (runs `20261103_j24acc` pass 10 and `20261103_j24acc2` pass 17), about 8 minutes each.
3. **The cause of that flake is unknown, and the evidence for it is destroyed**: `Pc.launch` already retries a lost headless start once (`ctl.py:325-330`), the two J24 failures happened
   *with* that retry (the pass files show one job's output, the retry's), and the retry overwrites the first attempt's `proxy.log` and `headless_status.json`.
4. **A campaign row past the start cannot join the acceptance order** (B51): nothing stages a supplied save (napoleon J46).
5. **A reused `--run` id silently overwrites earlier evidence** (H5, `acceptance.py:373-377`).
6. **A pass file proves little** (H3): the docstring (`acceptance.py:16-17`) promises shot sha256s and none are written; the ledger line is not tied to its file; and the
   watcher's identity is the hand-kept string `$Version` (`watcher.ps1:11`, H10), so a changed watcher that keeps its version passes on old evidence.

## What exists (read before building)
`CLAUDE.md`, `docs/DECISIONS.md` (C13, C14), `docs/CONSUMING.md` ("The proxy, the harness and the save tools", "The job pipeline"),
`docs/BACKLOG.md` (B26, B31, B51, B60 in full), `docs/REVIEW.md`, `jobs/W8/report.md` (how the harness host tests run here), `jobs/W10/brief.md` (the lock owner becomes the session id).
Citations checked against the tree at 0.25.0 (main `020244c`):
- **`harness/acceptance.py`**: header 1-20; `ledger_line` 139-142; `streak` 145-153; `run_pass` 157-205 (the `launch` at 172, the shot step at 187-189); `PcEnv` 217-302 (`lock` 238-245,
  `release` 247-258, bare `sh('touch')` 245, 281, 294; `identity` 299-302); `pass_file` 305; `run_problems` 309-334 (Pillow, branch, lock and profile checks); `cmd_run` 337-386
  (identity read at 361; pass file write 373-377 with `write_text`, which overwrites; ledger append 378-380; stop at first failure 382-385); `main` 468-491 (`--owner` default
  `claude-acceptance` at 472, `--session` default `acceptance`).
- **`harness/ctl.py`**: `scenario_target` 110-120 (a campaign row's `save` field must start with `campaign:...`); `Pc.status` 247; `Pc.launch` 311-338 (retry 325-330; returns
  `retried_after` only when the second attempt succeeds); `Pc.exit` 348-361; `Pc.build_info` 363-372 (the `proxy.log` read 369-370, fallback to `install.json` 371);
  `Ctl.run` 517-525 (every exception becomes a `failed` result with `Type: message`); `v_scene` 532-577 (`pc.launch()` 545-546; the relaunch that leaves a campaign or a
  historical battle 549-554).
- **`harness/watcher.ps1`**: `$Version` 11; `Headless-Wait` 891-919 (the 180 s wait; the three `HEADLESS FAILED` texts 895, 915, 919; a `refused` state 910-912); `Launch-Job` 922-946
  (`headless_wait_s` header 940); `Write-Status` ~1108-1120 (`version` is in `watcher.status`). The installed copy is `<state_dir>/<watcher_subdir>/src/watcher.ps1`
  (`harness/install.ps1:23,42`; `update.ps1` replaces it from a kit, sha-checked); the installed proxy kit's manifest is `<state_dir>/kits/<kit_id>/manifest.json`
  (`pc_deploy.py send`, 403-420), with a sha256 per file.
- **`proxy/src/dllmain.cpp:86`** logs `launch <id>: <game> proxy d3d9.dll build <BUILD_ID> loaded into <exe> (pid <n>, base ...)` into `proxy.log`; `log.cpp:45` opens it CREATE_ALWAYS.
  **W24** (`registries/jobs/W24.json`, no brief on origin when this was written) makes the DLL also log its own module sha256 there; its line format is not fixed yet (decision 7).
- **Schemas**: `schemas/scenarios.schema.json` (`additionalProperties: false`; a campaign row requires `save`, text). The stdlib subset validator is `warscape/schema.py` (`validate`).
- **Napoleon's evidence (read-only, other clone)**: `harness/acceptance/ledger.jsonl` (311 lines, 24 runs; line keys `pass utc build_id watcher kit branch run evidence result steps`);
  `harness/runs/20261103_j24acc/pass_10.json` ("the game exited before reporting on_virtual (last status: starting DllMain)") and `20261103_j24acc2/pass_17.json` ("no on_virtual status for pid
  31820 within 180 s (last: (no status yet)); the game was killed"); both on step `hist_nile:scene`, both after `exe_sha1` and `hist_dresden:*` passed. Its rule 79 is
  `tools/jobs_hooks.py:305-345` (`acceptance_problems`; the watcher is read from `$Version` by regex at :349), and J75 / J78 are its follow-up jobs.
- **Host tests to extend**: `tests/test_acceptance.py` (19), `tests/test_ctl.py` (53; `PcLaunch` 417 builds a fake `sh` and a fake clock, copy that pattern), `tests/test_job_sh.py`.
  `harness/tests/Test-Unit.ps1` only if you touch `watcher.ps1` (you should not, decision 9).

## Decisions already made (do not reopen; each has its reason)
1. **The build id is read after the launch, from the launch's own log line, and never falls back.** `Pc.launch` reads `proxy.log` once the frontend is up, requires the load line's
   `pid` to equal the running game's pid (so a stale log from the previous launch cannot answer), polls up to 10 s for it, and records
   `{pid, build, dll_sha256_logged, utc}` on a new list `Pc.launches` (one entry per launch, including the ones `v_scene` makes by itself). `Pc.build_info(strict=False)` keeps its
   callers' behaviour (perf labels); acceptance calls it `strict=True`, which raises when there is no matching line. A pass takes its `build_id` from `launches[0]`; a later launch
   in the same pass that reports another build fails the pass (step `build_stable`). A pass with no recorded launch has `build_id: null` and cannot pass. Reason: the log of *this* process is the source; the kit id was only a stand-in.
2. **Staged saves (B51) are a row field plus an adapter block, copied under a harness name and cleared after.** A scenario row may carry `save_file` (path relative to the game
   repo root) and `save_sha256` (64 hex), both optional and allowed only with `kind: campaign`. The adapter carries `ctl.saves = {"anchor": "appdata" | "game", "dir": "<folder>",
   "ext": "<.ext>"}` (anchors are the ones `config_files` already use, `acceptance.py:263`); the core names no folder or extension. `ctl.stage_save(row, adapter, repo_root)` is a context
   manager: verify the source's sha256 against `save_sha256` (refuse on mismatch or a missing file, naming both), write `<dir>/<harness name><ext>` through a temp file and
   `os.replace`, yield the target `campaign:<harness name>`, and on exit remove that one file (only a file whose name starts with `wsc_`, never anything else; a leftover from a crash is
   overwritten and said). Harness name: `wsc_` + the row id with every character outside `[A-Za-z0-9_-]` replaced by `_`, cut to 72 characters with an 8-hex hash of the id when cut (the DLL's
   `SafeToken` accepts only plain names up to 80, `devcore.h:190-194`). `scenario_target` returns that target for a row with `save_file` (the `save` text stays a description); a row with
   `save_file` and no `ctl.saves` block is refused naming the key. `v_scene` stages before the autostart request and clears in a `finally`. Reason: the game lists saves at the front end, so the file must exist before the request; a name the harness owns cannot collide with Liam's saves.
3. **The hist_nile retry stays in `Pc.launch`, not `v_scene`, and becomes evidence.** `v_scene`'s relaunch (`ctl.py:554`) and every other launch go through `Pc.launch`, so one retry
   there covers all callers; adding a second one in `v_scene` would make four launches. Changes: (a) before the retry, copy the failed attempt's `proxy.log`, `headless_status.json` (the
   adapter's `headless.status_file`) and the job's output into `<state>/acceptance/<run>/.../attempt_1/` (or `<state>/_scratch/<owner>/` outside a run; the directory is a `Pc` attribute `evidence_dir`
   set by `PcEnv`), because the retry's launch recreates them; (b) wait `retry_settle_s` (adapter `ctl.launch.retry_settle_s`, default 10) after the failed attempt's kill before the retry
   (injected `sleep`); (c) return `attempts: [{rc, tail}, ...]` in the launch result and raise `HeadlessLaunchLost(RuntimeError)` (new, in `ctl.py`) carrying every attempt's last 300
   characters when the retry also fails; `Ctl.run` turns it into a `failed` result with the same reason text plus `cause: "headless_launch_lost"`. Reason: today the first attempt's text is lost
   and the second's is all the report shows; the cause cannot be found from what is kept.
4. **Exactly one failure is a flake: a lost headless launch.** A pass is `result: flake` when (and only when) the first failed step carries `cause: "headless_launch_lost"` (or the cleanup
   exception is a `HeadlessLaunchLost`), which means two launch attempts ended in one of the watcher's three pre-`on_virtual` texts (`is not running after the start`, `exited before
   reporting on_virtual`, `no on_virtual status ... within N s`), **and** the `exe_sha1` step of that pass passed. Not a flake, always `fail`: `the proxy refused the launch`
   (`watcher.ps1:912`, a real defect with an exit code), `bad size`, a failed exe pin, a failed `settings_identical`, any later step (`load`, `cam`, `shot`, `shot_match`, `perf`, a
   `frontend` wait), a lock or restore failure, any exception that is not `HeadlessLaunchLost`. Reason: a flake fails before the build under test ran; a narrow test cannot hide a build defect.
5. **N flakes per streak: configured in the adapter, default 1, capped in the core at 3, recorded on every line.** `acceptance.max_flakes` in the harness adapter (game-owned data, not
   `baseline.json`, which a branch could loosen: H3); `--max-flakes N` may only lower it; a value above `MAX_FLAKES_CAP = 3` is refused. Every ledger line carries `flakes_allowed`. A flake
   **never counts as a pass**: `streak()` skips flake lines of the same build or of `build_id: null` (a launch that died before the DLL logged cannot name a build) without counting them,
   and the (N+1)th flake in the streak's span ends it like a fail; a flake of another non-null build ends it. A run continues after a flake (the next attempt is a fresh pass with
   the next attempt number) until `--passes` passes are recorded, a fail, or the flake budget is spent. Reason: an old consumer reading `result == 'pass'` treats a flake as a break, which
   is today's behaviour, so a consumer that has not migrated is only more conservative.
6. **A `--run` id with evidence is refused before anything starts** (`run_problems`): any `harness/runs/<run>/pass_*.json`, any ledger line naming that run (in the ledger being appended
   to), or any `<state>/acceptance/<run>/pass_*` folder. The pass file is written with open mode `'x'`, so a race still cannot overwrite. No override. `measure` is unchanged.
7. **Evidence in the pass file, schema 2.** New `schemas/acceptance_pass.schema.json` (stdlib subset, checked in the tests with `warscape/schema.py`) and a pure
   `acceptance.pass_problems(doc)`. Fields, all new ones required in schema 2: `schema: 2`, `pass` (the attempt number), `start_utc`, `end_utc`, `result` (`pass|fail|flake`), `passed`,
   `build_id`, `build_source: "proxy.log"`, `watcher` (version string, display only), `kit` (kit id), `steps`, and `evidence` = `{exe_sha1, baseline_sha256 (the baseline.json this pass
   compared against), shots: {<step>: {sha256, bytes}} (one per shot step, hashed from the file `ctl` wrote, plus the baseline shot's sha256 for compared steps), kit_sha256 (sha256 of
   `<state>/kits/<kit id>/manifest.json`), dll_sha256 (the installed `d3d9.dll`, found through `install.json` files, else `<game_dir>/d3d9.dll`), dll_sha256_logged (from the `proxy.log`
   self-hash line, or null when the DLL does not log one yet), watcher_sha256 (sha256 of the installed `src/watcher.ps1`), watcher_kit_sha256 (sha256 of `harness/watcher.ps1` at the
   core's HEAD), launches: [...]}`. If `dll_sha256_logged` is present and differs from `dll_sha256`, the pass fails (step `dll_hash`: the file changed under the run). The self-hash line is
   matched by `\b(?:sha256|module sha256)[ =:]+([0-9a-f]{64})\b` on a `proxy.log` line that also contains `d3d9.dll` or `module`; **read W24's brief or merged code if present and use its exact format**,
   keep the regex as the fallback in one named constant. Reason: the file on disk is always available, so evidence never waits for W24; together they catch a replaced DLL.
8. **The ledger line copies the evidence's key facts and the file's hash.** `ledger_line` gains `watcher_sha`, `dll_sha256`, `kit_sha256`, `evidence_sha256` (sha256 of the pass file's bytes,
   hashed after writing), `schema: 2`, `flakes_allowed`; the pure `ledger_line_matches(line, doc, file_sha)` checks every shared field. New subcommand `acceptance.py check-pass FILE...` runs `pass_problems`
   and, given `--ledger`, `ledger_line_matches` for each file's line; it is what a consumer's gate calls. `streak(lines, build_id, watcher, max_flakes=0, watcher_sha=None)` keeps its old
   behaviour with the defaults and the CLI `streak` gains `--watcher-sha` and `--max-flakes`. Reason: H3 asks for line-to-file agreement; the hash on the line gives it without the consumer
   having to understand the file.
9. **The watcher preflight compares sha256 of bytes, runs in `run_problems`, and has no override.** Installed side: open `<state_dir>/<watcher_subdir>/src/watcher.ps1` with mode `'rb'`
   and read it (no write, no rename, no touching `jobs/`, `profiles/` or the lock; the watcher itself never holds that file open exclusively, and `update.ps1` swaps it atomically).
   Kit side: `git -C <core root> show HEAD:harness/watcher.ps1` (the committed bytes at the core's HEAD, which in a game repo is the pinned commit; a dirty working copy is therefore irrelevant;
   if git cannot answer, refuse naming why). Also parse `$Version = '...'` from the installed bytes and compare it with `watcher.status` `version` (the running watcher must be the installed one: a
   watcher that was updated on disk and never restarted is refused). A mismatch is a refusal with the fix named: send a harness kit (`pc_deploy.py kit --what harness`, `send`) and run
   `job.sh update kit=<id>`. `watcher_status` and the two shas are injectable parameters so the tests need no PC. The fix itself stays Liam's / the orchestrator's (the audit's
   "watcher self-update" is a separate idea, not this job). Reason: H10 and automation 5: the version of a watcher is its content, and it must be checked before pass 1 spends a ledger line.
10. **Acceptance owns its lock through W10's API.** If `harness/job.sh` on main has `holds` and the owner/session pair rule (W10 merged: `grep -n 'holds)' harness/job.sh`), then `acceptance.py`
    defaults `--owner` and `--session` to the session id as W10 decides (no `claude-acceptance` default), and every bare `sh('touch')` at `acceptance.py:245, 281, 294` becomes `touch <owner>`.
    If W10 is not merged when you start, change nothing about the lock, say so in the report, and keep the three touches in one helper (`PcEnv.touch()`) so W10's fix is one line. Reason: a bare `touch`
    is refused after W10 and would break every pass.

## Steps (host tests first; run `python3 -m unittest tests.test_acceptance tests.test_ctl` after each step)
Branch `job/W9` from current main. Run `git config core.hooksPath .githooks`. Every commit message ends with the two trailer lines (`Claude-Session: ...`, `Co-Authored-By: ...`) in its final paragraph.
1. **`Pc.launches` and the strict build** (decision 1): extract `Pc.read_launch_line(pid)` (regex `d3d9\.dll build (\S+) loaded into .* \(pid (\d+)`, poll 10 s via injected clock and
   sleep), call it at the end of `Pc.launch`, add `strict` to `build_info`. Tests: a stale log of another pid is not accepted; a fresh install with no log until the launch yields the DLL's
   build on pass 1 (the J8 case); strict with no line raises; non-strict keeps the old fallback for perf. Failing fixture: restore the read-before-launch and the fresh-install test must fail.
2. **`HeadlessLaunchLost`, attempts and the evidence copy** (decision 3): tests with the `PcLaunch.pc` fake: first attempt fails and the retry works (result carries `attempts` and
   `retried_after`, as now); both fail (raises with both texts, `Ctl.run` result has the cause); a non-headless failure is not retried (the existing `test_other_launch_failures_are_not_retried` stays
   green); the log and status file of attempt 1 are copied before the second `launch` job is sent (assert on the order of `sh` calls and the copied bytes); `retry_settle_s` sleeps once.
3. **Flake classification** (decisions 4 and 5): pure `classify(passed, steps)` returning `pass|fail|flake`, and the streak. Tests, one per branch of decision 4 (each non-flake case listed there is a
   test, including a `proxy refused` text that must stay `fail` and a launch loss after a failed `exe_sha1`), `streak` with 0, 1 and 2 flakes at N=1 and N=2, a flake of another build, a flake with
   `build_id: null`, a flake as the first and as the last line, and "a flake never counts as a pass" (`streak` of 19 passes plus one flake is 19, not 20). Cap test: `max_flakes=4` refused.
4. **`cmd_run` loop** (decisions 4-8): attempts instead of pass indices; a flake continues, a fail or an exhausted budget stops (exit 1, message says which); the pass file opens with `'x'`; the
   ledger line is built from the written file's hash; the run stops when `--passes` passes are recorded. Keep `run_pass` pure: it gains optional env callables (`file_sha`, `evidence`) with
   defaults so existing tests pass unchanged; the shot step records `sha256` and `bytes`. Tests with a fake env: three passes, one flake in the middle, ledger has 4 lines, `streak` 3; a run id with a
   pass file / a ledger line / a state folder is refused (three cases) and a pass file already present is never overwritten.
5. **Schema and `check-pass`** (decisions 7 and 8): the schema file, `pass_problems`, `ledger_line_matches`, the subcommand. Tests: a valid doc; each required field missing; a doc whose line says
   another build; a line whose `evidence_sha256` is not the file's; a schema-1 doc (no `schema`) is reported as legacy, not as valid.
6. **Preflight** (decision 9): `watcher_problems(installed_bytes, kit_bytes, status)` pure, wired into `run_problems`. Tests: equal shas pass; one differing byte refuses and names both shas (12 hex) and the
   fix; status version differing from the installed `$Version` refuses; installed file missing refuses; the installed copy is opened read-only (a test that makes it read-only and checks mtime and bytes after).
7. **Staged saves** (decision 2): `stage_save`, `scenario_target`, `v_scene`, schema fields, `ctl.saves` adapter docs. Tests on temp folders: staged under the harness name and cleared after a normal
   scene and after a failing one; a wrong sha refuses before any write; a name with unsafe characters and a long id; a leftover file is overwritten and said; a file not starting with `wsc_` is never
   removed; a save-less campaign row behaves as today; no `ctl.saves` block refuses. Failing fixture: skip the clear and the leftover test must fail.
8. **Lock calls** (decision 10): the `touch` helper and, if W10 is merged, the owner defaults.
9. **Docs and registry**: `docs/CONSUMING.md` gets a short section "Acceptance evidence (0.26.0)" (about 1.5 KB, keep the file under 30 KB): the pass-file schema, the ledger-line fields, `flake`, `check-pass`, the
   preflight, the staged-save row fields and adapter block, and what a consumer must change (below). Update the `acceptance.py` header (`usage:` must list `check-pass` and the new flags; the `tools` gate compares
   headers with `registries/tools.jsonl`: re-run `python3 wsc.py reg add tools harness/acceptance.py` if it asks) and the docstring lines 16-17 so they say what is now written. Remove B26, B31 and B51 from
   `docs/BACKLOG.md` (and B60 if step 11 finds and fixes the cause; otherwise rewrite its row with the findings, dated, with the run ids). Bump `VERSION` (below). Run `python3 wsc.py gates`.
10. **PC part, setup** (`needs_pc`; do it on Liam's PC in this chat, `harness/README.md` and the lock rules apply; take the game lock, release it when done). Check what the PC is: the installed watcher's sha equals the
    core HEAD's (`python3 harness/acceptance.py run` will now say it does not if not; if the installed watcher is older, **stop this part and ask**, do not update the watcher yourself: the kit update is Liam's). Run
    the preflight against the real installed copy once and keep its output.
11. **PC part, B60** (what the PC proves; nothing here is host-testable): with the new evidence copy in place, run the loop `ctl.py scene hist_dresden`, then `ctl.py scene hist_nile` (the relaunch that
    flakes) at least 30 times, varying only the gap between the exit and the relaunch (`retry_settle_s` aside, an extra `--settle` you add to the loop script in the scratch folder, not to `ctl.py`): 0 s, 5 s, 15 s,
    10 cycles each, randomised order, one line per cycle in `<state>/_scratch/<owner>/b60.csv` (utc, gap, outcome, launch_s, attempts). For each lost launch keep attempt 1's `proxy.log` tail, `headless_status.json` and
    the watcher's job output, and answer: (i) did the game process exist, how long, and what was the last status (the two J24 texts differ: a crash after `starting DllMain` versus no status at all); (ii) did the previous
    process's exit finish first (window gone, `Get-Process` empty) or still tear down; (iii) did the `vdisplay` attach (the watcher log and `vdisplay_restore.json`) complete before the launch; (iv) does a longer gap
    change the rate. If one gap clearly removes the flake, make it the default (`ctl.launch.relaunch_settle_s`, applied in `Pc.launch` when the previous game exited within it: host-tested with the fake clock) and
    prove it with 30 more cycles at that default. If the cause is a crash in the DLL after DllMain, it is not this job: file it as a backlog row with the dump path and the log, and still ship decisions 3-5. If it is in
    `watcher.ps1` (for example `Headless-Wait` reading a stale status file), file the fix as a new backlog row with the evidence rather than editing the watcher: a watcher change moves its sha, forces a kit update and a new 20-pass run for
    every consumer (decision 9 makes that visible), and belongs in its own job. A null result (no failure in 30 cycles) is reported as such with the cycle table; B60 stays open, with the new evidence, and nothing is "fixed".
12. **PC part, staged save and a short acceptance sitting**: (a) stage one real save (a save already in the game's save folder, copied to the scratch folder as the row's source; a throwaway scenarios file in the
    scratch folder, not committed) and run `ctl.py scene` on it: loaded, the staged file gone afterwards, Liam's own saves untouched (list the folder before and after, names and sizes). If the PC has no save, say so and
    list it as the open item for the consumer (J46's two saves). (b) `acceptance.py run --passes 3 --run <fresh id>` on the PC (it will exercise the preflight, the build read, the shas and the run-id refusal on a second
    start with the same id). Write the three pass files and the ledger lines to a **scratch ledger** (`--ledger` in the scratch folder), never to a game's committed ledger. Run `check-pass` over them.

## Proof and what done looks like
- All new host tests pass on this PC and in CI (`gates` on ubuntu and windows, `harness-windows`); the failing fixtures named in steps 1, 3, 4 and 7 each go red against the old code and green after (scratch commits in a
  throwaway worktree, not pushed, as in W8's report).
- `python3 wsc.py gates` green; `python3 wsc.py policy --branch job/W9 --base origin/main` ok apart from the report, review and `done` row.
- Step 10-12 evidence in `jobs/W9/report.md` (the orchestrator writes it from your text): the preflight output, `b60.csv` summarised (counts per gap, the two or more failure texts, the answers to (i)-(iv)), the staged-save
  listing before and after, the three pass files' evidence blocks, the `check-pass` output. Dated, with run ids.
- Nothing in the core names a game or a game path (`tests/test_moved_tools.py` `NoGameNames` scans the moved trees: the examples above are placeholders, not game files). The committed ledger of no game is touched.
- The report states what a consumer must change (below) and which behaviours are the same as before (a game with no `ctl.saves` block, no `max_flakes`, no flakes behaves as 0.25.0 except for the preflight, the shas and the
  run-id refusal).

## What a consumer must change (goes in the report and in CONSUMING.md)
Napoleon's rule 79 (`tools/jobs_hooks.py:305-345`, `acceptance_problems`; J75 requires these once its pin carries this job):
- **Flake lines**: skip `result: flake` lines (not a pass, not a break) while their count in the span is at most `flakes_allowed` (never above 3) and their build is the line's build or null; one more ends the streak.
  Without this change a flake line simply ends the streak, as a fail does today.
- **Require the evidence of schema 2** on every counted pass: `evidence_sha256` equals the sha256 of the committed `evidence` file at the branch head; the ledger line and file agree (`acceptance.py check-pass`);
  the 20 lines have unique `evidence` paths and unique `(run, pass)`; one `dll_sha256` across the streak and (when W24 is in) `dll_sha256_logged` equal to it; `baseline_sha256` equals the committed baseline.
- **The watcher is its sha, not `$Version`**: replace the regex at `jobs_hooks.py:349` by the sha256 of `core/harness/watcher.ps1` at the branch HEAD and require every counted line's `watcher_sha` to equal it
  (the `watcher` string stays for display). Lines written before this job carry no shas: they stop counting for a branch whose pin includes this job.
- A pin bump past this job changes `harness/`, so rule 79 asks for 20 passes (napoleon J78 is that job): they must run on a PC whose installed watcher is the kit at that pin (the preflight refuses otherwise).
  Also: the first consumer's adapter gains `acceptance.max_flakes` (suggest 1) and, for staged rows, `ctl.saves`.

## VERSION
The next free minor at build time: the highest of `VERSION` on `origin/main` and on every open `origin/job/*` branch, plus one minor (main is 0.25.0 at writing; expect 0.26.0 or later). Merge `origin/main` into `job/W9` before the final push and re-check; a tag is Liam's (the `core_pin` gate reads `VERSION`).

## Open questions (Liam chooses; the recommended answer is what the builder does if no answer comes)
1. **Add W10 to this job's `depends_on`?** Both change the lock calls in `acceptance.py`. Recommended: yes (`depends_on: [W8, W10]`), so the builder always has `holds` and the session-id owner; the orchestrator makes
   the row edit. Without it decision 10 covers both orders.
2. **Flake allowance default**: N = 1 per streak, hard cap 3 (decision 5). Recommended: accept. N = 2 would have saved J24 its second restart; a larger number starts to hide a launch rate worth fixing.
3. **If the PC cannot reproduce the flake in 30 cycles** the job still ships with B60 open and the evidence in place. Recommended: accept; the next real flake then arrives with its logs.
4. **Watcher self-update** (audit automation 5) is not in this job. Recommended: a separate row after W9, since it changes the watcher and every consumer's 20 passes.

## Kill criteria
- Tool-call cap about 190 (150 host, 40 PC). At the cap: commit what is green, report what is left.
- PC part: stop after 60 launch cycles or about 2 hours of PC time in total, or the first time a launch leaves the game running after the watcher reports it killed (a zombie: `PC NEEDS REBOOT`): stop, release the lock,
  tell the orchestrator, do not retry, do not reboot yourself.
- Stop and report, rather than work around, if: the installed watcher differs from the core HEAD's (step 10); the pass-file or ledger change would make a **committed** napoleon ledger line invalid (this job only appends
  new-shape lines; it never rewrites or validates old ones); the schema subset in `warscape/schema.py` cannot express the pass file (C3: use plain Python checks in `pass_problems`, do not extend the validator); a fix for B60
  needs a change in `watcher.ps1` or the DLL (file a backlog row, decision in step 11); `test_job_sh.py` or any existing test goes red for a reason you cannot tie to your change after two attempts.

## Finish
The orchestrator writes `jobs/W9/report.md` from your report text, pushes `job/W9` and opens the draft pull request; an independent reviewer merges (C18); Liam tags. Never mark the row `done`. Last step (`python3 wsc.py` in the core): `wsc reg set jobs W9 status=review report=jobs/W9/report.md`

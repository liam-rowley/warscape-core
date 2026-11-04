# W35: Crash dump symbolisation and guarded verbs for recurring permission asks

Model: Opus, reason: the linker map is a new flag on the DLL's link line (a DLL input; the id changes for every consumer) and the minidump reader parses
a binary format whose mistakes name the wrong function; the first consumer's D52 gives builds to Opus. Budget about 110 tool calls (CI round trips
included: the artifact upload and the download are proved only by pushes). At the cap, stop, commit, and report what is left.

## Goal
Audit 2026-11-03 (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`, read-only), "Automation opportunities" item 7 (rest). Two halves, one job because
both change what an agent can do without asking Liam:
- **Frames named in the cloud.** A crash on the first consumer's PC leaves a minidump (`proxy/src/crash.cpp`: `<mod>\dumps\<launch id>_<code>.dmp`, and
  WER LocalDumps via `proxy/tools/wer/`); naming its frames today needs the PC and a debugger. The DLL is linked with no map (the `build.sh` link line passes
  no `-Wl,-Map`), so nothing in CI can turn an address into a function. Keep the linker map per build id as a CI artifact and add a verb that symbolises a
  minidump against it.
- **Guarded verbs for the permissions sessions keep asking for.** Two recur in the first consumer's reports: moving a stale `vdisplay_restore.json` aside
  (its J44 and J10 reports, J48's brief) and edits to the agent settings file (`.claude/settings.json`) for one more allowed command. Each becomes a verb
  that checks the state it changes and refuses otherwise, so a session runs the verb without a one-off ask and Liam's judgement lives in the guard.

## What exists (read before building)
- `CLAUDE.md`, `docs/DECISIONS.md` (C14, C16, C24 and the W24 and W22 rows), `docs/CONSUMING.md` ("The proxy, the harness and the save tools"),
  `docs/PROXY_BUILD.md` (W24), `jobs/W24/brief.md` and `report.md` (the build id and the self-hash line; W24 left `-Wl,-Map` to this job, keyed by the id and
  the sha256 it prints), `jobs/W22/brief.md` (the CI summary blocks, `ci_render.py`).
- `proxy/tools/build.sh`: `build_dll` and the link line (`-Wl,--no-insert-timestamp` and the `-ffile-prefix-map` flags that keep the DLL reproducible), the
  `repro` command (a second build from another path must stay byte-identical, so a map must not change the DLL), the build line printing the id and sha256.
  `ci/gates.yml.in` `proxy` job and `warscape/ci_render.py` (the render blocks; the rendered `.github/workflows/gates.yml`).
- `proxy/src/crash.cpp` (dump flags: `MiniDumpWithIndirectlyReferencedMemory | WithDataSegs | WithThreadInfo | WithUnloadedModules`, no full memory, so stack
  words exist only as far as indirect memory reaches), `proxy/src/crashpolicy.h`, `proxy/tools/wer/wer_localdumps.ps1` (full dumps, out of process).
- The first consumer's crash-dump tools (napoleon `release/core/build_release.py` `crash_dump_cmd`, J74): they turn dumps on and off; nothing reads one.
- `harness/watcher.ps1` around lines 750-815 (the vdisplay restore: moves into `_to_delete\` as `vdisplay_restore_<utc>.json[.dropped]`, `Log`, the stale and
  dropped cases, `test_vdisplay_script`) and 250-268 (the unique-name move of lock expiry); `harness/job.sh` (the verbs, `holds_check`, `owner_ok`, the final
  exit-code map); `harness/README.md` (the state folder table: `vdisplay_restore.json` exists only while a launch has changed the display mode); `harness/tests/`.
- The first consumer's `tools/claude_hook.py` (J76) denies shell writes into the state folder and the AppData prefs and exempts only the core's `pc_deploy.py`
  and `job.sh`: that is why a guarded state change must be a `job.sh` or `pc_deploy.py` verb, never a new script.
- `warscape/verbs/` (a verb: `NAME`, `HELP`, `add_arguments`, `run`; `docs/CONSUMING.md` lists the core verbs a game must not shadow), `proxy/tools/layout.py`,
  `warscape/tools.py` (tool header rules).

## Decisions already made (follow them; a deviation goes in the report with its reason)
### The map, per build id
1. **Link with a map, never change the bytes.** The link line gains `-Wl,-Map,<file>.map`, written next to the DLL's output folder (not inside it: kits and
   installers copy that folder), e.g. `build/proxy/<adapter>/d3d9.map`. Add `--cref` only if the size is acceptable (say the size in the report). `repro`
   and a new check that the DLL's sha256 is identical with and without the flag stay green; if the flag moves one byte, stop (Kill criteria).
2. **Name the map by what it describes.** `build.sh` writes `d3d9.map` and a sidecar `d3d9.map.json`: `{build_id, dll_sha256, image_base, size}`. No timestamp
   enters either file (the map is reproducible too; `repro` compares the two maps). The id and sha256 are those the build line prints.
3. **CI keeps it.** The `proxy` job uploads `proxy-map-<build id>` (the map, the sidecar, the sha256 line) with `actions/upload-artifact` (pin a full commit
   sha, not a tag; retention 90 days, the maximum) and names it in the step summary W24 added. It is a render block in `ci_render.py`, so a consumer's rendered
   workflow gets it, with a test in `tests/test_ci.py`. The artifact name uses what `build.sh` printed, never a second computation.
4. **A map outlives 90 days only by being kept.** Release builds are the consumer's: the core only says in `docs/PROXY_BUILD.md` that a release attaches
   `d3d9.map` and its sidecar to the release it publishes, and the verb reads a map from a path. No release code here.

### The verb
5. **`wsc crash symbolise <dump> [--map <file> | --build-id <id> [--run <id>]] [--log <proxy.log>] [--module <name>] [--json]`** (`warscape/verbs/crash.py`
   and a library module `warscape/minidump.py`; standard library only, no `dbghelp`, no network unless `--build-id` asks). It reads the streams that say what
   happened: `ExceptionStream` (code, address, thread), `ModuleListStream` (name, base, size; the proxy DLL is the module whose base name equals the
   sidecar's DLL name, or `--module`), `ThreadListStream` and `ThreadInfoListStream` for the faulting thread, `MemoryListStream` / `Memory64ListStream` for
   the stack bytes that exist. It prints the faulting address as `module+rva`, then through the GNU ld map as `section: symbol+offset` (nearest preceding
   symbol of the same input section, the object file named), and the same for every stack word that falls inside the DLL's range. A 32-bit mingw DLL has no
   `.pdata`, so stack hits are a scan, not an unwind: label them "stack scan" (candidate, ordered by depth) against "exception" (certain), never print a
   scan hit as a certain frame. Addresses outside the DLL print `module+rva` only (optional `--sites <engine_sites.json>` adds the name of an exe rva that
   a row anchors; off when absent).
6. **The right map or none.** The sidecar's build id must equal the build id in the launch line of `--log` (`d3d9.dll build <id> loaded`), and when a DLL path
   is given its sha256 must equal the sidecar's: a mismatch refuses with both ids (exit 2), unless `--force-map`, which prefixes every output line
   `WRONG MAP?`. With `--build-id` the verb fetches the CI artifact by name with `gh run download -n proxy-map-<id>` (the newest run on `main` or the branch
   that has it; `--run` names one) into `_scratch/maps/<id>/`, and says plainly when it has expired ("kept 90 days; the release attaches its own").
7. **Output.** One block: the build id, the exception (code name, address, thread), the certain frame, up to 16 scan candidates, and the command that
   reproduces it. `--json` prints the same fields. Exit 0 symbolised, 1 a dump that parses but names no frame in the DLL (still prints the exception and the
   module list), 2 refused (bad dump, wrong map, no map). Output for the same inputs is byte-identical.
8. **No game names, no PC.** The verb runs anywhere. CI proof is real: the smoke's stand-in exe takes a deliberate fault in a DLL function with a known
   symbol, under wine writes a minidump with `MiniDumpWriteDump`, and the verb names that function. Host tests also run on hand-built dumps so the Linux and
   Windows `gates` need no wine.

### Guarded verbs
9. **First, the survey (a step, capped at about 10 calls).** Search the first consumer's reports and reviews read-only (`git -C ../napoleon-remastered grep`
   on `origin/main`) for permission asks that recurred; write each with its count and a report path into the report. Build the two named in the row plus any
   other that is (a) a single state change, (b) fully decidable from files on disk, (c) undoable. An ask that needs judgement (a new allowed command pattern
   with reach, a merge right) never becomes a verb.
10. **`job.sh vdisplay-aside <owner> <session> <why>`**: moves `<state>\vdisplay_restore.json` to `_to_delete\vdisplay_restore_<utc>.json.aside` and logs it,
    only when all hold: the file exists; the lock is free or held by `<owner>` (`holds_check` rules; the owner is the session by default, H2) and no game
    process runs; the watcher's own restore has already failed or dropped it (the watcher log says `vdisplay: RESTORE FAILED` or `pending restore dropped`),
    or the file is older than the lock's stale limit; `<why>` is non-empty. It prints the saved mode (the file's content, one line) so the record is in the
    session's output, never deletes, never writes the display mode (only the watcher's pump does), and uses a unique-name move that overwrites nothing (as
    lock expiry does). Otherwise it refuses with the one-line reason and the next step (let the watcher restore it; take the lock). No watcher code changes.
11. **`wsc agent-settings allow "<rule>" [--file .claude/settings.json]`** and `remove` (`warscape/verbs/agent_settings.py`, configured by `[agent_settings]` in
    `wsc.toml`: `safe` patterns, e.g. `git status|diff|log|show`, `python3 core/wsc.py <read-only verb>`, `gh pr checks|view|list`): adds one rule to
    `permissions.allow` only when it matches a `safe` pattern, is not covered by an existing `deny` rule, is not broader than its pattern (`Bash(*)`,
    `Bash(git:*)`, `PowerShell(*)` refuse), and the file stays valid JSON with the same key order and indentation (atomic write: temp file in the same
    folder, then replace; the old file kept as `settings.json.bak` once per run). A refusal names the failed check and says Liam decides. It never edits a
    hook or a `deny` entry and never writes outside `.claude/`. With no `[agent_settings]` the verb says it is not configured and does nothing.
12. **Where each lives.** `crash` and `agent-settings` are core verbs (a consumer deletes a same-named game verb in its pin bump); `vdisplay-aside` lives in
    `harness/job.sh`. The report says whether `agent-settings` needs a line in the consumer's hook (it edits `.claude/`, not a protected folder, so it should
    not), and the pin-bump job adds one only if it does.

### Docs and the decision
13. `docs/PROXY_BUILD.md` gains "Symbolising a crash" (the map, the artifact name, the retention, the command, what a scan hit means, the release rule of
    decision 4). `docs/CONSUMING.md` lists the verbs under the right headings and stays under the 30 KB cap (move text to `PROXY_BUILD.md`, link, do not
    copy; `doc_size` is a gate). A C-row in `docs/DECISIONS.md` (next free number, read `origin/main`) says agents may run the three verbs and why each is safe.

## Scope: files this job touches
`proxy/tools/build.sh`, `warscape/minidump.py` (new), `warscape/verbs/crash.py` (new), `warscape/verbs/agent_settings.py` (new), `warscape/ci_render.py`,
`ci/gates.yml.in`, `.github/workflows/gates.yml` (rendered), `harness/job.sh`, `harness/tests/` (the new verb's cases), `proxy/tests/smoke_host.cpp` (a
deliberate-fault mode, only if the stand-in exe cannot already fault; no change to the DLL's own source), `tests/test_minidump.py`, `tests/test_crash_verb.py`,
`tests/test_agent_settings.py`, `tests/test_ci.py`, `tests/test_moved_tools.py` (a `repro` case with the map flag), the job.sh test file that exists,
`registries/tools.jsonl`, `wsc.toml` (`[agent_settings]` for the core's own use), `docs/PROXY_BUILD.md`, `docs/CONSUMING.md`, `docs/DECISIONS.md`,
`docs/BACKLOG.md`, `VERSION`.
**Not:** `proxy/src/*` (the DLL's source and the in-process dump flags: a bigger dump is Liam's call, open question 2), `harness/watcher.ps1` (restore
logic is W10's and the consumer's J48; no watcher code here, so no watcher kit update), `dev.cpp` or `dllmain.cpp` (W33), any adapter. No game names in
core files (`tests/test_moved_tools.py` `NoGameNames`; say "the first consumer").

## Steps
1. Read "What exists". `git fetch`; read `origin/main` `VERSION` and the open `job/*` branches for overlap.
2. **Survey** (decision 9).
3. **Failing tests first, committed red.** `test_minidump.py`: a hand-built minidump builder (header, directory, exception, module list, thread list, one
   memory range); the reader returns the exception, module and stack words; truncated, wrong-signature and zero-stream dumps give a named error, never a
   traceback. `test_crash_verb.py`: a small GNU ld map fixture (two sections, an object per section, a symbol gap) names `section: symbol+offset` and the
   object; nearest-preceding rule; an address in no input section prints `module+rva`; a sidecar sha256 or build id that disagrees refuses (exit 2) and
   `--force-map` prefixes `WRONG MAP?`; scan hits are labelled and the exception line is not; `--build-id` with a fake `gh` finds, downloads and reports an
   expired artifact; `--json` fields; byte-identical output. `test_agent_settings.py`: allows a configured safe rule; refuses `Bash(*)`, `Bash(git:*)`, a rule
   under a `deny`, an unconfigured repo; keeps key order and indentation; atomic (a failing write leaves the file); `.bak` once; `remove`; never touches `deny`
   or hooks. `job.sh vdisplay-aside` cases (the harness tests' fake state folder): moves with a unique name, prints the saved mode, refuses with a game running,
   with another owner's lock, with no file, with an empty `<why>`, while the watcher's restore is still pending and fresh, and twice in one second without
   overwriting. `test_ci.py`: the artifact block renders, names the id from the build line, pins a sha. A `build.sh` fixture: the link line has the map flag and
   `repro` compares the maps.
4. Build, one commit each: the map flag and sidecar (1-2), the CI artifact (3), the reader and verb (5-8), `vdisplay-aside` (10), `agent-settings` (11), docs
   and decision (13).
5. **CI proof** on `job/W35`: the `proxy` job uploads `proxy-map-<id>`; from this session download it with `gh run download` and run
   `python3 wsc.py crash symbolise` on the dump the smoke's fault made: the output names the faulting function. Quote the run id, the artifact name and size,
   and the output. `repro` byte-identical; the DLL's sha256 with and without the map flag, both printed.
6. `python3 wsc.py gates` (full), CI green, `python3 wsc.py policy --branch job/W35 --base origin/main`.

## Tests and acceptance (what done looks like)
- Step 3's cases red first, then green; every existing Python and C++ host test green; `repro` and the smoke unchanged in meaning.
- **A real fault named in CI** (step 5), not only on hand-built dumps: the artifact, the dump and the verb's output in the report.
- The DLL's bytes unchanged by the map flag (both sha256 values in the report). Every consumer's build id changes with this job (`build.sh` is an input), as
  with W24; the first consumer takes it in a pin bump with a 20-pass run.
- The three verbs refuse every unsafe case above with a one-line reason and the next step; none deletes or overwrites anything.
- Done: the draft pull request open with CI green, the report written, the row at `review`.

## VERSION
A minor bump (a new link flag changes the build id; two new core verbs; a changed render block). Take the next free minor at merge time: `origin/main` says
0.30.0 on 2026-11-04 and W15, W16, W25 and W33 also bump. Re-read `origin/main` `VERSION` and the open `job/*` branches before the last commit; the second to
merge takes the next free number and merges `main` (never rebase). Say which number you took. Tags are Liam's.

## What consumers must do after the tag (napoleon-remastered)
The pin bump takes the new core with its DLL inputs (one 20-pass run with W24, W33 and the rest); delete any game verb named `crash` or `agent-settings`; add
`[agent_settings]` to `wsc.toml` (safe list from the survey) and one hook line if the report says so; the watcher kit does not change. The release builder
attaches `d3d9.map` and its sidecar to each release (decision 4).

## Kill criteria
- The map flag changes one byte of the DLL, or `repro` stops being byte-identical: stop; never weaken the check or drop the flag silently.
- The reader needs a native debug library, a network call at parse time, or more than `struct`-level parsing to name the exception frame: stop and report with
  the stream that blocked it (a stack scan alone is not a result: the exception frame must be named).
- No real fault can be produced and read in CI's `proxy` job (wine writes no usable minidump) after about 12 calls: stop, report what wine wrote, and finish
  the hand-built-dump half; open question 1 goes back to Liam.
- A guarded verb cannot decide its precondition from files on disk (it would need a new PC script or a watcher change): stop; that verb is reported as not built.
- Anything here needs a rule loosened in `CLAUDE.md`, the hook, a `deny` list or the `policy` check: stop; that is Liam's.
- Core CI red after three fix attempts for a cause in this change: stop and report. Version collision as in VERSION; never rebase a pushed branch.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **If wine cannot write a minidump in the smoke?** Recommended: keep the hand-built dumps as the proof and add one real Windows dump symbolised to the first
   consumer's next acceptance, saying so in the report. Alternative: a `windows-latest` job that builds the DLL natively and faults (slower, a second toolchain).
2. **Dump contents.** Recommended: leave `crash.cpp`'s flags: the exception frame is always named, stack scan hits are best effort. A fuller stack costs
   larger dumps and is a DLL change with a 20-pass run; a later row if scans prove too thin.
3. **Retention.** Recommended: 90 days for CI maps plus the release rule of decision 4. Alternative: also commit the sidecar (not the map) per release in the
   consumer's repo, so the id-to-sha256 record outlives the artifact.
4. **Which other recurring asks become verbs?** Recommended: only those meeting decision 9's three tests, listed in the report; the rest stay asks.

## File overlap with other rows (whoever merges second merges `main`, never rebase)
- **W24** (merged): this job follows its `build.sh` link line and the build line it prints. **W16** (null game on its own): `build.sh`, CI's `WSP_BUILD_ID`.
  **W33** (threads off `DllMain`): DLL inputs and `VERSION`. **W25, W15**: `harness/` and `ci_render.py` neighbours; read their branches. **W10** (merged): the
  lock owner is the session; the new `job.sh` verb uses it. **W22**: the render blocks. All rows: `docs/BACKLOG.md`, `docs/CONSUMING.md`, `docs/DECISIONS.md`, `VERSION`.

## Finish
Report in `jobs/W35/report.md` (what was built per decision, the survey, tests red then green and where they ran, the CI run ids, artifact and the real fault's
output, the DLL sha256 with and without the flag, the version taken, deviations, open questions, what the first consumer must do), then
`wsc reg set jobs W35 status=review report=jobs/W35/report.md` (`python3 wsc.py`). Push `job/W35`, open the draft pull request, and stop: an independent
reviewer merges (C18); Liam tags. (A builder running as a subagent that cannot write the report or push returns the report text and the branch state instead;
the orchestrator writes it, sets the row, pushes and opens the pull request.)

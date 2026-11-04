# W35 report: Crash dump symbolisation and guarded verbs for recurring permission asks

W35 builds two things. The proxy DLL now links with a reproducible GNU ld map and a sidecar. CI keeps them as `proxy-map-<build id>` for 90 days. A new verb,
`wsc crash symbolise`, names a minidump's exception frame from that map with no debugger (standard library only). In CI it named a real fault that the smoke
caused inside the DLL under wine: `lua_gettop`. The job also adds two guarded verbs, `wsc agent-settings` and `job.sh vdisplay-aside`. They stand in for the
one-off permission asks sessions kept making: each checks the state it changes and refuses otherwise. With the map flag on, the DLL is byte-identical to the
build without it (repro proves it).

Written by the orchestrating session (same session id as the builder) from the builder subagent's hand-back text, unchanged in substance; the harness refused the
builder's own write of this file.

## What was built
### The map, per build id (decisions 1-4)
- `build.sh` `build_dll` takes a fourth argument, the map path. With it, the link line gains `-Wl,-Map,<map>.raw`, and `warscape/minidump.py` `write_map` then
  writes `d3d9.map` and `d3d9.map.json` beside the DLL (`build/proxy/<adapter>/`, the brief's example path; kits copy `d3d9.dll` by name).
  - The map is normalised so it is reproducible: checkout paths become `core/ adapter/ out/ ui/ root/`, and gcc's `/tmp/ccXXXXXX.o` objects are named after their
    sources in LOAD order. A count mismatch refuses the build.
  - The sidecar is `{dll, build_id, dll_sha256, image_base, size, size_of_image}`, with no timestamp. `d3d9.map.build.txt` holds the build line.
  - No `--cref`: the map is 2,813,917 bytes (246 KB zipped), and the verb reads sections and symbols only.
- `repro` compares the DLL, the map and the sidecar from another path, then links again without the flag and fails unless the DLL is byte-identical (both
  sha256 printed).
- On CI, `build.sh` writes `map_name=proxy-map-$BUILD_ID` and `map_files` to `$GITHUB_OUTPUT`, plus a step-summary line.
- New render block `{{wsc proxy_map step=dll}}` in `ci_render.py`: `actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9` (v7.0.2), 90 days,
  `if-no-files-found: error`, and a summary link.
- `ci/gates.yml.in`: the build step is `id: dll`, then the block; the smoke's fault dump and log go up as `proxy-smoke-dll-fault` (30 days).
- The release rule is in PROXY_BUILD.md; there is no release code.

### The verb (decisions 5-8)
- **Reader.** `warscape/minidump.py` reads these streams with `struct` only: Exception, ModuleList, ThreadList, ThreadInfoList, MemoryList, Memory64List and
  SystemInfo. It tolerates list padding, and a bad dump raises a named `DumpError`.
- **Map reader.** Nearest preceding symbol within the same input section; input-section lines that wrap onto two lines are handled.
- **`warscape/verbs/crash.py`**, `wsc crash symbolise <dump> [--map | --build-id [--run] [--repo]] [--log] [--dll] [--module] [--sites] [--force-map] [--json]`:
  - It prints the exception, the certain `exception frame:`, up to 16 `stack scan #n` candidates (code addresses only; data pointers are counted, not listed),
    the modules when exit is not 0, and `reproduce:`.
  - Exit 2, naming both values, when the sidecar disagrees with any of these: the `--log` launch line or its `self_hash`, the `--dll` sha256, or the dump's
    `size_of_image`. `--force-map` uses the map anyway and prefixes every line `WRONG MAP? `.
  - `--build-id` finds the artifact with `gh api .../actions/artifacts?name=` and downloads it with `gh run download <run> -n ... -D _scratch/maps/<id>/`. When
    every copy has expired it says "kept 90 days; the release attaches its own".
  - Exits: 0 named, 1 no frame in the DLL, 2 refused. Output is byte-identical for the same inputs.
- **Smoke step 9.** `smoke_host.cpp` gains a `dllfault` mode: it calls the export `wsp_sentinel` with a bad `lua_State` (`[dev] lua_bridge=1`, `exe_guard=0`).
  The fault lands in the DLL's `lua_gettop`, and the verb must name it. No DLL source changed.

### Guarded verbs (9-12)
- **`job.sh vdisplay-aside <owner|-> <session> <why>`** acts only when all of these hold: the file exists; the lock is free or held by `<owner>`
  (`holds_check`); the watcher is alive and `watcher.status` lists no game process (from files on disk); the last `vdisplay: ` line of `watcher.log` (at or after
  the file's time) is RESTORE FAILED, its "repeated" line, or "pending restore dropped", or the file is older than `lock_stale_min`; `<why>` is non-empty. It
  moves the file to `_to_delete\vdisplay_restore_<utc>[_n].json.aside` with a checked `mv -n`, appends a record line to `watcher.log`, and prints the saved
  mode. It never deletes, never sets the display mode, and needs no watcher change.
- **`wsc agent-settings allow|remove "<rule>" [...] [--file]`**, configured by `[agent_settings] safe`:
  - A rule is added only if a safe pattern covers it, no `deny` rule overlaps it, and it has no wildcard (except a trailing `:*`) and no shell operator.
    `Bash(*)`, `Bash(git:*)`, `PowerShell(*)`, a bare `Bash` and `Edit(**)` refuse.
  - Key order, indent and line endings are kept, and an internal guard checks that only `permissions.allow` changed.
  - The write is atomic (temporary file, then `os.replace`), and `.bak` is written once per run.
  - It writes only a `.json` directly inside `.claude/`, never through a symlink; `remove` never touches `deny`; an unconfigured repo refuses.
- Both verbs are core verbs (`CORE_VERBS`). Hook line: not needed, because `.claude/` is not a protected folder and the verb runs as `python3 core/wsc.py`.
- The core's own `wsc.toml` has a safe list.

### Docs and decision (13)
PROXY_BUILD.md "Symbolising a crash"; PROXY_HARNESS.md "Guarded verbs"; CONSUMING.md (a 4-line pin-bump section and the core verb names, 30,116 bytes);
DECISIONS.md C29.

## Evidence
### The survey (decision 9)
Searched with `git -C ../napoleon-remastered grep` on origin/main (reports, reviews, briefs, the audit).

| Ask | Count | Where | Result |
|---|---|---|---|
| Move a stale `vdisplay_restore.json` | 2 (+J48 brief) | J10 report:177, J44 report:95 | built |
| `.claude/settings.json` edit | 1 | J20 report:82 (a hook edit) | the allow half built; hooks never |
| Orchestrator writes a subagent's report | 6 | J11, J33, J34, J38, J57, J62 | no (judgement, policy) |
| Unpinned raw download | 1 | J7 report:107 | no (network with reach) |
| Trailer history rewrite | 1 | J44 report:87 | no (a history edit) |

### Tests, red then green
- **Red** at 7fa00ce: `test_minidump` (14), `test_crash_verb` (14), `test_agent_settings` (14), `test_job_sh.VdisplayAside` (5), `test_ci.ProxyMap`,
  `test_moved_tools.LinkerMap`.
- **Green:** local full `wsc gates` on the merged branch, 2026-11-04: 12 ok, 3 warn, 0 failed. CI run 41890834438 (6ee9ff5): changes, gates on ubuntu and
  windows, proxy and harness-windows all green.
- **Learning turned into code:** runs 41888042361 and 41888298756 failed as "a workflow file issue", caused by `": "` inside a plain YAML `run:` value.
  `test_no_plain_yaml_value_holds_a_colon_space` now refuses that in every rendered workflow.
- **Real dumps:** two first-consumer WER full dumps (read only) parse to 119 modules, 60 threads and ~1,740 ranges, exception 0xc000041d. There is no map for
  those builds, so they were not symbolised.

### CI evidence
- Run 41890834438: artifact `proxy-map-nullgame-ci` (245,879 bytes zipped, expires 2027-02-02) and `proxy-smoke-dll-fault` (4,638 bytes).
- From the builder's session: `gh run download 41890834438 -n proxy-smoke-dll-fault`, then
  `python3 wsc.py crash symbolise smoke_dll_fault.dmp --build-id nullgame-ci --run 41890834438 --log smoke_dll_fault.log`, exit 0:

```
exception: 0xc0000005 EXCEPTION_ACCESS_VIOLATION (read at 0x00000018) at 0x78659664, thread 0x170
exception frame: d3d9.dll+0x79664  .text: lua_gettop+0x4 [out/d3d9.dll.lua/lapi.o]
  stack scan #1 esp+0x0: d3d9.dll+0x4d501  .text: wsp_sentinel+0x41 [core/luabridge.cpp.o]
  stack scan #2 esp+0x8: d3d9.dll+0x4d4c0  .text: wsp_sentinel+0x0 [core/luabridge.cpp.o]
  stack scan #3 esp+0x28: d3d9.dll+0x4d4c0  .text: wsp_sentinel+0x0 [core/luabridge.cpp.o]
  stack scan #4 esp+0x4c: d3d9.dll+0x1880  .text: D3DPERF_BeginEvent+0x0 [core/backend.cpp.o]
```

- The DLL loaded relocated at 0x785e0000, so the rva arithmetic was exercised. Run 41888684660 also named the same frame in CI.

### The DLL's sha256 with and without the map flag
9c94a827dad11fdf150196e40b73754dad2ef59791730f21961035fa403a006f with `-Map` and the same without (null game, `WSP_BUILD_ID=nullgame-ci`). The map and sidecar
are identical from another path.

### The id change and version
`build.sh` is a build-id input, so every consumer's id changes (as with W24); the DLL bytes do not. VERSION 0.35.0: main says 0.33.0, and the open branches hold
0.31.0 to 0.34.0; W29 has not merged.

## Deviations from the brief and why
1. **C29, not C28:** W15, W25 and W28 all claimed C28, and W25 merged with it. (W27 also took C29 on its branch; whichever merges second renumbers.)
2. **Files outside the scope list:** `warscape/cli.py` (`CORE_VERBS`) and `warscape/repo.py` (`DEFAULTS['agent_settings']`; otherwise the key is unknown to every
   verb) are both needed. `docs/PROXY_HARNESS.md` takes detail so CONSUMING.md stays under the cap.
3. **The sidecar has `dll` and `size_of_image` added**, plus `d3d9.map.build.txt`.
4. **The fault comes through an export:** `wsp_sentinel` with a bad pointer. The symbol prints as the map has it (`lua_gettop`; the smoke accepts an optional
   underscore).
5. **The scan lists code addresses only.**
6. **`.bak` is replaced on each run that writes.**
7. **A dead watcher refuses `vdisplay-aside`:** without a fresh `watcher.status`, "no game" cannot be decided.
8. **The record goes to `watcher.log`** (best effort; a failure is said on stderr).
9. **The builder ran as a subagent that may not write report files:** the orchestrating session wrote this report, set the row and pushed.

## Open questions
1. Wine wrote a usable dump, so open question 1's fallback was not needed. A real Windows dump symbolised against its map stays the first consumer's next
   acceptance item.
2. Dump flags unchanged. The scan's first hit was the real return address; the `+0x0` hits are `GetProcAddress` function pointers, which is why scan hits are
   candidates.
3. Retention: 90 days plus the release rule (C28, Liam 2026-11-04).
4. Other asks stay asks.
5. The map lists globals only, so a `static` function shows as the nearest preceding global of its object. A later row if it bites (`-ffunction-sections`
   changes the DLL).

## What the first consumer must do (pin bump)
- Take the new core with one 20-pass run (with W24, W33 and the rest).
- Delete any game verb named `crash` or `agent-settings`.
- Give the proxy build step `id: dll`, add `{{wsc proxy_map step=dll}}` after it, then `wsc ci render`.
- Add `[agent_settings] safe` (Liam decides the list; the builder suggested read-only git, `wsc find`, `wsc jobs view`, `gh pr view`, `gh pr checks` and
  `gh run view` patterns, each as its own rule).
- No hook line is needed.
- The release builder attaches `d3d9.map` and `d3d9.map.json`.
- The watcher kit does not change.

## Fix round 1
Fixed by a fresh session (Claude-Session e4f8697d-5612-4e71-b8ef-a35835938710), 2026-11-04, on review round 1 ("merge after fixes"). The code fixes
for 1-6 interleave in one file and its tests, so they are one commit.

- **Merge of main** (`f538a54`): W16 and W33 had merged; W33 took C29, so W35's decision is now **C30** (the row and every `(W35, C29)` reference).
  VERSION stays 0.35.0, the next after main's 0.34.0. `smoke_host.cpp` takes both `open` (W33) and `dllfault` (W35); `build.sh smoke` runs W33's
  thread-order check and steps 9-10, then the DLL fault as step 11 (11 launches, 3 dumps). The smoke runs only in CI (wine); not run here.
- **1. A narrower rule can be a write primitive** (`91649e1`): `covers` accepts only whole-word extensions of a prefix (`git diff` no longer covers
  `git diffx`). The words a rule adds to its closest safe pattern may not hold a `WRITE_FLAGS` flag (`--output`, `--ext-diff`, `--textconv`,
  `--config`, `--exec`, `--upload-pack`, `--git-dir`, `-c`, `-O`, `-o`, `-x` and kin; also `--flag=value` and `-cvalue`). New `[agent_settings]
  exact_only = true` allows only the patterns themselves (default false; a non-bool refuses). A flag inside a safe pattern itself is still Liam's choice.
- **2. Symlinks and junctions** (`91649e1`): the target is judged after `os.path.realpath`: `.claude` a symlink or junction (`Path.is_junction`), the
  file or its `.bak` a link, the file or `.bak` with more than one hard link, or a resolved path outside `<real root>/.claude`, refuses. The `.bak` is now
  written as a temporary file in the folder and `os.replace`d onto its name, so a link that appears there after the check is replaced, never written through.
  In passing: the file is read and the `.bak` written as bytes, so a CRLF file keeps its line ends (`read_text` had turned them into LF, so the
  CRLF branch never ran; a test now proves it).
- **3. `--file` in any `.claude` folder** (`91649e1`): the resolved parent must be the repo's own `<root>/.claude`; an absolute or relative path to
  another `.claude` folder refuses.
- **4. Tests** (`91649e1`): ten new tests in `tests/test_agent_settings.py` (24 in all): whole-word prefixes, nine write/run-flag rules, `exact_only`,
  a glob deny, a `.claude` outside the root, a `.claude` junction (a directory symlink off Windows), a symlinked settings file, a symlink at `.bak`, hard
  links at the file and at `.bak`, CRLF. Run against the round-0 verb, 8 fail; the two symlink tests skip on this Windows PC (no symlink privilege)
  and run on ubuntu CI. The junction and hard-link tests need no privilege and always run on Windows.
- **5. A deny with a `*` inside** (`91649e1`): `glob_overlaps` reads it broadly: it blocks any rule of its tool whose command starts with the deny's
  text before the first `*` (or, for a prefix rule, whose command that text starts with). `Bash(git * --force)` therefore blocks every `git` rule; Liam
  decides those.
- **6. `.bak` once per run** (`91649e1`): the `--file` help, the module docstring and `docs/PROXY_HARNESS.md` say each writing run replaces the `.bak`,
  so two runs keep only the second original.
- **Docs:** `docs/PROXY_HARNESS.md` "Guarded verbs" and the C30 row describe the new rules (`91649e1`). The report's round-0 claims ("never follows a
  symlink", "writes only directly inside `.claude/`") hold now in the form above.
- **Not asked, needed for green gates** (`5b84c27`): main is red on `doc_size` since W16 and W33 merged (CONSUMING.md 31,527 bytes, run 41893656670);
  with W35's section it was 32,086. The three oldest pin-bump sections (0.24.0, 0.26.0, 0.27.0) move unchanged to `docs/CONSUMING_UPGRADES.md` behind a
  pointer, as the earlier CONSUMING_OPTIONS.md move did; CONSUMING.md is 28.6 KB. Merging W35 turns main's doc_size green.
- **Left:** a `watcher.status`-shows-a-process test for `vdisplay-aside` (the review's "later, not required"). One check-then-write race remains: a link
  put at the file or `.bak` after the check is replaced (`os.replace` acts on the name), but `.claude` itself swapped for a junction between the check
  and the write would take the temporary file and the replace with it. That needs a writer racing the verb inside the repo; not guarded further.
- **Machines** (this checkout, Windows, 2026-11-04): `wsc gates` 13 ok, 2 warn (`ci_render`'s old W23 note; `tests` 809 passed, 5 skipped: no POSIX sh,
  no capstone), 0 failed. `wsc policy --branch job/W35 --base origin/main` refuses only on the missing merge verdict and the `done` row.

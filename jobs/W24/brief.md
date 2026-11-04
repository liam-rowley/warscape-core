# W24: Build id names one DLL: toolchain, committed sources, DLL self-hash

Model: Opus, reason: DLL (the row's model). The job changes the DLL's start-up path (a file hash inside `DllMain`, under the loader lock) and the inputs
of every consumer's build id; a mistake ships in every launch and costs a consumer a 20-pass acceptance sitting to find. Budget about 140 tool calls (CI
round trips included: the pinned install, the step summary and the smoke check can only be shown by pushes; finding the package versions has its own cap
under Kill criteria). At the cap, stop, commit, and report what is left.

## Goal
The audit of 2026-11-03 (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`, read-only) found that the build id, which rule 79 of the first consumer
trusts to name one DLL, does not (C1), plus a refusal no doc explains (C2, core half), and W21 left a retry outside the fetchers (B62):
- **Toolchain unpinned.** `ci/gates.yml.in:56` (rendered `.github/workflows/gates.yml:122` at 0.24.0) runs `sudo apt-get install -y -q g++-mingw-w64-i686`,
  and `proxy/tools/build.sh:15,44` installs the same unpinned package inside the digest-pinned container. A later archive version gives other bytes under
  the same id; nothing records which compiler built a DLL.
- **Untracked sources.** `build.sh:129` links every `$S/*.cpp`; the id hashes the committed tree (`build_id.py:33-36` `INPUTS`) and `-dirty` comes from
  `git diff --quiet <commit> -- <path>` (`build_id.py:105-108`), which ignores untracked files: an untracked `.cpp` links in and the id stays clean.
- **No byte evidence.** Acceptance takes the id from the DLL's launch line (`harness/ctl.py:370`, the regex `d3d9\.dll build (\S+) loaded`, called through
  `harness/acceptance.py:299-302` `identity()`), never the DLL's sha256.
- **C2.** `fetch_ui.py:117-119` stops with `has no "stb_image_write" pin`; `docs/CONSUMING.md` never names that pin (required since 0.10.0, W2).
- **B62.** Fold `netfetch.retry` into `fetch_lua.py` and `fetch_ui.py` and drop the CI-only `prefetch` step: W21 kept them out only because they are DLL
  inputs, and this job changes DLL inputs anyway. The PC route (`build.sh --docker`) still fetches with no retry.
- **Audit rule row** "runner image and apt are outside the key" (CI pass markers): the apt half closes here; the image half is decided below (decision 6).

**Every consumer's build id changes with this job, and so do the DLL's bytes** (new code at init). The first consumer takes it in its J78 (the pin bump
to audit train 1) with W33 and the rest, in one 20-pass acceptance run. W33 (threads off `DllMain`) and W35 (linker map per build id) follow this job on
the DLL inputs; W9 records the DLL sha256 per acceptance pass from the line decision 10 defines.

## What exists (read before building)
- `CLAUDE.md`, `docs/DECISIONS.md` (C14, C16, C21), `docs/CONSUMING.md` ("The job pipeline", "The proxy, the harness and the save tools"),
  `docs/BACKLOG.md` B16 and B62, `jobs/W21/brief.md` and `report.md` (netfetch, the fetch cache, why the fetchers were not edited, the throwaway
  superproject used for `build_id.py --inputs`), `jobs/W16/brief.md` (the overlapping B16 work).
- `proxy/tools/build_id.py`: `INPUTS` (7 roles), `locate` (each role read at the revision, through the gitlink for a submodule), `build_id` (`-dirty`),
  `--inputs`. **Rule 79 recomputes the id from committed content with no compiler**: napoleon `tools/jobs_hooks.py:250-259` `dll_build_id` calls
  `build_id(root, 'HEAD', dirty=False)` inside its `policy` check. Any id design must keep that working.
- `proxy/tools/build.sh`: `IMAGE`/`APT` (14-15), `WSP_BUILD_ID` handoff into `--docker` (22-26, 43), `ui_objs` and its stamp (64: `$CXXU --version | head -1`,
  which names the GCC major and thread model, not the package revision or the mingw-w64 headers and import libraries), `build_dll` (115-131), the
  fetchers with stdout discarded (134-135), the build line `build.sh: ... build <id> sha256 <hex>` (141), imports and exports checks, `repro`, `smoke`.
- `proxy/src/dllmain.cpp`: `Init` runs inside `DllMain` (115-118); the launch line (86-87) is the first line of `proxy.log`; `dll <path>` (88).
  `proxy/src/guard_driver.cpp:21-36` `HashFile`: the exe hashed from `DllMain` in 1 MiB `ReadFile`s with `sha1.h` (pure, "loading bcrypt.dll or another
  crypto DLL under the loader lock is not safe"), logged `(hashed in N ms)` (65-71). On the first consumer's PC that hash of a 17.9 MB exe takes 31 to
  47 ms (napoleon `harness/runs/20261101_j8idle2/proxy.log`); its DLL is about 1 MB (`build/proxy/napoleon/d3d9.dll`, 2026-11-02).
- `proxy/tests/test_sha1.cpp` (the vector test shape), `proxy/tests/test_guard.cpp:97-104` (the "names no game" file list), `proxy/tests/smoke_host.cpp`.
- `proxy/tools/netfetch.py` (`retry`, `transient`, `prefetch`, `clean_checkouts`, `_git_ok`, `_force_remove`, `ci_cache`), `fetch_lua.py:53-86`
  (`urlopen` at 62), `fetch_ui.py` (`fetch_git` 42-55, `download` 58-68, the key loop 117-119), `fetch_dxvk.py` (already retried), `tests/test_netfetch.py`.
- `warscape/ci_render.py:99-109` `block_fetch_cache` (three steps, the last `netfetch.py prefetch`), `tests/test_ci.py:324-337`, `ci/gates.yml.in` (`proxy` job,
  `WSP_BUILD_ID: nullgame-ci` because the null game is not a git root, B16), `wsc.toml` `[ci] inputs` (the `proxy` set includes `^proxy/`, so a change
  under `proxy/tools/` reruns the job).
- `tests/test_moved_tools.py:84-123` `BuildId` (throwaway flat and submodule layouts that copy the tool files the roles name).
- `proxy/tools/pc_deploy.py:282-286`: a kit's manifest records each staged file's sha256 (the DLL's included).

## Decisions already made (follow them; a deviation goes in the report with its reason)
### Toolchain (C1)
1. **Pin the toolchain in a committed file that is a build-id input; never measure the installed compiler into the id.** A new tool
   `proxy/tools/toolchain.py` (header, `reg add tools`, `not-a-verb`: a build helper like `build_id.py`) holds `PIN = {'image': <the ubuntu:24.04 digest,
   moved from build.sh:14>, 'apt': {package: exact version}}` and is a new role, `('toolchain', ('proxy/tools/toolchain.py',))`, appended to `INPUTS`.
   The `apt` set is every package `dpkg-query -W '*mingw-w64*'` lists after `apt-get install --no-install-recommends g++-mingw-w64-i686-win32` on the
   pinned image (expected: `g++-` and `gcc-mingw-w64-i686-win32`, a `-runtime` package if noble has one, `gcc-mingw-w64-base`, `binutils-mingw-w64-i686`,
   `mingw-w64-i686-dev`, `mingw-w64-common`; take the real list). Prefer versions from the `noble` release pocket, which never changes; note any that
   only `noble-updates` carries (`apt-cache madison`), since a later update removes an older update from the archive.
   Why not hash `$CXX --version` and `ld --version` into the id (the row's first option): rule 79's policy check would then need the compiler to recompute
   the id, and Ubuntu's version lines do not name the package revision or `mingw-w64-i686-dev` (the headers, CRT and import libraries linked into the
   DLL). Quote the runner's actual first lines in the report. The lines are still checked and printed (decision 3), only not hashed.
2. **Both places install the pins.** `toolchain.py apt` prints `pkg=version ...` on one line, sorted; `toolchain.py image` prints the image reference.
   CI: `sudo apt-get install -y -q --no-install-recommends $(python3 proxy/tools/toolchain.py apt)` (add `--allow-downgrades` only if the runner has a
   newer one preinstalled, and say so). `build.sh --docker`: `IMAGE` and the toolchain part of `APT` come from `toolchain.py` on the host; `g++`, `python3`,
   `ca-certificates`, `git` and the smoke's `wine` stay unpinned (the host tests and the smoke do not make the DLL).
3. **Checked at build time, refused off the pin.** Before the first mingw compile of `dll`, `all` and `repro`, `build.sh` runs `toolchain.py check "$CXX"`:
   every pinned package installed at its version (`dpkg-query`), and the resolved `$CXX` binary owned by a pinned package (`dpkg -S` on `readlink -f`), so a
   compiler earlier on `PATH` cannot stand in. OK: one line `toolchain: pinned: <n> packages at their pins; <cxx first line>; <ld first line>`. Otherwise one
   line per difference (installed or `not installed` against the pin; `no dpkg-query: the pin cannot be checked`), then the fix: install the pins, or
   build with `--docker`. `build.sh` then exits 2, unless `WSP_TOOLCHAIN=any`, which builds and appends `-dirty` to the id once (a DLL from another
   toolchain is not the DLL the committed id names). `build.sh id` stays a pure id (no compiler, no check), so napoleon's `test_build_sh_and_rule_79_agree`
   keeps its meaning. The check's runner is injectable for host tests.
4. **Cached UI objects follow the toolchain.** The `mingw32` stamp of `ui_objs` adds the installed versions of the pinned packages (what `check` read),
   so a toolchain change rebuilds `build/ui/obj/mingw32` on a consumer's PC, where `build/` persists between `--docker` builds. The `host` tag is unchanged.
5. **A consumer's PC build** (`build.sh --docker`, the first consumer's D31) needs nothing new: the host computes the id (the toolchain role is a committed
   file), the container installs the pinned versions and runs the same check, so the PC's DLL is CI's DLL by construction rather than by one comparison.
   If the archive drops a pinned version, `apt-get` fails in CI and on the PC alike, loudly; the fix is a core job that bumps the pin (a new id, which
   is the truth: a new toolchain is a new DLL).
6. **The runner image stays outside the pass-marker key.** With the toolchain pinned and checked, the image cannot change the DLL's bytes; it can change
   the host tests' `g++` and the smoke's wine, which the next `proxy/` change exercises, and `[ci] salt` stays the manual lever. Say so in
   `ci/gates.yml.in`'s `proxy` comment; no new key.

### Committed sources (C1)
7. **Compile the tracked list.** `build_id.py --sources` prints the top-level `*.cpp` names of the core sources folder (`layout.py proxy-src`) from
   `git -C <folder> ls-files` (the index of the repository that holds the folder, a submodule's own; byte-sorted, the order `LC_ALL=C ls` gives today, so
   the link order is unchanged). Folder-relative calls work in the flat, submodule and nested null-game layouts alike, so this does not wait for B16.
   `build_dll` compiles `$S/<name>` for each listed name (minus `ui_lua.cpp`, as today), the same list for `repro`'s copy. `--docker` passes the
   host's list in as `WSP_SOURCES` (as `WSP_BUILD_ID`: the container cannot read a worktree's `.git`). Outside git (`nogit`) it falls back to the glob and
   says so. A staged new file is listed and compiled, and the id is already `-dirty` (`git diff` sees it): host-test that.
8. **Refuse an untracked source.** `--sources` exits 2 naming each untracked or ignored file with a source suffix (`.c .cpp .h .hpp .inc .def`) under the
   core sources folder or the adapter folder (`git ls-files --others`, with and without `--exclude-standard`), with the fix (`git add` it, or move it out).
   `build.sh` calls it right after the id for `dll`, `all` and `repro`, before `gen_tables.py --check` and the fetchers, so the refusal is quick and needs
   no compiler. Why refuse rather than `-dirty`: an untracked source is a forgotten `git add` (the DLL silently lacks it) or a stray copy, and an untracked
   header can shadow a tracked one through `-I"$S"`; a `-dirty` DLL would be kitted and tested for passes rule 79 never counts.

### The DLL's own sha256 (C1)
9. **Hash the DLL file in `Init`, synchronously, the guard's way.** A pure `proxy/src/sha256.h` (FIPS 180-4, the shape of `sha1.h`). Right after the launch
   line, `Init` hashes the file at the path it already has from `GetModuleFileNameW(self)`, with the guard's read loop (factor `HashFile`'s loop into one
   function both call, e.g. a template over the hasher; the guard keeps its PE parse of the first read). `CreateFileW`, `ReadFile`, `CloseHandle`,
   `GetTickCount` only: no `LoadLibrary`, no bcrypt or CryptoAPI (a provider DLL loads under the loader lock), **no thread** (W33 moves the existing ones off
   `DllMain`; do not add one), no wait, no new import (`build.sh`'s import check proves it). The file, not the mapped image: the image is relocated and
   section-aligned, so only the file's hash equals `sha256sum d3d9.dll`, the kit manifest and the build line. Start-up cost: a 1 to 4 MB SHA-256 against the
   18 MB SHA-1 the guard already does there, so a fraction of 31 to 47 ms; the line carries the measurement. Every launch logs it, second processes and
   `proxy.enabled=0` included (both log the launch line). Add it to the start-up order comment at the top of `dllmain.cpp`.
10. **The line, exactly (W9's contract).** The second line of every `proxy.log` (and of a second process's `proxy.p<pid>.log`), at INFO:
    `self_hash: sha256 <64 lowercase hex> bytes <decimal size> build <WSP_BUILD_ID> (hashed in <decimal> ms)`,
    from `LOGI("self_hash: sha256 %s bytes %llu build %s (hashed in %lu ms)", ...)`. On failure, at WARN: `self_hash: unavailable: <reason>` (the open or
    read error and its code). Parsers use `\bself_hash: sha256 ([0-9a-f]{64}) bytes ([0-9]+) build (\S+) \(hashed in ([0-9]+) ms\)`. A log with neither line
    comes from a DLL older than this job. The launch line does not change (`ctl.py` reads it).
11. **The parser lives beside the existing one.** `harness/ctl.py` gains `SELF_HASH_RE` (the regex above) and `build_info()` returns `dll_sha256` (the hex,
    or `None`) from the same `proxy.log`, with a host test in `tests/test_ctl.py` on a sample log. Recording it in each pass file, and comparing it with the
    kit manifest's `d3d9.dll` sha256 and the line's `build` with the launch line's, is W9's (B26 and H3); this job writes no pass file.

### CI step summary
12. **`build.sh` writes it** when `$GITHUB_STEP_SUMMARY` is set, so every consumer's CI gets it with no template change and a PC build writes nothing:
    after `dll`: a heading `### proxy DLL: <adapter>`, then bullets: the build id; `d3d9.dll` sha256 and bytes; the toolchain line of decision 3. `repro`
    adds `repro: identical from another path`; `smoke` adds `smoke: self_hash in proxy.log matches d3d9.dll (<ms> ms under wine)`. In the core, the id
    reads `nullgame-ci` until W16 drops `WSP_BUILD_ID` from CI (B16); leave that variable alone here.
13. **`build.sh smoke` proves the line.** Launch 1 also checks that the log's `self_hash` sha256 and bytes equal `sha256sum` and the size of the `d3d9.dll`
    it copied, and that its `build` equals the launch line's.

### B62
14. **The retry moves into the fetchers.** `fetch_lua.fetch`'s download and `fetch_ui`'s `download()` and `git fetch` run inside `netfetch.retry`; the sha256
    checks and patch checks stay outside the retried call and keep raising `SystemExit` (never retried). `fetch_ui.fetch_git` trusts a checkout only when HEAD
    is the pin and the working tree equals HEAD (W21's `_git_ok`); anything else is removed (`_force_remove` for git's read-only objects on Windows) and
    fetched again, which W21's `clean_checkouts` did from outside. `netfetch` is imported by the fetchers but is not a DLL input (it changes whether a
    download succeeds, never a byte; `layout.py` is the precedent). Retry lines go to **stderr**: `build.sh` discards the fetchers' stdout (134-135).
15. **The `prefetch` step goes.** `block_fetch_cache` renders two steps (the key and `actions/cache`, still `continue-on-error`), its docstring and
    `CONSUMING.md` say the fetchers retry themselves; `netfetch.py` loses `prefetch` and `clean_checkouts` (no consumer calls them: the first consumer pins
    0.10.0, before netfetch) and keeps `retry`, `transient`, `ci-cache`; its header and row are updated. `python3 wsc.py ci render`; commit both files.

### C2
16. **Name the pin.** `fetch_ui.py`'s missing-key refusal names the key, the five required keys, what `stb_image_write` is for (the in-game host's PNG
    dump, required since 0.10.0) and the reference entry to copy: the null game's `proxy/tests/null_game/viewer/pins.json`, by its path from the game root,
    computed from the script's own place (no game name). `docs/CONSUMING.md` gains a short "The UI pin file" paragraph: the five keys, the null game's file
    as the reference, the file is a DLL input (`ui_pins` role).

### Docs and the decision
17. **`docs/PROXY_BUILD.md`** (new contract doc, like `PROXY_UI.md`) owns the build contract: the inputs and roles, the toolchain pin and check
    (`WSP_TOOLCHAIN=any`), tracked sources only, the `self_hash` line of decision 10 with its regex, the step summary. `CONSUMING.md` links to it from "The
    proxy, the harness and the save tools" and gains the consumer steps of 0.N.0 (below) and the UI pin paragraph; stay under 30 KB (`doc_size`).
    `docs/DECISIONS.md`: one proposed row at the next free `C<n>`: the toolchain pinned by exact package versions in a build-id input and checked at build
    time (refused off the pin; `WSP_TOOLCHAIN=any` marks `-dirty`), never measured into the id, so rule 79 recomputes it without a compiler; the DLL compiles
    tracked sources only and logs its own file sha256 at init. `docs/BACKLOG.md`: remove B62.

## Scope: files this job touches
`proxy/tools/toolchain.py` (new), `proxy/tools/build_id.py` (`INPUTS`, `--sources`), `proxy/tools/build.sh`, `proxy/tools/fetch_lua.py`, `proxy/tools/fetch_ui.py`,
`proxy/tools/netfetch.py`, `proxy/src/sha256.h` (new), `proxy/src/dllmain.cpp`, `proxy/src/guard_driver.cpp` (the shared read loop only),
`proxy/tests/test_sha256.cpp` (new), `proxy/tests/test_guard.cpp` (the file list, the lint), `harness/ctl.py` (`SELF_HASH_RE`, `build_info`),
`warscape/ci_render.py` (`block_fetch_cache`), `ci/gates.yml.in`, `.github/workflows/gates.yml` (rendered), `tests/test_moved_tools.py`, `tests/test_netfetch.py`,
`tests/test_ci.py`, `tests/test_ctl.py`, `registries/tools.jsonl` (rows whose header changed, the new tool), `docs/PROXY_BUILD.md` (new), `docs/CONSUMING.md`,
`docs/DECISIONS.md`, `docs/BACKLOG.md`, `VERSION`. **Not:** `proxy/src/dev.cpp` or any thread start (W33), `-Wl,-Map` (W35), `harness/acceptance.py` pass
files (W9), `WSP_BUILD_ID` in CI (W16), any adapter. No game names in core files (`tests/test_moved_tools.py` `NoGameNames`; say "the first consumer").

## Steps
1. Read "What exists". Check what this session can run: `g++` and `i686-w64-mingw32-g++-win32` for `build.sh all`, `docker info` for `--docker`. If neither,
   the C++ proof runs in CI's `proxy` job: push `job/W24` early and read its log.
2. **Find the pin** (capped, Kill criteria). On the runner: a temporary step in the `proxy` job prints, after installing `g++-mingw-w64-i686-win32` with
   `--no-install-recommends`, `dpkg-query -W -f '${Package}=${Version}\n' '*mingw-w64*'`, `apt-cache madison` for each, and the first lines of
   `i686-w64-mingw32-g++-win32 --version` and `i686-w64-mingw32-ld --version`; the same inside the pinned image (`docker run` works on GitHub's runners,
   so one step covers both). The two lists must be identical. Write `toolchain.py` from them; remove the probe step.
3. **Failing tests first, committed red.** Python: the role list ends with `toolchain` and editing `toolchain.py` changes the id (flat and submodule
   fixtures copy it); `--sources` lists tracked names only, refuses an untracked `.cpp` and an ignored `.h` naming each, lists a staged new file (and the
   id is `-dirty`); `build.sh dll` in a fixture exits 2 on an untracked `.cpp` before any compile (Git Bash via `bash_or_skip`; `harness-windows` runs
   `test_moved_tools` with `WSC_REQUIRE_BASH`); `toolchain.py` `apt` output, `check` with a fake runner (all match; one version off; one missing; `$CXX`
   owned by no pinned package; no `dpkg-query`); the fetchers retry a flaky download and a flaky `git fetch` (W21's `Flaky`, a fake sleep, lines on
   stderr), never a sha mismatch, and remove a half-restored or half-fetched checkout themselves; the refusal text of decision 16; `fetch_cache` renders
   two steps; `SELF_HASH_RE` and `build_info()['dll_sha256']` on a sample log, `None` on an old one. C++: `test_sha256.cpp` with the FIPS 180-4 messages
   (empty, `abc`, the 448-bit two-block message, one million `a` fed in 1000-byte updates) and every split point of a 130-byte message, as
   `test_sha1.cpp`; a lint that `dllmain.cpp` logs the exact format of decision 10 before the config lines, and that the self-hash path names no
   `LoadLibrary`, `CreateThread`, `_beginthread`, `WaitFor`, `BCrypt` or `Crypt`; `sha256.h` in the "names no game" list.
4. Build, one commit each: toolchain (decisions 1-6), sources (7-8), self-hash (9-11, 13), summary (12), B62 (14-15), C2 (16).
5. **CI proof** on `job/W24`: the `proxy` job's install log shows the `pkg=version` list; `build.sh all` prints the `toolchain: pinned` line; the step
   summary shows the block of decision 12 with the repro and smoke lines; the smoke passes its `self_hash` check. Quote the run id, the summary and the ms.
6. **The id change, shown.** `build_id.py --root . --inputs` in a throwaway superproject (the null game at its root, the core as `core` at `main` and at the
   branch, as W21's report did): every changed role and the new `toolchain` line, before and after. If Docker works here, `build.sh --docker all` too.
7. Docs, decision row, backlog, tools rows, `VERSION`; `python3 wsc.py gates` (full), CI green, `python3 wsc.py policy --branch job/W24 --base origin/main`.

## Tests and acceptance (what done looks like)
- The step 3 cases red first, then green; every existing Python and C++ host test green (`test_sha1`, the guard's lints and the 16 proxy suites as before).
- CI on the branch: `gates` (Linux, Windows), `proxy` (`build.sh all` with the pinned toolchain, `repro` byte-identical, `smoke` with the `self_hash`
  check) and `harness-windows` green, with the run ids and the summary text in the report.
- `build.sh` imports and exports checks unchanged (no new DLL import); `self_hash` under 100 ms in CI's smoke, the DLL's size and the ms in the report.
- The `--inputs` before and after (step 6), and the DLL size before and after, in the report.
- Done: the draft pull request open with CI green, the report written, the row at `review`.

## VERSION
A minor bump (a new build-id role, a new tool, a new log line, a removed `netfetch` mode, a changed render block; every consumer's id changes). Take the next
free minor at merge time: `origin/main` says 0.25.0 on 2026-11-04 (W30 merged), and W10, W20 and W22 also bump. Re-read `origin/main` `VERSION` and the open
`job/*` branches before the last commit; the second to merge takes the next free number and merges `main` (never rebase). Say which number you took. Tags are Liam's.

## What consumers must do after the tag (napoleon-remastered, J78)
- **Rule 79: the build id changes** (roles `core`, `build_sh`, `build_id`, `fetch_lua`, `fetch_ui` changed; `toolchain` is new) **and so do the DLL's bytes**:
  20 consecutive acceptance passes on the new id. J78 takes this tag with W33 and the rest of audit train 1 in one 20-pass run.
- `ci/gates.yml.in` `proxy` job (its line 82 today): `sudo apt-get install -y -q --no-install-recommends $(python3 core/proxy/tools/toolchain.py apt)`, then
  `python3 core/wsc.py ci render`; otherwise `build.sh` refuses as soon as the archive's candidate differs from the pin. If it adopts `{{wsc fetch_cache}}`
  (0.22.0), the block now has two steps.
- `tests/test_build_id.py`: its fixtures copy `proxy/tools/toolchain.py` beside `build.sh`, `build_id.py` and `layout.py` (else `locate` refuses: "toolchain
  is not tracked").
- On the PC nothing changes: `build.sh --docker` installs the pins in the container; `build/ui/obj/mingw32` rebuilds once (decision 4). A local native
  build off the pin needs `WSP_TOOLCHAIN=any` and gives a `-dirty` DLL. An untracked source under `core/proxy/src` or `proxy/<game>/` now refuses the build.
- `viewer/pins.json` already has `stb_image_write` (napoleon `main` 6fb1dda, 2026-11-04): nothing to do. No adapter, config key or ini change.
- With W9 in the same bump: each pass records `dll_sha256` from `build_info()`.

## Kill criteria
- The runner and the pinned image cannot install one identical pinned set (a version missing from either, or different candidates) after about 15 calls:
  stop, put both `apt-cache madison` outputs in the report, and do not fall back to hashing version lines (open question 1 goes back to Liam).
- Any design step needs `build_id.py` to run a compiler or read installed packages: stop; rule 79 must recompute the id from committed content.
- The self-hash needs more than `CreateFileW`, `ReadFile`, `CloseHandle` and `GetTickCount` under the loader lock (a `LoadLibrary`, a provider DLL, a thread,
  a wait, a new import), or takes over 100 ms in CI's smoke: stop and report; never move it onto a thread or later in start-up without Liam.
- `repro` is not byte-identical, or the smoke's `self_hash` differs from the file's sha256: stop and fix before anything else; never weaken either check.
- A fetcher change makes a sha256 mismatch or a failed patch retryable, or hides an error: stop.
- Core CI red after three fix attempts for a cause in this change: stop and report. Version collision as in VERSION; never rebase a pushed branch.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **How to pin the toolchain?** Recommended: exact package versions in `toolchain.py` (decision 1): explicit, checkable with `dpkg-query`, and a bump is
   a one-file diff. Alternative: a dated archive snapshot (`apt-get update --snapshot <date>` against `snapshot.ubuntu.com`, apt 2.7 on noble), which would pin
   wine and the host `g++` too, but adds a service on the build path and needs sources the runner's mirror setup may not offer. Rejected: hashing
   `--version` lines into the id (rule 79 could not recompute it; the lines miss the package revision and the mingw-w64 libraries).
2. **Off the pin: refuse or mark `-dirty` by default?** Recommended: refuse, with `WSP_TOOLCHAIN=any` for a `-dirty` local DLL (decision 3): fail-closed,
   and CI and `--docker` never need the variable. Marking by default lets an agent build anywhere, but a `-dirty` DLL is easy to kit by mistake.
3. **Untracked source: refuse or `-dirty`?** Recommended: refuse (decision 8, the row's choice); `git add` gives `-dirty` when a test of an uncommitted file is wanted.

## File overlap with other rows (whoever merges second merges `main`, never rebase)
- **W16** (the null game on its own; queued): `build.sh` (tests loop, `--docker` mount), `build_id.py` (nested layout), `fetch_ui.py` (pin-file schema and
  `--check`, which replaces the key loop of decision 16: the replacement must keep naming the missing key, the null game's reference entry and the
  `CONSUMING.md` paragraph), and CI's `WSP_BUILD_ID`. `--sources` (decision 7) uses folder-relative git calls, independent of W16's lookup.
- **W22** (main health; this row depends on it): `ci_render.py` and the template; it pins the `fetch_cache` text in a test, which decision 15 changes on
  purpose: update that pin with the reason.
- **W33** (`dev.cpp`, `dllmain.cpp`): keep the `self_hash` line where decision 10 puts it; W33 moves threads, never this hash. **W35**: the linker map is
  W35's, keyed by the build id and the sha256 this job prints. **W9**: records `dll_sha256` per pass from decision 11. **W20**, **W18**: `proxy/src` files
  other than `dllmain.cpp` and `guard_driver.cpp`. All rows: `docs/BACKLOG.md`, `docs/CONSUMING.md`, `docs/DECISIONS.md`, `VERSION`.

## Finish
Report in `jobs/W24/report.md` (what was built per decision, the pinned set and where each version comes from, the version lines, tests red then green
and where they ran, the CI run ids and the summary text, the `self_hash` ms and the DLL size, the `--inputs` before and after, the version taken,
deviations, open questions, what napoleon must do), then `wsc reg set jobs W24 status=review report=jobs/W24/report.md` (`python3 wsc.py`). Push `job/W24`,
open the draft pull request, and stop: an independent reviewer merges (C18); Liam tags. (A builder running as a subagent that cannot write the report or
push returns the report text and the branch state instead; the orchestrator writes it, sets the row, pushes and opens the pull request.)

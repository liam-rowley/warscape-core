# W24 report: Build id names one DLL: toolchain, committed sources, DLL self-hash

The orchestrator wrote this file from the builder subagent's hand-back, because the harness refuses a subagent's write of a report file;
the text is the builder's own apart from this note.

W24 closes audit 2026-11-03 C1 and the core half of C2, and builds B62. Of the audit's rule row "runner image and apt are outside the key",
it closes the apt half; the image half stays outside the key (decision 6). It also closes B69, which is the same finding.

- VERSION is 0.27.0 and the decision row is C25 (proposed). W23 merged C24 and 0.26.0 to `main` mid-job, and `main` was merged in with no
  rebase.
- The PC had no g++ or MinGW, so the C++ ran in CI's `proxy` job.
- Once Docker Desktop was back, the `--docker` route was also run locally, which found a bug on the PC route (Deviation 9).

## What was built
### Toolchain (decisions 1-6)
- `proxy/tools/toolchain.py` (new tool, row `proxy.tools.toolchain`) holds `PIN = {'image': ..., 'apt': {...}}`; the image digest moved there
  from `build.sh`.
- Its modes:
  - `apt` prints the sorted `pkg=version` words;
  - `image` prints the image reference;
  - `installed` prints the installed versions of the pinned packages;
  - `check <cxx>` checks every pinned package with `dpkg-query`, resolves `$CXX` with `readlink -f`, and requires a pinned package to own it
    (`dpkg -S`).
- `check` passes with one line, `toolchain: pinned: 7 packages at their pins; <g++ line>; <ld line>`. Otherwise it prints one line per
  difference and the fix, and exits 2. The runner is injectable for host tests.
- `build_id.py` `INPUTS` gains the role `('toolchain', ('proxy/tools/toolchain.py',))`. Nothing installed is measured into the id.
- CI installs the pin: `sudo apt-get install -y -q --no-install-recommends $(python3 proxy/tools/toolchain.py apt)`, then prints the
  `dpkg-query` output.
- `build.sh --docker` takes `IMAGE` and the toolchain part of `APT` from `toolchain.py`.
- `build.sh` runs `toolchain_check "$CXX"` before the first mingw compile of `dll`, `all` and `repro`.
  - Off the pin it exits 2.
  - `WSP_TOOLCHAIN=any` builds anyway and appends `-dirty` once.
  - `build.sh id` is unchanged.
- The `mingw32` stamp of `ui_objs` adds `toolchain.py installed`; the `host` stamp is byte-identical to before.

The pinned set was taken from probe run 41802947502. The GitHub ubuntu-24.04 runner and `ubuntu@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852`
gave the same seven packages, all one `noble/universe` line each:

| Package | Version |
|---|---|
| `binutils-mingw-w64-i686` | `2.41.90.20240122-1ubuntu1+11.4` |
| `g++-mingw-w64-i686-win32` | `13.2.0-6ubuntu1+26.1` |
| `gcc-mingw-w64-base` | `13.2.0-6ubuntu1+26.1` |
| `gcc-mingw-w64-i686-win32` | `13.2.0-6ubuntu1+26.1` |
| `gcc-mingw-w64-i686-win32-runtime` | `13.2.0-6ubuntu1+26.1` |
| `mingw-w64-common` | `11.0.1-3build1` |
| `mingw-w64-i686-dev` | `11.0.1-3build1` |

The version lines are printed but never hashed: `i686-w64-mingw32-g++-win32 (GCC) 13-win32` and `GNU ld (GNU Binutils) 2.41.90.20240122`
name neither the package revision nor `mingw-w64-i686-dev`.

### Committed sources (decisions 7-8)
- `build_id.py --sources` prints the tracked top-level `*.cpp` names of the core sources folder, byte-sorted from `git ls-files -z`, so the
  link order is unchanged.
- It exits 2 and names every untracked or ignored `.c .cpp .h .hpp .inc .def` under the core sources or the adapter folder (found with
  `ls-files --others`, with and without `--exclude-standard`). Outside git it falls back to the glob and says so.
- `build.sh` calls it right after the id, for `dll`, `all` and `repro`, before `gen_tables.py` and the fetchers. `build_dll` compiles only
  the listed names (minus `ui_lua.cpp`), and `--docker` passes the list in as `WSP_SOURCES`.
- On this repo the list equals the old `LC_ALL=C ls proxy/src/*.cpp`: 19 names.

### The DLL's own sha256 (decisions 9-11, 13)
- `proxy/src/sha256.h` (new) is a pure FIPS 180-4 SHA-256 in `sha1.h`'s shape; its constants were checked against the roots of the first
  primes.
- `guard_driver.cpp`: `HashFile`'s loop becomes `ReadChunks(path, what, eat, ctx, bytes, err)`, using `CreateFileW`, 1 MiB `ReadFile`s and
  `CloseHandle`. The guard's error texts are unchanged.
- `dllmain.cpp`: `LogSelfHash(dll)` runs right after the launch line, so it writes the second line of every log:
  `self_hash: sha256 %s bytes %llu build %s (hashed in %lu ms)`, or `self_hash: unavailable: %s`.
  - It runs before the second-process and `proxy.enabled=0` branches.
  - It loads no library, starts no thread and waits for nothing; the imports check is unchanged.
- `harness/ctl.py` gains `LAUNCH_RE` and `SELF_HASH_RE`, and `build_info()` returns `dll_sha256`: the hex, or `None`.
- `build.sh smoke` launch 1 requires log line 2 to be a `self_hash` line whose sha256 and bytes equal `sha256sum` and the size of the copied
  `d3d9.dll`, and whose `build` equals the launch line's.

### CI step summary (decision 12)
When `$GITHUB_STEP_SUMMARY` is set, `build.sh` writes `### proxy DLL: <adapter>`, the build id, `d3d9.dll`'s sha256 and bytes, and the
toolchain line; `repro` and `smoke` add their lines. Each line is also echoed into the job log as `build.sh: step summary: ...`. A PC build
writes none.

### B62 (decisions 14-15)
- `fetch_lua`'s download, and `fetch_ui`'s `download()` and `git fetch`, run inside `netfetch.retry`. The sha256 and patch checks stay
  outside the retried call and still raise `SystemExit`.
- `fetch_ui.fetch_git` trusts a checkout only when HEAD is the pin and `netfetch._git_ok` passes; anything else is removed and fetched again.
- Retry and removal lines go to stderr.
- `netfetch.py` loses `prefetch` and `clean_checkouts`.
- `block_fetch_cache` renders two steps, and `gates.yml` is re-rendered.

### C2 (decision 16)
`fetch_ui.py`'s missing-key refusal names:
- `stb_image_write`: the in-game host's PNG dump, required since 0.10.0;
- the five keys;
- `CONSUMING.md` "The UI pin file", and that the file is a DLL input (`ui_pins`);
- the null game's `proxy/tests/null_game/viewer/pins.json` as the reference entry.

### Docs
- `docs/PROXY_BUILD.md` (new contract doc) covers the eight roles, the pin and its check, tracked sources, the `self_hash` line and its regex,
  the summary, and fetching.
- `docs/CONSUMING.md` links to it and gains "The build id names one DLL (0.27.0)". It is 30,616 of 30,720 bytes.
- `docs/DECISIONS.md` gains C25 (proposed); `docs/BACKLOG.md` loses B62 and B69; the tools rows are updated, and `toolchain` is new.

## Tests, red then green
- **Red first: commit 409ef9c, tests only.** On the PC, with `toolchain.py` moved aside, the four Python modules gave 116 tests: 8 failures and
  11 errors. The C++ was red by construction (`test_sha256.cpp` includes `sha256.h`, which did not exist yet). That red was not observed in CI.
- **Python cases:**
  - `toolchain` is the last role. Editing `toolchain.py` changes the id, and the moved fixture still locates the file.
  - `--sources`:
    - tracked names come out in byte order;
    - an untracked `.cpp`, an ignored `.h` and an untracked adapter `.inc` are each named;
    - a staged new file is listed and gives a `-dirty` id;
    - outside git it falls back to the glob.
  - `build.sh dll` exits 2 on an untracked `.cpp` before a stub `gen_tables.py` can run.
  - A clean list reaches `gen_tables.py`. This covers the CR fix: red without it.
  - `toolchain.py check` with a fake runner covers:
    - every package at its pin;
    - one package off its pin, and one missing;
    - a compiler owned by no package, or owned by `g++-13`;
    - no `dpkg-query`;
    - and the CLI's exit codes, 0, 2 and 64.
  - The fetchers:
    - a flaky `urlopen` or `git fetch` is retried, with its lines on stderr;
    - half-restored and half-fetched checkouts are removed;
    - a sha mismatch or a failed patch is never retried.
  - The other cases:
    - the refusal text;
    - the two-step `fetch_cache` render;
    - `SELF_HASH_RE` and `build_info()['dll_sha256']`, with `None` for an old log, no log, the WARN line, upper-case hex and a short hash.
- **C++ cases:**
  - `test_sha256.cpp` covers:
    - the empty string, `abc`, and the 448-bit two-block message;
    - one million `a` in 1000-byte updates;
    - a fixed digest of a 130-byte message from Python's `hashlib`, and every split point of that message.
  - The `test_guard.cpp` lint checks:
    - the exact format lines;
    - that `LogSelfHash(dll);` sits after the launch format and before `dll %ls` and `config: %ls %s`;
    - that `LogSelfHash` and `ReadChunks` name none of `LoadLibrary`, `CreateThread`, `_beginthread`, `WaitFor`, `BCrypt`, `Crypt`,
      `GetProcAddress` or `Sleep(`;
    - that `sha256.h` names no Windows header and no game.
- **Green:**
  - PC: full `python3 wsc.py gates`, 644 host tests, 0 failed.
  - CI 41808275796: 16 C++ suites, 0 failures. `test_sha256` passed 136 checks and `test_guard` 93 (81 before).

## CI evidence
**Final run 41808275796, at 05e1c74.** Every job is green (changes, gates on ubuntu and windows, proxy, harness-windows).
- The install step lists the seven `pkg=version` lines above.
- `build.sh` prints `toolchain: pinned: 7 packages at their pins; i686-w64-mingw32-g++-win32 (GCC) 13-win32; GNU ld (GNU Binutils) 2.41.90.20240122`
  for both `all` and `repro`.
- `d3d9.dll`: build `nullgame-ci`, sha256 `3a50d3fdd4a51a5200feb0c526e7c9948dd5696992796777d34b596396ffa8cd`, 4,408,320 bytes.
- The imports (`advapi32.dll dbghelp.dll kernel32.dll msvcrt.dll user32.dll`) are unchanged, and the export check passed.
- `build.sh repro: identical from another path`.
- `build.sh smoke: self_hash matches d3d9.dll (sha256 3a50d3fd...96ffa8cd, 4408320 bytes, build nullgame-ci, hashed in 13 ms under wine)`,
  then `smoke: passed (8 launches under wine, 2 dumps)`.
- The step summary is echoed in the log.

**Earlier runs:**

| Run | Head | Result |
|---|---|---|
| 41807186959 | 924ed1b | all green; self_hash took 17 ms |
| 41805349522 | 3fbb23d | `proxy` green (self_hash 24 ms). Both `gates` jobs failed on two `test_netfetch` cases, because the B62 commit was not yet pushed. |
| 41802947502 | 1d56eb6 | the probe: `proxy` stopped on purpose after printing the pinned set |

**self_hash** took 13 to 24 ms in CI's smoke, against a 100 ms cap. **DLL size** (null game): 4,403,712 bytes at the merge base, 4,408,320 on
the branch (+4,608).

## The id change
Measured with `build_id.py --root . --inputs` in a throwaway superproject (the null game at its root, the core as `core`). The id went from
`60f7dfc714ec` (origin/main c919977) to `ec2808bc5db8` (05e1c74):
- **Changed roles:** `core`, `build_sh`, `fetch_lua`, `build_id` and `fetch_ui`.
- **New role:** `toolchain` (`core/proxy/tools/toolchain.py` 6c087f07).
- **Unchanged roles:** `adapter` and `ui_pins`.

**The PC route.** `build.sh --docker all` on the PC exited 0 in 393 s:
- It printed the `toolchain: pinned` line, ran the same 16 suites with 0 failures, and built a 4,408,320-byte DLL with id `ec2808bc5db8`.
- `repro` was identical.
- `fetch_lua` got three `Connection refused` errors from www.lua.org and succeeded on the fourth try, so B62's retry cured a real flake on
  the PC route. The base's `--docker dll` had failed on the same refusal.

## Version
0.27.0, the next free minor above `main` (0.26.0, W23) and every open branch. The decision row is C25. W10 holds 0.26.0 and C24 on its
branch, so the numbers are re-checked at merge.

## Deviations from the brief and why
1. **`proxy/src/runtime.h` gains a `ReadChunks` declaration.** `dllmain.cpp` and `guard_driver.cpp` are separate translation units.
2. **`ReadChunks` takes a function pointer and a context, not a template.** That keeps the loop in `guard_driver.cpp`, where the brief puts it.
3. **B69 is removed from the backlog too.** It is the same finding, closed by decisions 1-3.
4. **C25, not C24.** W23 merged C24 mid-job.
5. **`origin/main` (W23) was merged in (0c9b189), without a rebase.** `VERSION`, `DECISIONS.md`, `ci_render.py`'s docstring and `CONSUMING.md`
   conflicted, and both sides were kept. `CONSUMING.md` then went over 30 KB, so this job's additions there were shortened.
6. **`netfetch.retry`'s `sleep` default is now `None`**, looked up at call time, so a test that patches it takes effect (an old test really
   slept about 5 s). `fetch_dxvk`'s retry lines also go to stderr now.
7. **`fetch_ui` refetches after a pin change.** Under decision 14's trust rule, a checkout at another pin is removed rather than fetched into.
8. **Step-summary lines are echoed into the job log**, because the summary file cannot be read through the REST API.
9. **A bug on the PC route, fixed in 05e1c74.**
   - Found by the local `--docker all` run: in Git Bash, a Windows `python3` prints CRLF, and `$(... | tr '\n' ' ')` keeps every CR but the
     last, so the container got `backend.cpp\r` and the PC route would have failed on every build.
   - `build.sh` now strips CRs with `tr -d '\r'` and refuses any source name outside `[A-Za-z0-9_.+-]`.
   - A host test runs the success path through the host's python3: red without the fix.
10. **`toolchain.py` has an `installed` mode** for decision 4's stamp.
11. **The smoke check is stricter than the brief:** the `self_hash` line must be log line 2 exactly.
12. **Not tested end to end:**
    - the C++ red, which was red by construction rather than observed;
    - `WSP_TOOLCHAIN=any`, since no off-pin toolchain exists here;
    - `--docker smoke`, not run locally (CI's smoke covers it).
13. **A temporary probe step** (1d56eb6, run 41802947502) stopped the `proxy` job on purpose, and was removed in 8fd64b2.

## Open questions
These are the brief's defaults, built as stated; they stay open for Liam:
1. **Pinning:** exact package versions in `toolchain.py`, not a dated snapshot archive. The version lines are never hashed.
2. **Off the pin:** refuse by default; `WSP_TOOLCHAIN=any` builds with a `-dirty` id.
3. **An untracked source:** refuse rather than build `-dirty`; `git add` gives `-dirty`.

New:
4. `CONSUMING.md` is at 30,616 of 30,720 bytes. The next job that adds to it should split a section out.
5. W23's bootstrap `pull_request` trigger in `ci/policy.yml.in` is still there (the `ci_render` warning); W27 removes it.

## What napoleon must do (J78)
- **Rule 79.** The build id and the DLL's bytes change, so the bump needs 20 consecutive acceptance passes on the new id, together with W33
  and the rest of audit train 1.
- **The `proxy` job in `ci/gates.yml.in`.** Replace the `g++-mingw-w64-i686` install with
  `sudo apt-get install -y -q --no-install-recommends $(python3 core/proxy/tools/toolchain.py apt)`, then run `python3 core/wsc.py ci render`.
  Without it, `build.sh` refuses once the archive's candidate differs from the pin. `{{wsc fetch_cache}}` is now two steps.
- **`tests/test_build_id.py`.** Its fixtures copy `proxy/tools/toolchain.py` beside `build.sh`, `build_id.py` and `layout.py`.
- **On the PC:**
  - `build.sh --docker` installs the pins;
  - the CR fix makes the source list safe from a Windows python3;
  - an untracked source under `core/proxy/src` or `proxy/<game>/` refuses the build.
- **`viewer/pins.json`** already has `stb_image_write`.
- **With W9:** each acceptance pass records `dll_sha256` from `build_info()`, and `proxy.log`'s second line is the `self_hash` line.

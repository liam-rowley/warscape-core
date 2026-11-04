# The proxy DLL build contract

What a build id names, how the DLL is built from it, and how a log proves which DLL ran (W24, C25). The scripts are `proxy/tools/build.sh`,
`build_id.py` and `toolchain.py`; how a game runs them is [PROXY_HARNESS.md](PROXY_HARNESS.md).

## The build id: committed inputs under role names
`build_id.py` hashes the git object id of each DLL input at a revision, under a fixed role name, in this order (12 hex of sha256 over
`role oid` lines; a role is found in the game repo, else inside a submodule at the commit its gitlink pins):

| Role | Path | What it decides |
|---|---|---|
| `core` | `proxy/src` (the core's sources) | the DLL's own code |
| `adapter` | the game's proxy adapter folder (`layout.py proxy-adapter`) | the game's tables, identity and config |
| `build_sh` | `proxy/tools/build.sh` | flags, link order, the checks |
| `fetch_lua` | `proxy/tools/fetch_lua.py` | the engine-patched Lua 5.1.1 |
| `build_id` | `proxy/tools/build_id.py` | the id and the source list |
| `fetch_ui` | `proxy/tools/fetch_ui.py` | RmlUi, FreeType, the host's Lua and stb |
| `ui_pins` | the game's UI pin file (`layout.py ui-pins`) | the commits and sha256 the UI fetcher takes |
| `toolchain` | `proxy/tools/toolchain.py` | the build image and every mingw-w64 package, at exact versions |

`-dirty` is appended when an input's working copy differs from HEAD. **Rule 79 of the first consumer recomputes the id from committed
content with no compiler**, so nothing installed is ever measured into it. `build.sh id` prints the id alone (no compiler, no check).
`build_id.py --inputs` prints each role, path and object id.

## The toolchain pin
`toolchain.py` holds `PIN = {'image': <ubuntu:24.04 by digest>, 'apt': {package: exact version}}`: the packages that
`apt-get install --no-install-recommends g++-mingw-w64-i686-win32` installs (the compiler, its C driver and runtime, binutils, and
`mingw-w64-i686-dev`, the headers, CRT and import libraries linked into the DLL), all from the `noble` release pocket, which never changes.
- **Install:** `sudo apt-get install -y -q --no-install-recommends $(python3 proxy/tools/toolchain.py apt)` (CI);
  `build.sh --docker` takes the image (`toolchain.py image`) and the same packages, so a PC build is CI's build by construction.
- **Check:** before the first mingw compile of `dll`, `all` and `repro`, `build.sh` runs `toolchain.py check "$CXX"`: every pinned package
  installed at its version (`dpkg-query`), and the resolved compiler (`readlink -f`) owned by a pinned package (`dpkg -S`), so a compiler
  earlier on `PATH` cannot stand in. OK is one line, `toolchain: pinned: <n> packages at their pins; <g++ first line>; <ld first line>`.
  Otherwise one line per difference and the fix, and `build.sh` exits 2.
- **`WSP_TOOLCHAIN=any`** builds off the pin and appends `-dirty` to the id once: a DLL from another toolchain is not the DLL the committed
  id names, and no acceptance pass counts it.
- **A bump** is a core job that edits `PIN` (a new id: a new toolchain is a new DLL). If the archive drops a pinned version, `apt-get` fails
  in CI and on the PC alike. The version lines are printed, never hashed: they name neither the package revision nor `mingw-w64-i686-dev`.
- The cached UI objects (`build/ui/obj/mingw32`) are stamped with the installed versions (`toolchain.py installed`), so a toolchain change
  rebuilds them. The CI runner image stays outside the pass-marker key: it cannot change the DLL's bytes once the toolchain is checked.

## Tracked sources only
`build_id.py --sources` lists the tracked top-level `*.cpp` of the core sources folder (`git -C <folder> ls-files`, the index of the
repository that holds it), byte-sorted, and `build.sh` compiles exactly those (minus `ui_lua.cpp`, linked through its own object) for the
DLL and `repro`'s copy; `--docker` passes the host's list in as `WSP_SOURCES`. An untracked or ignored `.c .cpp .h .hpp .inc .def` under the
core sources or the adapter folder refuses the build (exit 2, each file named) before anything compiles: `git add` it (a staged file is
compiled and the id is `-dirty`) or move it out. Outside git, every `*.cpp` is compiled and the tool says so.

## The DLL's own sha256: the `self_hash` line
Right after the launch line, `Init` (inside `DllMain`) hashes the DLL **file** (not the relocated image) with `sha256.h` through the guard's
read loop: `CreateFileW`, `ReadFile`, `CloseHandle`, `GetTickCount`; no library load, crypto provider, thread or wait. Every launch logs it as
the **second line** of `proxy.log` (and of a second process's `proxy.p<pid>.log`), at INFO:
```
self_hash: sha256 <64 lowercase hex> bytes <decimal size> build <WSP_BUILD_ID> (hashed in <decimal> ms)
```
On failure, at WARN: `self_hash: unavailable: <reason>` (the open or read error and its code). Parse it with
`\bself_hash: sha256 ([0-9a-f]{64}) bytes ([0-9]+) build (\S+) \(hashed in ([0-9]+) ms\)` (`harness/ctl.py` `SELF_HASH_RE`;
`build_info()['dll_sha256']`). A log with neither line comes from a DLL older than 0.27.0. The sha256 equals `sha256sum d3d9.dll`, the kit
manifest's entry and the build line `build.sh: <path> build <id> sha256 <hex>`; `build.sh smoke` checks the first two, and the line's `build`
against the launch line's, on every CI run.

## The CI step summary
When `$GITHUB_STEP_SUMMARY` is set, `build.sh` writes `### proxy DLL: <adapter>` with the build id, `d3d9.dll`'s sha256 and bytes and the
toolchain line; `repro` adds `repro: identical from another path`, `smoke` adds `smoke: self_hash in proxy.log matches d3d9.dll (<ms> ms
under wine)`. A PC build writes nothing.

## Fetching
`fetch_lua.py` and `fetch_ui.py` retry each download and `git fetch` on a network flake (`netfetch.retry`, one stderr line each), never a
sha256 mismatch or a failed patch; `fetch_ui.py` trusts a checkout only when HEAD is the pin and the working tree equals HEAD.

## Symbolising a crash (W35, C35)
- **The map.** `build.sh dll` links with `-Wl,-Map` (no `--cref`: the verb reads sections and symbols only) and writes, beside the DLL in
  `build/proxy/<adapter>/`, `d3d9.map` (checkout paths become the labels `core/`, `adapter/`, `out/`, `ui/`; gcc's temporary objects are named
  after their sources in link order), `d3d9.map.json` (`{dll, build_id, dll_sha256, image_base, size, size_of_image}`, the id and sha256 of
  the build line) and `d3d9.map.build.txt` (the build line). No timestamp enters them. `repro` compares both maps from another path and
  links once more without the flag: the DLL must be byte-identical (both sha256 printed); a difference fails the job, never waived.
- **CI keeps it.** The `{{wsc proxy_map step=<id>}}` block after the build step (`id: dll`) uploads `proxy-map-<build id>`, the name
  `build.sh` wrote to the step's outputs, for 90 days (GitHub's maximum), and links it in the step summary. A map outlives 90 days only by
  being kept: **a release attaches `d3d9.map` and `d3d9.map.json` to the release it publishes** (the consumer's release builder).
- **The command.** `python3 core/wsc.py crash symbolise <dump> --map d3d9.map [--log proxy.log] [--dll d3d9.dll]`, or `--build-id <id>
  [--run <run id>]` to fetch the artifact with `gh` into `_scratch/maps/<id>/`. Standard library only, no debugger, no network but `gh`.
  The sidecar must agree with the launch line and `self_hash` of `--log`, the sha256 of `--dll` and the module's size of image in the
  dump, else it refuses (exit 2) with both values; `--force-map` uses it anyway and prefixes every line `WRONG MAP?`.
- **What it prints.** The exception (code, name, address, thread), the **exception frame** as `d3d9.dll+rva  .text: symbol+offset [object]`
  (certain: the faulting instruction), then up to 16 **stack scan** candidates: words on the faulting thread's stack that point into the
  DLL's code, by depth. A 32-bit mingw DLL has no `.pdata`, so a scan hit is a candidate (a stale return address or a function pointer can
  look the same), never a frame. The map lists globals only: a static function shows as the nearest preceding global of its object.
  Addresses outside the DLL print `module+rva` (`--sites <engine_sites>` adds the site an exe rva falls in). Exit 0 named, 1 no frame in
  the DLL (the module list is printed), 2 refused. The in-process dump has the stacks and the memory they reference, not full memory, so
  scans are best effort; the exception frame is always named.
- **Proof.** The smoke's step 9 faults inside the DLL (the stand-in exe calls `wsp_sentinel` with a bad `lua_State`) and the verb must
  name `lua_gettop` (with the PE leading underscore when the toolchain adds one); CI uploads that dump and log as `proxy-smoke-dll-fault`.

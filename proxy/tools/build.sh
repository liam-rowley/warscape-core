#!/usr/bin/env bash
# purpose: build the proxy d3d9.dll (mingw-w64 i686, the release route) and/or build and run the host tests (g++)
# usage: proxy/tools/build.sh [--docker] [dll|tests|all|smoke|repro|id] [--adapter DIR]   (DIR: the game's proxy adapter folder, default proxy/tools/layout.py proxy-adapter; --docker: the same target inside ubuntu:24.04 pinned by digest with CI's packages, the PC route (D31); smoke: run the built DLL under wine with a stand-in exe; repro: rebuild from a copy at another path, fail unless byte-identical; id: print the build id only)   (outputs in <game repo>/build/proxy/; needs g++-mingw-w64-i686 for dll, or Docker Desktop with --docker)
# when: after any change to the proxy sources or the adapter (CI runs `all` on every push); on the PC always with --docker; the DLL in <game repo>/build/proxy/<adapter name>/d3d9.dll is what proxy/tools/pc_deploy.py kits
# not-a-verb: a compiler driver for C++ sources, not a registry operation; CI and agents call it directly
set -euo pipefail
# Paths (J12): OWN is the repo holding this script (the game repo before the move, warscape-core after). The game repo, the core
# sources and the adapter come from proxy/tools/layout.py, never from this script's location or a game name: one file for both layouts.
OWN="$(cd "$(dirname "$0")/../.." && pwd)"
layout() { python3 "$OWN/proxy/tools/layout.py" "$1" || exit 2; }
upath() { if command -v cygpath >/dev/null; then cygpath -u "$1"; else printf '%s\n' "$1"; fi; }
DOCKER=0; [[ "${1:-}" == "--docker" ]] && { DOCKER=1; shift; }
# D31: the container CI's proxy job runs in (ubuntu-24.04), pinned by digest, with the packages CI installs or its runner image has
IMAGE="ubuntu@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852"   # ubuntu:24.04, pinned 2026-10-29
APT="g++-mingw-w64-i686 g++ python3 ca-certificates"
WHAT="${1:-all}"
if [[ "${2:-}" == "--adapter" ]]; then WSP_PROXY_ADAPTER="$(cd "${3:?adapter folder}" && pwd)"; export WSP_PROXY_ADAPTER; fi
ROOT="$(upath "$(layout game-root)")"; SRC="$(upath "$(layout proxy-src)")"; ADIR="$(upath "$(layout proxy-adapter)")"; ADAPTER="$(basename "$ADIR")"
OUT="$ROOT/build/proxy"; mkdir -p "$OUT/$ADAPTER" "$OUT/tests"
# Build id = a hash of the DLL inputs' content (proxy/tools/build_id.py, the one implementation, which rule 79 also uses): a report
# commit, a reword or a rebase that leaves the inputs alone keeps the id; -dirty when an input has local changes (J45).
if [[ -n "${WSP_BUILD_ID:-}" ]]; then
  BUILD_ID="$WSP_BUILD_ID"   # inside --docker: the host computed it (a worktree's .git points at a host path the container cannot see)
else
  BUILD_ID="$(python3 "$OWN/proxy/tools/build_id.py")" || { echo "build.sh: no build id (above)"; exit 4; }
fi
[[ "$WHAT" == id ]] && { echo "$BUILD_ID"; exit 0; }   # the id this checkout's DLL would carry (tests: build.sh and rule 79 agree)

if [[ $DOCKER == 1 ]]; then
  docker info >/dev/null 2>&1 || { echo "build.sh --docker: Docker is not answering: start Docker Desktop (Linux containers); fallback: the CI artifact (proxy/README.md \"Build\")"; exit 2; }
  # smoke: the same container plus the wine packages CI's proxy job installs (J42); it runs the DLL `--docker all` left in build/proxy/
  PRE=":"
  if [[ "$WHAT" == smoke ]]; then
    [[ -f "$OUT/$ADAPTER/d3d9.dll" ]] || { echo "build.sh --docker smoke: no $OUT/$ADAPTER/d3d9.dll: run build.sh --docker all first"; exit 2; }
    PRE="dpkg --add-architecture i386"; APT="$APT wine wine32:i386"
  fi
  # The game repo is mounted at /src (the core, as its submodule, is inside it). The container has no git: it is told the game root
  # and the adapter, as paths relative to the mount.
  rel() { python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]).replace(os.sep, "/"))' "$1" "$ROOT"; }
  MNT="$ROOT"; command -v cygpath >/dev/null && MNT="$(cygpath -w "$ROOT")"   # Git Bash: docker wants C:\...
  echo "build.sh --docker: $WHAT in $IMAGE, build $BUILD_ID"
  # MSYS_NO_PATHCONV: Git Bash would rewrite /src and the -v argument into Windows paths
  MSYS_NO_PATHCONV=1 docker run --rm -v "$MNT:/src" -w /src -e WSP_BUILD_ID="$BUILD_ID" -e WSP_GAME_ROOT=/src -e WSP_PROXY_ADAPTER="/src/$(rel "$ADIR")" "$IMAGE" bash -c \
    "set -e; $PRE; apt-get update -q >/dev/null; DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends $APT >/dev/null
     i686-w64-mingw32-g++-win32 --version | head -1; $(rel "$OWN")/proxy/tools/build.sh $WHAT"
  exit $?
fi

# One compile line for every build (dll and repro): $1 = core sources, $2 = adapter folder, $3 = output DLL. Uses $CXX, $BUILD_ID.
# File names in the DLL are fixed labels (core/, adapter/, lua/), never checkout paths: the same inputs give the same bytes from any
# folder and in either layout (before and after the move to warscape-core; J12 proves it with `id` and `repro`).
LUA_SRC="$ROOT/build/lua/src"   # proxy/tools/fetch_lua.py: Lua 5.1.1, pinned, patched for the engine
build_dll() {
  local S="$1" A="$2" O="$3" L="$3.lua"; mkdir -p "$L"
  local CC="${CXX/g++/gcc}"
  for c in lapi lcode ldebug ldo ldump lfunc lgc llex lmem lobject lopcodes lparser lstate lstring ltable ltm lundump lvm lzio lauxlib; do
    "$CC" -std=gnu99 -O2 -w -ffile-prefix-map="$LUA_SRC/"=lua/ -c -o "$L/$c.o" "$LUA_SRC/$c.c"
  done
  # -win32 thread model (no winpthread DLL), static libgcc/libstdc++ (the DLL depends on system DLLs only), no PE timestamp and
  # relative file names (the same sources give the same bytes: the PC test binary is the CI binary). --disable-auto-image-base: mingw
  # ld otherwise hashes the OUTPUT PATH into the DLL's ImageBase, so the container, CI and a worktree gave three different DLLs for
  # one commit (review of J1, 2026-10-28). `build.sh repro` proves it stays fixed.
  "$CXX" -std=c++17 -O2 -s -shared -Wall -Wextra -Werror -DWSP_BUILD_ID="\"$BUILD_ID\"" -D_WIN32_WINNT=0x0601 -DUNICODE -D_UNICODE \
    -ffile-prefix-map="$S/"=core/ -ffile-prefix-map="$A/"=adapter/ -static-libgcc -static-libstdc++ -Wl,--no-insert-timestamp -Wl,--disable-auto-image-base -Wl,--enable-stdcall-fixup \
    -I"$S" -I"$LUA_SRC" -o "$O" "$S"/*.cpp "$A/adapter.cpp" "$L"/*.o "$S/d3d9.def" -ldbghelp -ladvapi32
}

python3 "$OWN/proxy/tools/gen_tables.py" --check
if [[ "$WHAT" == dll || "$WHAT" == all || "$WHAT" == repro ]]; then python3 "$OWN/proxy/tools/fetch_lua.py" --out "$ROOT/build/lua" >/dev/null; fi

if [[ "$WHAT" == dll || "$WHAT" == all ]]; then
  CXX="$(command -v i686-w64-mingw32-g++-win32 || command -v i686-w64-mingw32-g++ || true)"
  [[ -n "$CXX" ]] || { echo "build.sh: no i686 mingw-w64 g++ (apt-get install g++-mingw-w64-i686)"; exit 2; }
  build_dll "$SRC" "$ADIR" "$OUT/$ADAPTER/d3d9.dll"
  echo "build.sh: $OUT/$ADAPTER/d3d9.dll build $BUILD_ID sha256 $(sha256sum "$OUT/$ADAPTER/d3d9.dll" | cut -c1-64)"
  if command -v i686-w64-mingw32-objdump >/dev/null; then
    DEPS="$(i686-w64-mingw32-objdump -p "$OUT/$ADAPTER/d3d9.dll" | awk '/DLL Name/{print tolower($3)}' | sort -u | tr '\n' ' ')"
    echo "build.sh: imports $DEPS"
    # user32: the headless window guard (J13); the game exe imports it anyway, so it is already loaded
    for d in $DEPS; do case "$d" in kernel32.dll|advapi32.dll|dbghelp.dll|msvcrt.dll|user32.dll|api-ms-win-*) ;; *) echo "build.sh: unexpected import $d"; exit 3;; esac; done
    EXP="$(i686-w64-mingw32-objdump -p "$OUT/$ADAPTER/d3d9.dll" | awk '/\[Ordinal\/Name Pointer\] Table/{f=1;next} f&&NF==0{f=0} f{print $NF}' | sort | tr '\n' ' ')"
    echo "build.sh: exports $EXP"
    for e in $(awk '/^EXPORTS/{f=1;next} f&&NF&&$1!~/^;/{print $1}' "$SRC/d3d9.def"); do
      [[ " $EXP " == *" $e "* ]] || { echo "build.sh: export $e missing (decorated?)"; exit 3; }
    done
  fi
fi

if [[ "$WHAT" == tests || "$WHAT" == all ]]; then
  fail=0
  # the tests include core headers, the adapter's generated tables and testkit.h by name, and read files through --src/--adapter/--tests
  for t in "$OWN"/proxy/tests/test_*.cpp; do
    n="$(basename "$t" .cpp)"
    g++ -std=c++17 -O1 -Wall -Wextra -Werror -I"$SRC" -I"$ADIR" -I"$OWN/proxy/tests" -o "$OUT/tests/$n" "$t"
    if "$OUT/tests/$n" --src "$SRC" --adapter "$ADIR" --tests "$OWN/proxy/tests"; then :; else echo "build.sh: $n FAILED"; fail=1; fi
  done
  [[ $fail == 0 ]] && echo "build.sh: host tests passed" || exit 1
fi

if [[ "$WHAT" == repro ]]; then
  # The same inputs must give the same bytes from any checkout path (container, CI runner, worktree, either layout): build again
  # from copies of the core sources and the adapter.
  [[ -f "$OUT/$ADAPTER/d3d9.dll" ]] || { echo "build.sh repro: build the dll first"; exit 2; }
  R="$(mktemp -d)/elsewhere_$RANDOM"; mkdir -p "$R"
  cp -a "$SRC" "$R/src"; cp -a "$ADIR" "$R/adapter"   # the build id was computed above
  CXX="$(command -v i686-w64-mingw32-g++-win32 || command -v i686-w64-mingw32-g++)"
  build_dll "$R/src" "$R/adapter" "$R/other.dll"
  if cmp -s "$OUT/$ADAPTER/d3d9.dll" "$R/other.dll"; then echo "build.sh repro: identical from another path"; rm -rf "$(dirname "$R")"
  else echo "build.sh repro: FAILED: the DLL depends on the checkout path"; cmp -l "$OUT/$ADAPTER/d3d9.dll" "$R/other.dll" | head -5; exit 1; fi
fi

if [[ "$WHAT" == smoke ]]; then
  command -v wine >/dev/null || { echo "build.sh smoke: wine not installed (apt-get install wine wine32:i386)"; exit 2; }
  CXX="$(command -v i686-w64-mingw32-g++-win32 || command -v i686-w64-mingw32-g++)"
  # the stand-in exe, the mod folder and the config file carry the names the adapter's identity.json gives them
  ident() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]])' "$ADIR/identity.json" "$1"; }
  EXE="$(ident exe_name)"; MOD="$(ident mod_dir)"; INI="$(ident config_file)"
  G="$OUT/smoke/game"; rm -rf "$OUT/smoke"; mkdir -p "$G"
  "$CXX" -O1 -static -o "$G/$EXE" "$OWN/proxy/tests/smoke_host.cpp"
  cp "$OUT/$ADAPTER/d3d9.dll" "$G/"
  run() { (cd "$G" && WINEDEBUG=-all WINEDLLOVERRIDES="d3d9=n,b;winedbg.exe=d" timeout 120 wine "$EXE" "$@") ; }
  check() { grep -q "$1" "$G/$MOD/logs/proxy.log" || { echo "build.sh smoke: '$1' not in the log"; cat "$G/$MOD/logs/proxy.log"; exit 1; }; }
  # 1) default config: the stand-in exe is not the pinned build -> MISMATCH, pass-through, notice, system fallback (no DXVK), clean detach
  run; check "exe_guard: MISMATCH"; check "PASS-THROUGH"; check "patch_engine: not run"; check "backend: dxvk unavailable"; check "process detach"
  [[ -f "$G/$MOD/EXE_MISMATCH.txt" ]] || { echo "build.sh smoke: no notice"; exit 1; }
  # 2) developer override + system backend + an unknown key: engine path on, patch engine runs and refuses every site (none of the
  #    adapter's engine_sites exist in the stand-in exe; any count, J15 added the first), notice removed, unknown key warned
  printf '[proxy]\r\nbackend=system\r\nexe_guard=0\r\nbogus=1\r\n' > "$G/$INI"
  run; check "OVERRIDE"; check "patch_engine: REFUSED - [0-9]* sites: 0 ok, [0-9]* bad, 0 to write"; check "unknown key proxy.bogus"; check "removed the stale"; check "process detach"
  [[ -f "$G/$MOD/logs/proxy.prev.log" ]] || { echo "build.sh smoke: previous log not kept"; exit 1; }
  # 3) forced mismatch wins over the override
  printf '[proxy]\r\nbackend=system\r\nexe_guard=0\r\nexe_guard_force_mismatch=1\r\n' > "$G/$INI"
  run; check "FORCED MISMATCH"; check "process detach"
  # 4) crash capture end to end: an access violation in the host -> our filter (still ours at the first create) -> a .dmp named in the log.
  #    minidump=1 explicitly: the default became 2 (J3), where the first-chance dump is the launch's one dump and the unhandled filter
  #    has nothing left to write (this step failed in CI from 858aa97 until it said so)
  printf '[proxy]\r\nbackend=system\r\nminidump=1\r\n' > "$G/$INI"
  run crash || true
  check "top-level filter at first Direct3DCreate9: still ours"; check "UNHANDLED exception 0xc0000005"; check "minidump (unhandled) written"
  dmp="$(grep -o 'minidump (unhandled) written: .*' "$G/$MOD/logs/proxy.log" | sed 's/.*\\//' | tr -d '\r')"
  [[ -s "$G/$MOD/dumps/$dmp" ]] || { echo "build.sh smoke: the dump the log names ($dmp) is missing or empty"; ls -la "$G/$MOD/dumps"; exit 1; }
  [[ "$(head -c4 "$G/$MOD/dumps/$dmp")" == MDMP ]] || { echo "build.sh smoke: $dmp is not a minidump (no MDMP signature)"; exit 1; }
  # 5) the host replaces the top-level filter (as a game may): logged as REPLACED; mode 2 still dumps the first-chance AV
  printf '[proxy]\r\nbackend=system\r\nminidump=2\r\n' > "$G/$INI"
  run replace crash || true
  check "top-level filter at first Direct3DCreate9: REPLACED by $EXE"; check "minidump (first-chance) written"
  echo "build.sh smoke: passed (5 launches under wine, 2 dumps)"
fi

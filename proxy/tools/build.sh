#!/usr/bin/env bash
# purpose: build the proxy d3d9.dll (mingw-w64 i686, the release route) and/or build and run the host tests (g++)
# usage: proxy/tools/build.sh [--docker] [dll|tests|all|smoke|repro|id] [--adapter DIR]   (DIR: the game's proxy adapter folder, default proxy/tools/layout.py proxy-adapter; --docker: the same target inside the image proxy/tools/toolchain.py pins, with its pinned mingw-w64 packages, the PC route (D31); smoke: run the built DLL under wine with a stand-in exe; repro: rebuild from a copy at another path, fail unless byte-identical; id: print the build id only)   (outputs in <game repo>/build/proxy/; dll needs the pinned mingw-w64 packages, `toolchain.py apt` (WSP_TOOLCHAIN=any builds off the pin with a -dirty id), or Docker Desktop with --docker; contract: docs/PROXY_BUILD.md)
# when: after any change to the proxy sources or the adapter (CI runs `all` on every push); on the PC always with --docker; the DLL in <game repo>/build/proxy/<adapter name>/d3d9.dll is what proxy/tools/pc_deploy.py kits
# not-a-verb: a compiler driver for C++ sources, not a registry operation; CI and agents call it directly
set -euo pipefail
# Paths (J12): OWN is the repo holding this script (the game repo before the move, warscape-core after). The game repo, the core
# sources and the adapter come from proxy/tools/layout.py, never from this script's location or a game name: one file for both layouts.
OWN="$(cd "$(dirname "$0")/../.." && pwd)"
layout() { python3 "$OWN/proxy/tools/layout.py" "$1" || exit 2; }
upath() { if command -v cygpath >/dev/null; then cygpath -u "$1"; else printf '%s\n' "$1"; fi; }
DOCKER=0; [[ "${1:-}" == "--docker" ]] && { DOCKER=1; shift; }
TC="$OWN/proxy/tools/toolchain.py"   # W24 (C25): the image and the mingw-w64 packages at exact versions, a build-id input
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
# W24 (C25): the DLL compiles the tracked top-level *.cpp of the core sources (build_id.py --sources, byte-sorted, the link order of
# `LC_ALL=C ls`); an untracked or ignored source under the core sources or the adapter refuses the build here (exit 2), before
# gen_tables.py and the fetchers, with no compiler. Inside --docker the host's list comes in as WSP_SOURCES (as WSP_BUILD_ID: the
# container cannot read a worktree's .git).
SOURCES=""
if [[ "$WHAT" == dll || "$WHAT" == all || "$WHAT" == repro ]]; then
  if [[ -n "${WSP_SOURCES:-}" ]]; then SOURCES="$WSP_SOURCES"
  # tr -d '\r': a Windows python3 (Git Bash, the PC's --docker route) ends each line with CRLF, and `$(...)` strips only the last CR
  else SOURCES="$(python3 "$OWN/proxy/tools/build_id.py" --sources | tr -d '\r' | tr '\n' ' ')" || { echo "build.sh: refused: the DLL compiles tracked sources only (above)"; exit 2; }
  fi
  [[ -n "${SOURCES// /}" ]] || { echo "build.sh: no tracked *.cpp in $SRC"; exit 2; }
  re='[^A-Za-z0-9_. +-]'; [[ ! "$SOURCES" =~ $re ]] || { echo "build.sh: a source name outside [A-Za-z0-9_.+-]: $(printf '%q' "$SOURCES")"; exit 2; }
fi

if [[ $DOCKER == 1 ]]; then
  docker info >/dev/null 2>&1 || { echo "build.sh --docker: Docker is not answering: start Docker Desktop (Linux containers); fallback: the CI artifact (proxy/README.md \"Build\")"; exit 2; }
  # D31: the container is CI's (ubuntu-24.04), both from toolchain.py: the image by digest and the mingw-w64 packages at their pins, so the
  # PC's DLL is CI's by construction; g++ (host tests), python3, ca-certificates, git (fetch_ui.py, J30) and the smoke's wine stay unpinned
  # (they do not make the DLL). The container runs the same toolchain check before it compiles.
  IMAGE="$(python3 "$TC" image)" || exit 2
  APT="$(python3 "$TC" apt) g++ python3 ca-certificates git" || exit 2
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
  MSYS_NO_PATHCONV=1 docker run --rm -v "$MNT:/src" -w /src -e WSP_BUILD_ID="$BUILD_ID" -e WSP_SOURCES="$SOURCES" -e WSP_GAME_ROOT=/src -e WSP_PROXY_ADAPTER="/src/$(rel "$ADIR")" "$IMAGE" bash -c \
    "set -e; $PRE; apt-get update -q >/dev/null; DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends $APT >/dev/null
     $(rel "$OWN")/proxy/tools/build.sh $WHAT"
  exit $?
fi

# W24 (C25): the toolchain is checked before the first mingw compile of dll, all and repro: every pinned package at its version and $CXX
# owned by one of them (toolchain.py check). Off the pin the build is refused (exit 2) unless WSP_TOOLCHAIN=any, which builds and marks the
# id -dirty once: a DLL from another toolchain is not the DLL the committed id names. `id` above never gets here (rule 79 needs no compiler).
# W24: the CI step summary, when $GITHUB_STEP_SUMMARY is set (every consumer's CI gets it with no template change; a PC build writes none)
summary() { if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then printf '%s\n' "$@" >> "$GITHUB_STEP_SUMMARY"; printf 'build.sh: step summary: %s\n' "$@"; fi; }
TOOLCHAIN_LINE=""
toolchain_check() {   # $1 = the mingw g++ the build will use
  [[ -n "$TOOLCHAIN_LINE" ]] && return 0
  local out rc=0
  out="$(python3 "$TC" check "$1")" || rc=$?
  echo "$out"
  if [[ $rc == 0 ]]; then TOOLCHAIN_LINE="$out"; return 0; fi
  [[ $rc == 2 ]] || { echo "build.sh: toolchain.py check failed (exit $rc)"; exit 2; }
  if [[ "${WSP_TOOLCHAIN:-}" == any ]]; then
    [[ "$BUILD_ID" == *-dirty ]] || BUILD_ID="$BUILD_ID-dirty"
    TOOLCHAIN_LINE="toolchain: off the pin (WSP_TOOLCHAIN=any): build $BUILD_ID"
    echo "build.sh: WSP_TOOLCHAIN=any: building off the pin as $BUILD_ID (not the DLL the committed id names)"; return 0
  fi
  echo "build.sh: the toolchain is not the pinned one (above): refused (exit 2)"; exit 2
}

# One compile line for every build (dll and repro): $1 = core sources, $2 = adapter folder, $3 = output DLL. Uses $CXX, $BUILD_ID.
# File names in the DLL are fixed labels (core/, adapter/, lua/), never checkout paths: the same inputs give the same bytes from any
# folder and in either layout (before and after the move to warscape-core; J12 proves it with `id` and `repro`).
LUA_SRC="$ROOT/build/lua/src"   # proxy/tools/fetch_lua.py: Lua 5.1.1, pinned, patched for the engine
UI_SRC="$ROOT/build/ui/src"     # proxy/tools/fetch_ui.py: RmlUi, FreeType, the host's own Lua (float only) and stb, by the game's UI pins (J30)
UI_DEFS=(-DRMLUI_STATIC_LIB -DRMLUI_FONT_ENGINE_FREETYPE '-DRMLUI_VERSION="6.3"')
LUA_CORE="lapi lcode ldebug ldo ldump lfunc lgc llex lmem lobject lopcodes lparser lstate lstring ltable ltm lundump lvm lzio lauxlib"

# The RmlUi host's third-party objects (J30): RmlUi Core with its FreeType font engine, FreeType (TrueType only: sfnt, truetype,
# autofit, psnames, smooth; no zlib, bzip2, png, harfbuzz or brotli) and, for the Lua binding, RmlUi's Lua plugin plus a second Lua 5.1.1
# (the viewer's: float numbers, collector and dummynode untouched). They depend only on the pinned sources and these flags, so they are
# cached per compiler under build/ui/obj/<tag> (a stamp of the pin file, the flags and the compiler); file names in them are labels (ui/).
# The mingw32 stamp also holds the installed versions of the pinned toolchain packages (W24: the compiler's first line names neither the
# package revision nor mingw-w64-i686-dev), so a toolchain change rebuilds build/ui/obj/mingw32, which persists between --docker builds.
# $1 compiler (g++), $2 C compiler, $3 tag. Prints the object folder.
ui_objs() {   # $4 core sources (the compat header)
  local CXXU="$1" CCU="$2" U="$ROOT/build/ui/obj/$3" stamp tc=""; export UIS="$4"
  if [[ "$3" == mingw32 ]]; then tc="$(python3 "$TC" installed)" || exit 2; fi
  stamp="$( { sha256sum "$(layout ui-pins)" "$4/ui_lua51_compat.h" | cut -c1-64; "$CXXU" --version | head -1; echo "${UI_DEFS[*]} O2 v2"; [[ -z "$tc" ]] || echo "$tc"; } | sha256sum | cut -c1-16)"
  if [[ -f "$U/STAMP" && "$(cat "$U/STAMP")" == "$stamp" ]]; then echo "$U"; return; fi
  rm -rf "$U"; mkdir -p "$U/rml" "$U/ft" "$U/lua" "$U/rmllua" "$U/ftconf"
  # FreeType configuration: the stock options without zlib (as the viewer's CMake FT_DISABLE_ZLIB), and only the TrueType modules
  sed 's|^#define FT_CONFIG_OPTION_USE_ZLIB|/* J30: no zlib */ /* #define FT_CONFIG_OPTION_USE_ZLIB */|' "$UI_SRC/freetype/include/freetype/config/ftoption.h" > "$U/ftconf/ui_ftoption.h"
  grep -q 'no zlib' "$U/ftconf/ui_ftoption.h" || { echo "build.sh: the FreeType zlib option was not found" >&2; exit 3; }
  printf '%s\n' 'FT_USE_MODULE( FT_Module_Class, autofit_module_class )' 'FT_USE_MODULE( FT_Driver_ClassRec, tt_driver_class )' \
    'FT_USE_MODULE( FT_Module_Class, psnames_module_class )' 'FT_USE_MODULE( FT_Module_Class, sfnt_module_class )' \
    'FT_USE_MODULE( FT_Renderer_Class, ft_smooth_renderer_class )' > "$U/ftconf/ui_ftmodule.h"
  local FTF=(-std=gnu99 -O2 -w -DFT2_BUILD_LIBRARY '-DFT_CONFIG_OPTIONS_H=<ui_ftoption.h>' '-DFT_CONFIG_MODULES_H=<ui_ftmodule.h>' -I"$U/ftconf" -I"$UI_SRC/freetype/include" -ffile-prefix-map="$UI_SRC/"=ui/ -ffile-prefix-map="$U/"=uiobj/)
  local RMF=(-std=c++17 -O2 -w "${UI_DEFS[@]}" -I"$UI_SRC/rmlui/Include" -I"$UI_SRC/freetype/include" -I"$U/ftconf" '-DFT_CONFIG_OPTIONS_H=<ui_ftoption.h>' '-DFT_CONFIG_MODULES_H=<ui_ftmodule.h>' -ffile-prefix-map="$UI_SRC/"=ui/ -ffile-prefix-map="$U/"=uiobj/)
  local LUF=(-std=gnu99 -O2 -w -ffile-prefix-map="$UI_SRC/"=ui/)
  local jobs; jobs="$( (nproc || echo 4) 2>/dev/null)"
  local list="$U/list.txt"; : > "$list"
  local f
  for f in base/ftsystem base/ftinit base/ftdebug base/ftbase base/ftmm base/ftbitmap sfnt/sfnt truetype/truetype autofit/autofit psnames/psnames smooth/smooth; do
    echo "C ft/${f//\//_}.o $UI_SRC/freetype/src/$f.c" >> "$list"
  done
  for f in $LUA_CORE lbaselib lstrlib ltablib lmathlib ldblib; do echo "L lua/$f.o $UI_SRC/lua/src/$f.c" >> "$list"; done
  local core="$UI_SRC/rmlui/Source/Core"
  while IFS= read -r f; do r="${f#"$core/"}"; echo "X rml/${r//\//_}.o $f" >> "$list"; done < <(find "$core" "$core/Elements" "$core/Layout" "$core/FontEngineDefault" -maxdepth 1 -name '*.cpp' | LC_ALL=C sort -u)
  while IFS= read -r f; do r="${f#"$UI_SRC/rmlui/Source/Lua/"}"; echo "Y rmllua/${r//\//_}.o $f" >> "$list"; done < <(find "$UI_SRC/rmlui/Source/Lua" -name '*.cpp' | LC_ALL=C sort)
  # one compiler per line, in parallel; any failure fails the build
  export CXXU CCU U; export FTF_S="${FTF[*]}" RMF_S="${RMF[*]}" LUF_S="${LUF[*]}" LUAI="-I$UI_SRC/lua/src"
  # (arrays do not cross xargs: the flags carry no spaces except the quoted defines, rebuilt below)
  if ! xargs -P "$jobs" -L 1 bash -c '
      kind="$0"; out="$U/$1"; src="$2"
      case "$kind" in
        C) "$CCU" $FTF_S -c -o "$out" "$src" ;;
        L) "$CCU" $LUF_S -c -o "$out" "$src" ;;
        X) "$CXXU" $RMF_S -c -o "$out" "$src" ;;
        Y) "$CXXU" $RMF_S $LUAI -include "$UIS/ui_lua51_compat.h" -c -o "$out" "$src" ;;
      esac || { echo "build.sh: compile failed: $src" >&2; exit 255; }' < "$list"; then
    echo "build.sh: the UI third-party objects did not build" >&2; exit 3
  fi
  echo "$stamp" > "$U/STAMP"
  echo "$U"
}
# The host's Lua binding as one object whose Lua symbols are all local: ui_lua.cpp + RmlUi's Lua plugin + the host's Lua copy, partially
# linked, then every C symbol starting "lua" made local, so they never meet the proxy's engine-patched Lua (src/ui_lua.h has the why).
# $1 core sources, $2 object folder of ui_objs, $3 output object, $4 compiler, $5 binutils prefix ("" on the host).
ui_lua_obj() {
  local S="$1" U="$2" O="$3" CXXU="$4" P="$5"
  "$CXXU" -std=c++17 -O2 -Wall -Wextra -Werror "${UI_DEFS[@]}" -isystem "$UI_SRC/rmlui/Include" -isystem "$UI_SRC/lua/src" -I"$S" \
    -ffile-prefix-map="$S/"=core/ -c -o "$O.part.o" "$S/ui_lua.cpp"
  "${P}ld" -r -o "$O.all.o" "$O.part.o" $(LC_ALL=C ls "$U"/rmllua/*.o "$U"/lua/*.o)
  "${P}objcopy" --wildcard --localize-symbol='_lua*' --localize-symbol='lua*' "$O.all.o" "$O"
  if "${P}nm" -g --defined-only "$O" | grep -E ' _?lua' >/dev/null; then echo "build.sh: Lua symbols left global in $O" >&2; exit 3; fi
  rm -f "$O.part.o" "$O.all.o"
}

build_dll() {
  local S="$1" A="$2" O="$3" L="$3.lua"; mkdir -p "$L"
  local CC="${CXX/g++/gcc}" SRCS=() n
  for n in $SOURCES; do [[ "$n" == ui_lua.cpp ]] || SRCS+=("$S/$n"); done   # ui_lua.cpp goes in through ui_lua_obj (its Lua made local)
  for c in $LUA_CORE; do
    "$CC" -std=gnu99 -O2 -w -ffile-prefix-map="$LUA_SRC/"=lua/ -c -o "$L/$c.o" "$LUA_SRC/$c.c"
  done
  local U; U="$(ui_objs "$CXX" "$CC" mingw32 "$S")"; [[ -f "$U/STAMP" ]] || exit 3
  ui_lua_obj "$S" "$U" "$L/ui_lua.o" "$CXX" "${CXX%%g++*}"
  # -win32 thread model (no winpthread DLL), static libgcc/libstdc++ (the DLL depends on system DLLs only), no PE timestamp and
  # relative file names (the same sources give the same bytes: the PC test binary is the CI binary). --disable-auto-image-base: mingw
  # ld otherwise hashes the OUTPUT PATH into the DLL's ImageBase, so the container, CI and a worktree gave three different DLLs for
  # one commit (review of J1, 2026-10-28). `build.sh repro` proves it stays fixed.
  "$CXX" -std=c++17 -O2 -s -shared -Wall -Wextra -Wshadow -Werror -DWSP_BUILD_ID="\"$BUILD_ID\"" -D_WIN32_WINNT=0x0601 -DUNICODE -D_UNICODE \
    -ffile-prefix-map="$S/"=core/ -ffile-prefix-map="$A/"=adapter/ -static-libgcc -static-libstdc++ -Wl,--no-insert-timestamp -Wl,--disable-auto-image-base -Wl,--enable-stdcall-fixup \
    -I"$S" -I"$LUA_SRC" "${UI_DEFS[@]}" -isystem "$UI_SRC/rmlui/Include" -isystem "$UI_SRC/stb" -o "$O" "${SRCS[@]}" "$A/adapter.cpp" \
    "$L"/*.o $(LC_ALL=C ls "$U"/rml/*.o "$U"/ft/*.o) "$S/d3d9.def" -ldbghelp -ladvapi32
}

python3 "$OWN/proxy/tools/gen_tables.py" --check
if [[ "$WHAT" == dll || "$WHAT" == all || "$WHAT" == repro ]]; then python3 "$OWN/proxy/tools/fetch_lua.py" --out "$ROOT/build/lua" >/dev/null; fi
if [[ "$WHAT" == dll || "$WHAT" == all || "$WHAT" == repro || "$WHAT" == tests ]]; then python3 "$OWN/proxy/tools/fetch_ui.py" --out "$UI_SRC" >/dev/null; fi

if [[ "$WHAT" == dll || "$WHAT" == all ]]; then
  CXX="$(command -v i686-w64-mingw32-g++-win32 || command -v i686-w64-mingw32-g++ || true)"
  [[ -n "$CXX" ]] || { echo "build.sh: no i686 mingw-w64 g++ (sudo apt-get install -y --no-install-recommends \$(python3 $TC apt), or build.sh --docker)"; exit 2; }
  toolchain_check "$CXX"
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
  summary "### proxy DLL: $ADAPTER" "" "- build id: \`$BUILD_ID\`" \
    "- \`d3d9.dll\` sha256 \`$(sha256sum "$OUT/$ADAPTER/d3d9.dll" | cut -c1-64)\`, $(wc -c < "$OUT/$ADAPTER/d3d9.dll" | tr -d ' ') bytes" "- $TOOLCHAIN_LINE"
fi

if [[ "$WHAT" == tests || "$WHAT" == all ]]; then
  fail=0
  # the tests include core headers, the adapter's generated tables and testkit.h by name, and read files through --src/--adapter/--tests
  for t in "$OWN"/proxy/tests/test_*.cpp; do
    n="$(basename "$t" .cpp)"
    MORE=()
    if grep -q '^// link: ui' "$t"; then   # the RmlUi host's document tests (J30): host RmlUi + FreeType + the localised ui_lua object
      HU="$(ui_objs g++ gcc host "$SRC")"; [[ -f "$HU/STAMP" ]] || exit 3
      [[ -f "$OUT/tests/ui_lua.o" ]] || ui_lua_obj "$SRC" "$HU" "$OUT/tests/ui_lua.o" g++ ""
      MORE=("${UI_DEFS[@]}" -isystem "$UI_SRC/rmlui/Include" "$OUT/tests/ui_lua.o" $(LC_ALL=C ls "$HU"/rml/*.o "$HU"/ft/*.o))
    fi
    g++ -std=c++17 -O1 -Wall -Wextra -Wshadow -Werror -I"$SRC" -I"$ADIR" -I"$OWN/proxy/tests" -o "$OUT/tests/$n" "$t" "${MORE[@]}"
    if WSP_UI_SRC="$UI_SRC" "$OUT/tests/$n" --src "$SRC" --adapter "$ADIR" --tests "$OWN/proxy/tests"; then :; else echo "build.sh: $n FAILED"; fail=1; fi
  done
  rm -f "$OUT/tests/ui_lua.o"
  [[ $fail == 0 ]] && echo "build.sh: host tests passed" || exit 1
fi

if [[ "$WHAT" == repro ]]; then
  # The same inputs must give the same bytes from any checkout path (container, CI runner, worktree, either layout): build again
  # from copies of the core sources and the adapter.
  [[ -f "$OUT/$ADAPTER/d3d9.dll" ]] || { echo "build.sh repro: build the dll first"; exit 2; }
  R="$(mktemp -d)/elsewhere_$RANDOM"; mkdir -p "$R"
  cp -a "$SRC" "$R/src"; cp -a "$ADIR" "$R/adapter"   # the build id was computed above
  CXX="$(command -v i686-w64-mingw32-g++-win32 || command -v i686-w64-mingw32-g++)"
  toolchain_check "$CXX"
  build_dll "$R/src" "$R/adapter" "$R/other.dll"
  if cmp -s "$OUT/$ADAPTER/d3d9.dll" "$R/other.dll"; then echo "build.sh repro: identical from another path"; rm -rf "$(dirname "$R")"; summary "- repro: identical from another path"
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
  #    W24 (C25): the second log line is the DLL's own file sha256, and it is the copied d3d9.dll's: sha256, bytes and the launch line's build
  SELF="$(sed -n 2p "$G/$MOD/logs/proxy.log" | grep -o 'self_hash: sha256 [0-9a-f]\{64\} bytes [0-9]* build [^ ]* (hashed in [0-9]* ms)' || true)"
  [[ -n "$SELF" ]] || { echo "build.sh smoke: line 2 of the log is not a self_hash line"; cat "$G/$MOD/logs/proxy.log"; exit 1; }
  read -r _ _ SH_HEX _ SH_BYTES _ SH_BUILD _ _ SH_MS _ <<< "$SELF"
  LAUNCH_BUILD="$(grep -o 'd3d9\.dll build [^ ]* loaded' "$G/$MOD/logs/proxy.log" | head -1 | cut -d' ' -f3)"
  DLL_HEX="$(sha256sum "$G/d3d9.dll" | cut -c1-64)"; DLL_BYTES="$(wc -c < "$G/d3d9.dll" | tr -d ' ')"
  if [[ "$SH_HEX" != "$DLL_HEX" || "$SH_BYTES" != "$DLL_BYTES" || "$SH_BUILD" != "$LAUNCH_BUILD" ]]; then
    echo "build.sh smoke: self_hash differs from d3d9.dll: log sha256 $SH_HEX bytes $SH_BYTES build $SH_BUILD; file sha256 $DLL_HEX bytes $DLL_BYTES; launch build $LAUNCH_BUILD"
    exit 1
  fi
  echo "build.sh smoke: self_hash matches d3d9.dll (sha256 $SH_HEX, $SH_BYTES bytes, build $SH_BUILD, hashed in $SH_MS ms under wine)"
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
  # 6) the gesture layer (W6) with the RmlUi host it rides on. W37: the build's own log says which path it is on, never the game's name:
  #    a GestureAdapter starts the layer ("gesture: on: drag 6 px"); a game without one logs the no-adapter line and the layer is inert.
  #    Anything else (a missing callback, a crash, no gesture line) fails.
  NOGEST_LINE="gesture: controls.gestures=1 but no adapter (the game has no GestureAdapter): the layer is inert"
  printf '[proxy]\r\nbackend=system\r\nexe_guard=0\r\n[controls]\r\ngestures=1\r\n[ui]\r\nenabled=1\r\n' > "$G/$INI"
  run; NOGEST=0
  if grep -qF "$NOGEST_LINE" "$G/$MOD/logs/proxy.log"; then NOGEST=1; echo "build.sh smoke: this game has no GestureAdapter: steps 6 and 7 check the inert path"
  else check "gesture: on: drag 6 px"; fi
  check "ui: enabled"; check "process detach"
  # 7) gestures without the host: inert, said so, nothing hooked for them (W2's "ui.enabled=0: nothing hooked" holds)
  printf '[proxy]\r\nbackend=system\r\nexe_guard=0\r\n[controls]\r\ngestures=1\r\n' > "$G/$INI"
  run; check "process detach"
  if [[ $NOGEST == 1 ]]; then   # no adapter: GestureInit returns at the no-adapter check, before it looks at the host
    grep -qF "$NOGEST_LINE" "$G/$MOD/logs/proxy.log" || { echo "build.sh smoke: the no-adapter gesture line is not in the log"; cat "$G/$MOD/logs/proxy.log"; exit 1; }
  else check "gesture: the RmlUi host is off (ui.enabled=0)"; fi
  if grep -q "IDirect3D9::CreateDevice (ui)" "$G/$MOD/logs/proxy.log"; then echo "build.sh smoke: a UI hook went in with ui.enabled=0"; exit 1; fi
  # 8) the control channel (W17): a request written before the launch is refused as stale and never run (an exit here would end the
  #    launch before the peek), and a peek on the first engine site of the game being built (W37: from its generated tables; the stand-in
  #    exe refuses every site) is refused with its reason. A game with no engine sites checks the stale request only.
  #    The host waits for the peek's answer; the peek is written only once the ctl thread logged, so after the process was created.
  SITE="$(sed -n '/kSites\[/,/^};/p' "$ADIR/generated/tables.h" | grep -m1 -o '^ *{ "[^"]*"' | cut -d'"' -f2 || true)"
  if [[ -n "$SITE" ]]; then WAITFOR='ctl\peek1.done'; else WAITFOR='ctl\old1.done'; echo "build.sh smoke: this game has no engine sites: step 8 checks the stale request only"; fi
  mkdir -p "$G/ctl"; printf 'exit\n' > "$G/ctl/old1.cmd"; touch -d '2020-01-02 03:04:05 UTC' "$G/ctl/old1.cmd"
  printf '[proxy]\r\nbackend=system\r\nexe_guard=0\r\n[dev]\r\nctl=1\r\nctl_dir=ctl\r\nstate_json=1\r\n' > "$G/$INI"
  run wait "$WAITFOR" > "$OUT/smoke/ctl_run.txt" 2>&1 &
  RUN=$!
  for _ in $(seq 1 300); do grep -q "ctl: watching" "$G/$MOD/logs/proxy.log" 2>/dev/null && break; sleep 0.2; done
  if [[ -n "$SITE" ]]; then printf 'peek %s * 4\n' "$SITE" > "$G/ctl/peek1.tmp"; mv "$G/ctl/peek1.tmp" "$G/ctl/peek1.cmd"; fi
  wait "$RUN" || { echo "build.sh smoke: the ctl launch failed"; cat "$OUT/smoke/ctl_run.txt"; cat "$G/$MOD/logs/proxy.log"; exit 1; }
  check "ctl: old1: refused: stale: written 2020-01-02T03:04:05.000Z, before this launch started"
  if [[ -n "$SITE" ]]; then check "ctl: peek1: refused: sites not accepted by the patch engine"; fi
  if grep -q "exit requested" "$G/$MOD/logs/proxy.log"; then echo "build.sh smoke: the stale exit request ran"; exit 1; fi
  grep -q '"status": "refused", "reason": "stale: written' "$G/ctl/old1.done" || { echo "build.sh smoke: old1.done is not a stale refusal"; cat "$G/ctl/old1.done"; exit 1; }
  [[ -z "$SITE" ]] || grep -q '"status": "refused", "reason": "sites not accepted by the patch engine' "$G/ctl/peek1.done" || { echo "build.sh smoke: peek1.done is not the sites refusal"; cat "$G/ctl/peek1.done"; exit 1; }
  #    W33 (C28): no dev thread starts in DllMain: both start after the first Direct3DCreate9, and the ctl thread watches after its start line
  at() { grep -n -m1 -F "$1" "$G/$MOD/logs/proxy.log" | cut -d: -f1; }
  CREATE="$(at 'Direct3DCreate9(sdk=32)')"; T_STATE="$(at 'thread: dev.state started')"; T_CTL="$(at 'thread: dev.ctl started')"; WATCH="$(at 'ctl: watching')"
  if [[ -z "$CREATE" || -z "$T_STATE" || -z "$T_CTL" || -z "$WATCH" ]] || (( T_STATE < CREATE || T_CTL < CREATE || WATCH < T_CTL )); then
    echo "build.sh smoke: thread order: Direct3DCreate9 line ${CREATE:-none}, dev.state ${T_STATE:-none}, dev.ctl ${T_CTL:-none}, ctl: watching ${WATCH:-none}"
    cat "$G/$MOD/logs/proxy.log"; exit 1
  fi
  check "threads at the first Direct3DCreate9: state=1 ctl=1"
  nothread() { if grep -q "thread: " "$G/$MOD/logs/proxy.log"; then echo "build.sh smoke: $1: a proxy thread started"; cat "$G/$MOD/logs/proxy.log"; exit 1; fi; }
  # 9) proxy.file_rules (W33): the release file rules with every dev key off: the rules load, no dev side, no thread; the host opens the
  #    redirected path through its own import table and must read the target's text
  rm -rf "$G/ctl"; mkdir -p "$G/data"
  printf 'vanilla\r\n' > "$G/data/smoke_in.txt"; printf 'redirected by proxy.file_rules\r\n' > "$G/$MOD/smoke_out.txt"
  printf 'redirect data\\smoke_in.txt -> %s\\smoke_out.txt\r\n' "$MOD" > "$G/rules.txt"
  printf '[proxy]\r\nbackend=system\r\nexe_guard=0\r\nfile_rules=rules.txt\r\n' > "$G/$INI"
  run open 'data\smoke_in.txt' > "$OUT/smoke/open_run.txt" 2>&1 || { echo "build.sh smoke: the proxy.file_rules launch failed"; cat "$OUT/smoke/open_run.txt"; exit 1; }
  check "redirect: 1 rules from"; check "(proxy.file_rules)"; check "proxy.file_rules line 1"; check "process detach"
  if grep -q "dev: timeline=" "$G/$MOD/logs/proxy.log"; then echo "build.sh smoke: proxy.file_rules turned the dev side on"; exit 1; fi
  nothread "proxy.file_rules alone"
  grep -q "smoke: open data.smoke_in.txt: redirected by proxy.file_rules" "$OUT/smoke/open_run.txt" || { echo "build.sh smoke: the redirect did not serve smoke_out.txt"; cat "$OUT/smoke/open_run.txt"; cat "$G/$MOD/logs/proxy.log"; exit 1; }
  # 10) dev keys that need no thread (a hook and a rule file): the dev side on, no thread, a clean FreeLibrary with no proxy thread in the DLL
  printf '[proxy]\r\nbackend=system\r\nexe_guard=0\r\n[dev]\r\nskip_intro=1\r\nfile_rules=rules.txt\r\n' > "$G/$INI"
  run; check "threads at the first Direct3DCreate9: state=0 ctl=0"; check "process detach (FreeLibrary)"
  nothread "skip_intro and dev.file_rules"
  echo "build.sh smoke: passed (10 launches under wine, 2 dumps)"
  summary "- smoke: self_hash in proxy.log matches d3d9.dll ($SH_MS ms under wine)"
fi

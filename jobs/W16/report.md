# W16 report: The null game builds and tests on its own

The null game now builds and tests on its own, and a game's own C++ host tests have a place to live (B15, B16, B52). `build.sh tests` compiles a game's `proxy/tests/test_*.cpp` (`[proxy] tests`, `layout.py proxy-tests`) after the core's. The first consumer's console and camera numbers have left the core's `test_console.cpp` and `test_camera.cpp`, and a test-side `proxy/tests/adapter_checks.h` holds the console and camera contract instead, which now runs in core CI on synthetic site tables. `build_id.py` hashes a game root that sits inside its repository, so the null game's DLL carries a real build id in CI (`WSP_BUILD_ID: nullgame-ci` is gone), and `build.sh --docker` mounts the outer of the two roots. The UI pin file has a schema (`schemas/ui_pins.schema.json`), which `fetch_ui.py` checks before it fetches anything (`--check` runs the check on its own), and the null game's pin file now names only core things. No `proxy/src` file changed. VERSION 0.32.0.

Written by the orchestrating session (same session id as the builder) from the PR #88 description, which is the builder's full report text; the harness refused the builder's own write of this file.

## What was built
- **Game host tests (B15, decisions 1, 2, 4):** `layout.py` `proxy_tests(game)` and `layout.py proxy-tests`. It returns `[proxy] tests` when that is set, else `<game>/proxy/tests` when the folder holds a `test_*.cpp`, else none. `$WSP_PROXY_TESTS` overrides both. It refuses a folder inside the adapter folder (a build-id input) and the core's own `proxy/tests` with a `LayoutError` that gives the reason. `warscape/repo.py` `DEFAULTS` gains `[proxy] tests = ''`. `build.sh tests` runs one `host_test` for both sets: the core's tests first, then the game's in `LC_ALL=C` sort order, with the same flags, `-I<game tests>` added, the same run arguments and `// link: ui` support. It prints `build.sh: core|game test <name>` and ends with `host tests passed (N core, M game)`. Game binaries go under `build/proxy/tests/game/`. A failing game test fails the target, and a game with no folder skips the step silently. `proxy/tests/null_game/proxy/tests/test_null_adapter.cpp` checks that the null adapter has no console and no camera, runs both checkers if one appears, and checks that `identity.json` names `Game.exe`, `nullgame` and `nullgame.ini` (the smoke's files) and that the ini exists.
- **The contract (decision 3):** `proxy/tests/adapter_checks.h` (`wsp::adck`) holds `ConsoleAdapterProblems` and `CameraAdapterProblems`, which take a `SiteLookup` and return a list of problems, and the helpers `FindSite`, `TableLookup` and `StockDword`. The console checks: the 8 sites exist, are `kHook` rows and are keyed by `dev.console`. The slot, owner, selection-vtable, CLI-vtable and gate operands lie inside their sites' stock bytes. The slot call at `+2` reads the same dword as the slot test. The four struct offsets and `executeSlot` are not negative, `cliCtxOff + 4 <= cliSize`, and `cliSize <= 0x80` (the CLI buffer). The camera checks: the 3 sites exist, are `kHook` rows and are keyed by `dev.camera`. The global, battle, controller and mode operands lie inside their stock bytes, `setSlot >= 0`, and `targetDistance` is finite and above 0. A source lint keeps the two mirrored console.cpp numbers (`Operand(s_ad->slotCallSite, 2)`, `s_cliBuf[8][0x80]`) in step with the header. `test_console.cpp` and `test_camera.cpp` drop their `if (Adapter().console)` / `if (Adapter().camera)` blocks and gain synthetic cases: one passing table, then 16 failing console cases and 11 failing camera cases, one per rule. The gate-byte source lint used to sit inside the console `if` block. It reads only `core/console.cpp`, so it now runs with the other source lints. The pure parser and refusal cases use neutral command names in place of the consumer's.
- **Nested build id (B16, decision 6):** `build_id.locate` reads `git rev-parse --show-prefix` and looks up the game roles (`GAME_ROLES = ('adapter', 'ui_pins')`) as `<rev>:<prefix><path>`. The core roles are still found at the top. The `-dirty` diff uses `:(top)<path>` pathspecs, so a nested root sees changes to both kinds of input. Flat and submodule layouts keep their ids (their prefix is empty).
- **Docker (decision 5):** `build.sh --docker` mounts the game root when it contains the core, and the core when it contains the game root (in that case with `WSP_GAME_ROOT=/src/<rel>`). When neither contains the other it refuses with exit 2 and names both paths. The game tests go in as `WSP_PROXY_TESTS=/src/<rel>`, and tests outside the mount are refused.
- **CI (decision 7):** `WSP_BUILD_ID: nullgame-ci` and its comment are gone from `ci/gates.yml.in` and from the rendered `gates.yml`.
- **Pin schema (B52, decisions 8, 9):** `schemas/ui_pins.schema.json` is written in the subset and passes the `schemas` gate. Its shape: git pins need `version`, an https `repo` and a 40-hex lower-case `commit`, with optional `tag`, `licence` and `why`. `lua` needs `version`, an https `url`, a 64-hex `sha256` and `licence`, with an optional `why`. The stb entries need `version`, `url` and `sha256`, with optional `commit`, `licence` and `why`. `_doc` is a string, and any other key must hold an object. `fetch_ui.py` validates with `warscape.schema.validate` (the core root goes on `sys.path` from its own file) and exits naming every problem before any fetch. A missing pin still gets the `missing_pin` text. `--check [--pins FILE]` validates only. The null game's `pins.json` loses `emsdk_image`, and its `_doc` and `why` texts name only core files. The five source pins are byte-for-byte unchanged.
- **Docs and rows:** `docs/PROXY_HARNESS.md`, `docs/CONSUMING.md` (the 0.32.0 notes), `docs/PROXY_UI.md`, `README.md`, the null game's `README.md`, and B15, B16 and B52 removed from `docs/BACKLOG.md`. The tool rows for `build.sh`, `build_id.py`, `layout.py` and `fetch_ui.py` are refreshed with their ids kept. `tests/test_schema.py` now expects 10 schemas. `tests/test_netfetch.py` `Fetchers` patches `fetch_ui.validate`, because its offline `file://` stand-ins cannot pass the https-only schema (the schema is tested in `UiPins`).

### Checks moved to the consumer (one per line, against the deleted lines)
Console (the deleted `if (Adapter().console)` block in `test_console.cpp`):
1. `slotSite` stock[0..1] == `83 3d`
2. `ownerSite` stock[0..1] == `8b 0d`
3. dword `ownerSite` +13 == `ownerCampaignOff` (`0x9fc`)
4. dword `wiringSite` +2 == `ownerSelectionOff` (`0xf4`)
5. `wiringSite` stock[6..7] == `c7 01`
6. dword `wiringSite` +14 == `ownerCampaignOff`
7. `wiringSite` stock[30] == `campaignSelectionOff`
8. `ctorTailSite` stock[8] == `cliCtxOff`
9. `ctorTailSite` stock[11..12] == `c7 06`
10. `ctorTailSite` stock[21..22] == `c2 04`
11. `gateSite` stock[0] == `0x80`, stock[`gateOperand`] == `0x54`, stock[3] == `0x00`
12. `noOps` holds `all_end_turn`, `give_trait`, `selected_cqi`
13. `noOps` lacks `teleport_to`, `transport_to_region`, `create_army`
14. `systemNames` holds `here_kitty_kitty` and `quit`, and lacks `teleport_to`

Stayed in the core (now in `ConsoleAdapterProblems`): each site exists, is a `kHook` row and is keyed by `dev.console`; dword `slotCallSite` +2 == the slot; `cliCtxOff + 4 <= cliSize`. The gate-byte source lint also stays.

Camera (the deleted `if (Adapter().camera)` block in `test_camera.cpp`):
1. `chainSite` stock[0] == `0xa1`
2. `globalOperand == 1`
3. `chainSite` stock[8..9] == `8b 80`
4. dword `chainSite` +`battleOffOperand` == `0xf8`
5. `chainSite` stock[14..15] == `8b 80`
6. dword `chainSite` +`controllerOffOperand` == `0x281b8`
7. `modeSite` stock[0..1] == `8b 8e`
8. dword `modeSite` +`modeOffOperand` == `0x800`
9. dword `modeSite` +18 == `0xc0`
10. `setSlot * 4 == 0xbc`
11. `setSite` stock[0..2] == `83 ec 08`
12. `setSite` anchorLen == 4, anchor[0] == anchor[3] == `0xcc`

Stayed in the core (now in `CameraAdapterProblems`): each site exists, is a `kHook` row and is keyed by `dev.camera`; `targetDistance > 0`. No check hit the kill criterion. A grep of `test_console.cpp` and `test_camera.cpp` for `0x9fc 0xf4 0x281b8 0x800 0xf8 0xbc 0xc0 all_end_turn give_trait selected_cqi transport_to_region create_army here_kitty "quit"` finds nothing. `teleport_to` and `declare_war` remain as example lines in the pure parser cases.

## Evidence
- **Red first:** at `52acb29`, `python3 -m unittest tests.test_moved_tools` gave `Ran 29 tests ... FAILED (failures=3, errors=6)`. All 9 were the new cases. The lua-pin case passed from the start, because it guards a claim that was already true. The C++ red commit never got a CI verdict: its run 41881419447 was cancelled when the next push started a new one.
- **Green:** `tests.test_moved_tools` gives `Ran 29 tests ... OK`. In CI run **41882301016** (`979e2db`), `proxy` passed in 10m55s on the first attempt, and so did `harness-windows`. `gates` failed there on `test_schema` (count 9) and `test_netfetch` (`file://` pins); both are fixed in `d1a1ff1`. The final run is on this PR.
- **Proxy job log, run 41882301016** (no `WSP_BUILD_ID`): `d3d9.dll build 2d97737f1b60 sha256 c8085b0c...`, `build.sh: game test test_null_adapter`, `test_null_adapter: 5 passed, 0 failed`, `test_console: 77 passed, 0 failed`, `test_camera: 29 passed, 0 failed`, `build.sh: host tests passed (16 core, 1 game)`, `repro: identical from another path`, `self_hash matches d3d9.dll (... 4406784 bytes, build 2d97737f1b60 ...)`.
- **The local id equals CI's DLL id:** `WSP_GAME_ROOT=proxy/tests/null_game python3 proxy/tools/build_id.py --rev 979e2db --no-dirty` printed `2d97737f1b60`. `WSP_GAME_ROOT=proxy/tests/null_game bash proxy/tools/build.sh id` printed `e3eab3ef11d2` at `a9c4568` (a real id: no `nogit`, no `-dirty`, no error).
- **The DLL is unchanged beyond its id:** `git diff --stat origin/main -- proxy/src` is empty, and the compile line, `build_dll`, the adapter and the five source pins are unchanged. Main's CI DLL (run 41857256437, id `nullgame-ci`) is 4406784 bytes, and so is the branch's. A byte compare with `WSP_BUILD_ID=x` was not run (no mingw and no Docker here).
- **Gates:** full `python3 wsc.py gates`, `gates --fast` and `python3 wsc.py policy --branch job/W16 --base origin/main` pass locally.

## Rehearsal
Not run. `docker info` gets no answer and there is no `g++` or mingw on this PC. The kill criterion says not to start Docker or install packages. The two files below are the deleted checks moved verbatim onto `adck::FindSite` / `adck::StockDword`. They have not been compiled against napoleon's adapter.

## Consumer test files
`proxy/tests/test_console_adapter.cpp`:

```cpp
// test_console_adapter.cpp - this game's campaign console numbers against its engine_sites rows (moved out of the core's
// proxy/tests/test_console.cpp by core W16): the core's contract checker first (adapter_checks.h: sites, hook rows, dev.console, operands
// inside the stock bytes, one slot, cliCtxOff and cliSize), then the opcodes, offsets and command names only this game's exe has.
// A game test (core/proxy/tools/layout.py proxy-tests): built and run by core/proxy/tools/build.sh tests after the core's tests.
#include "testkit.h"
#include "adapter_checks.h"
#include "adapter.cpp"

using namespace wsp;

static const SiteDef* Site(const char* id) { return adck::FindSite(Adapter().sites, Adapter().nSites, id); }
static uint32_t StockDword(const char* id, int off) { uint32_t v = 0; return adck::StockDword(Site(id), off, v) ? v : 0xffffffffu; }

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    CHECK(Adapter().console != nullptr);
    if (!Adapter().console) return tk::Done("test_console_adapter");
    const ConsoleAdapter& c = *Adapter().console;
    const std::vector<std::string> problems = adck::ConsoleAdapterProblems(c, adck::TableLookup(Adapter().sites, Adapter().nSites));
    for (const std::string& p : problems) printf("    %s\n", p.c_str());
    CHECK(problems.empty());
    if (!problems.empty()) return tk::Done("test_console_adapter");   // a missing site: the byte checks below would read nothing
    CHECK(Site(c.slotSite)->stock[0] == 0x83 && Site(c.slotSite)->stock[1] == 0x3d);              // cmp dword [imm32], imm8
    CHECK(Site(c.ownerSite)->stock[0] == 0x8b && Site(c.ownerSite)->stock[1] == 0x0d);            // mov ecx, [imm32]
    CHECK(StockDword(c.ownerSite, 13) == (uint32_t)c.ownerCampaignOff);                          // mov ecx, [ecx + 0x9fc]
    CHECK(StockDword(c.wiringSite, 2) == (uint32_t)c.ownerSelectionOff);                         // lea ecx, [ebx + 0xf4]
    CHECK(Site(c.wiringSite)->stock[6] == 0xc7 && Site(c.wiringSite)->stock[7] == 0x01);          // mov [ecx], imm32
    CHECK(StockDword(c.wiringSite, 12 + 2) == (uint32_t)c.ownerCampaignOff);                     // lea edi, [ebx + 0x9fc]
    CHECK(Site(c.wiringSite)->stock[30] == (uint8_t)c.campaignSelectionOff);                     // mov [eax + 0x28], ecx
    CHECK(Site(c.ctorTailSite)->stock[8] == (uint8_t)c.cliCtxOff);                               // mov [esi + 0x28], eax
    CHECK(Site(c.ctorTailSite)->stock[11] == 0xc7 && Site(c.ctorTailSite)->stock[12] == 0x06);    // mov [esi], imm32
    CHECK(Site(c.ctorTailSite)->stock[21] == 0xc2 && Site(c.ctorTailSite)->stock[22] == 0x04);    // ret 4: thiscall(void** ctx)
    CHECK(Site(c.gateSite)->stock[0] == 0x80 && Site(c.gateSite)->stock[c.gateOperand] == 0x54 && Site(c.gateSite)->stock[3] == 0x00);   // cmp byte [r + 0x54], 0
    // the no-op table: refuses what retail compiled out, never a command that acts
    CHECK(ConsoleInList(c.noOps, "all_end_turn") && ConsoleInList(c.noOps, "give_trait") && ConsoleInList(c.noOps, "selected_cqi"));
    CHECK(!ConsoleInList(c.noOps, "teleport_to") && !ConsoleInList(c.noOps, "transport_to_region") && !ConsoleInList(c.noOps, "create_army"));
    CHECK(ConsoleInList(c.systemNames, "here_kitty_kitty") && ConsoleInList(c.systemNames, "quit") && !ConsoleInList(c.systemNames, "teleport_to"));
    return tk::Done("test_console_adapter");
}
```

`proxy/tests/test_camera_adapter.cpp`:

```cpp
// test_camera_adapter.cpp - this game's battle camera numbers against its engine_sites rows (moved out of the core's
// proxy/tests/test_camera.cpp by core W16): the core's contract checker first (adapter_checks.h: sites, hook rows, dev.camera, operands
// inside the stock bytes, setSlot, targetDistance), then the opcodes and offsets only this game's exe has.
// A game test (core/proxy/tools/layout.py proxy-tests): built and run by core/proxy/tools/build.sh tests after the core's tests.
#include "testkit.h"
#include "adapter_checks.h"
#include "adapter.cpp"

using namespace wsp;

static const SiteDef* Site(const char* id) { return adck::FindSite(Adapter().sites, Adapter().nSites, id); }
static uint32_t StockDword(const char* id, int off) { uint32_t v = 0; return adck::StockDword(Site(id), off, v) ? v : 0xffffffffu; }

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    CHECK(Adapter().camera != nullptr);
    if (!Adapter().camera) return tk::Done("test_camera_adapter");
    const CameraAdapter& c = *Adapter().camera;
    const std::vector<std::string> problems = adck::CameraAdapterProblems(c, adck::TableLookup(Adapter().sites, Adapter().nSites));
    for (const std::string& p : problems) printf("    %s\n", p.c_str());
    CHECK(problems.empty());
    if (!problems.empty()) return tk::Done("test_camera_adapter");   // a missing site: the byte checks below would read nothing
    CHECK(Site(c.chainSite)->stock[0] == 0xa1);                                                   // mov eax, [imm32]: the owner global
    CHECK(c.globalOperand == 1);
    CHECK(Site(c.chainSite)->stock[8] == 0x8b && Site(c.chainSite)->stock[9] == 0x80);            // mov eax, [eax + imm32]
    CHECK(StockDword(c.chainSite, c.battleOffOperand) == 0xf8);
    CHECK(Site(c.chainSite)->stock[14] == 0x8b && Site(c.chainSite)->stock[15] == 0x80);          // mov eax, [eax + imm32]
    CHECK(StockDword(c.chainSite, c.controllerOffOperand) == 0x281b8);
    CHECK(Site(c.modeSite)->stock[0] == 0x8b && Site(c.modeSite)->stock[1] == 0x8e);              // mov ecx, [esi + imm32]
    CHECK(StockDword(c.modeSite, c.modeOffOperand) == 0x800);
    CHECK(StockDword(c.modeSite, 18) == 0xc0);                                                    // ... call [eax + 0xc0]: a mode method
    CHECK(c.setSlot * 4 == 0xbc);
    const SiteDef* s = Site(c.setSite);
    CHECK(s->stock[0] == 0x83 && s->stock[1] == 0xec && s->stock[2] == 0x08);                     // sub esp, 8: the function entry
    CHECK(s->anchorLen == 4 && s->anchor[0] == 0xcc && s->anchor[3] == 0xcc);                      // int3 padding before it
    return tk::Done("test_camera_adapter");
}
```

## What napoleon must do (after the tag)
1. Add the two files above to its `proxy/tests/`; `core/proxy/tools/build.sh tests` must list them as game tests and pass.
2. Run `python3 core/proxy/tools/fetch_ui.py --check` on `viewer/pins.json`: it needs `stb_image_write` (required since 0.10.0); `emsdk_image` stays.
3. Rule 79: three DLL-input roles changed (`build_sh`, `build_id`, `fetch_ui`), so it needs 20 passes on the new build id, combined with the pin bump's other passes.
4. Optional: add `proxy/tests/` to `acc_exempt`.
5. `--docker` works as before. The bump also follows the 0.10.0 to 0.31.0 notes in `docs/CONSUMING.md`.

## Deviations from the brief and why
- **No local C++ build and no rehearsal:** this PC has no Docker and no compiler, so CI's `proxy` job is the proof, as the brief allows. The byte compare is replaced by the same size on main and on the branch plus the unchanged compile line and sources.
- **The docs went to `docs/PROXY_HARNESS.md`:** CONSUMING's proxy section moved there on 2026-11-04 (the 30 KB cap). CONSUMING gets only the short 0.32.0 notes (29.5 KB).
- **Version 0.32.0:** `origin/main` is at 0.30.0, and `job/W15` claims 0.31.0.
- **Extra core checks** against the adapter's fields or console.cpp's own numbers: `cliSize <= 0x80` (with a source lint), offsets and slots not negative, `targetDistance` finite, and the gate and vtable operands inside the stock bytes.
- **Two tests outside the brief's list changed:** `tests/test_schema.py` (the count) and `tests/test_netfetch.py` (its offline pins). Both are needed for the gates to pass.
- **Four consumer command names in the pure console cases are renamed**, so that the acceptance grep finds none. `null_game_no_gesture/viewer/pins.json` is untouched: it is out of scope and passes the schema.
- **The report is not committed** (see the top of this description).

## Open questions
1. The consumer files have not been compiled against napoleon's adapter. If one of napoleon's operands (`ownerOperand`, `selectionVtblOperand`, `cliVtblOperand`) lies beyond its row's `stock` bytes, the new core check will report it, which the old tests never did. The fix is then the row's `len`, not the checker.
2. Should the null game get a synthetic console or camera so the real path also runs in CI? I left it out because it changes the null game's DLL.

🤖 Generated with [Claude Code](https://claude.com/claude-code)


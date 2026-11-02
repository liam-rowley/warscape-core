# W2: The RmlUi host in the proxy (napoleon J30's core half)

Model: Opus, reason: DLL work in a 32-bit process across the D3D9 device, DXVK and the input path, and a second Lua beside the engine's (as the
consumer's J30 brief). Budget about 150 tool calls for the remainder (the build ran under napoleon-remastered J30, `jobs/J30/brief.md` there).

## What
The game-agnostic half of napoleon-remastered J30 (its brief is the full specification; read it on that repo's `main`): RmlUi 6.3 inside the
proxy DLL, off unless a game sets `ui.enabled`.
- `proxy/src/ui_*`: the pure decisions (`ui_core.h`: the D19 scale model, input routing, the device lifecycle, the `ui` ctl grammar), the host
  (`ui_host.cpp`: device and window hooks, the frame pass, input routing glue, the lossless PNG dump), the render interface ported from
  empire-remastered (`ui_render_d3d9.*`), the RmlUi-side helpers (`ui_rml.h`), and the host's own Lua (`ui_lua.*`, symbols made local).
- `ctl ui show|hide|reload|scale|click|wheel|dump|state` (devcore.h, dev.cpp); keys `ui.enabled`, `ui.scale`, `ui.dir`, `ui.show`,
  `ui.dump_dir` (the null game's rows).
- Build: `proxy/tools/fetch_ui.py` (one fetcher, the game's one pin file through `layout.py ui-pins`), RmlUi and FreeType compiled into the DLL
  with system-only imports and a byte-identical `repro`, `build_id.py` covering the fetcher and the pin file, `pc_deploy.py kit_ui`.
- `VtableHook` never installs a detour already in a slot's chain (a battle loader's helper device shares the main device's vtable).
- Host tests `test_ui_core.cpp`, `test_ui_rml.cpp`; `docs/PROXY_UI.md`; `VERSION` 0.10.0.
The PC evidence is the consumer's: napoleon-remastered `proxy/runs/20261102_j30pc/` on `job/J30`.

## Kill criteria
- The null game's `build.sh all`, `repro` or `smoke` fails in CI for a cause in the host after 3 attempts: stop and report.
- A change the review asks for alters the DLL inputs after the consumer's 20-pass run: say so; the consumer re-runs on the new build id.

## Finish
Report in `jobs/W2/report.md` (what was built, deviations, open questions), then `wsc reg set jobs W2 status=review report=jobs/W2/report.md` (`python3 wsc.py`).

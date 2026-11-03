# The proxy's RmlUi host (J30)

RmlUi 6.3 inside the proxy DLL: a D3D9 render interface (DXVK and system d3d9), FreeType fonts, RmlUi's own Lua bindings on the host's
own Lua state, input routing and the scale model. A game turns it on with `ui.enabled`; screens and the panel host come later (the
first consumer's J35). Sources: `proxy/src/ui_*`. Host tests: `proxy/tests/test_ui_core.cpp` (pure), `test_ui_rml.cpp` (RmlUi on a
null render interface, the host's Lua).

## Keys (rows in the game's config_keys registry; a game without them runs with the UI off)
| key | meaning |
|---|---|
| `ui.enabled` | 0 (default, release): nothing is hooked, loaded or allocated; `UiInit` returns after reading the key (source lint). |
| `ui.scale` | 85-125 in steps of 5, default 100; out of range or off the grid is clamped and logged. |
| `ui.dir` | the UI folder, relative to the game folder: documents and `fonts/*.ttf` (every TTF there is loaded). |
| `ui.show` | dev: a document under `ui.dir` shown once the main device is ready. |
| `ui.dump_dir` | where `ctl ui dump` writes PNGs (outside the game folder, so uninstall stays byte-exact). |

## How it hangs together
- **Device.** `IDirect3D9::CreateDevice` [16] is hooked (chained like the headless and dev hooks). The UI attaches to the main device
  only (`UiIsMainDevice`: a top-level window and a back buffer of at least 640x480; a loader's tiny helper device is ignored), hooks its
  `Reset` [16] and `Present` [17] and subclasses its window (`SetWindowLong`, not a detour). `UiLifecycle` (pure, host-tested) decides:
  Reset releases the render interface's default-pool resources (layers, post buffers, its own D24S8 stencil) and rebuilds them lazily;
  a new main device shuts RmlUi down and starts it again on the new one, re-showing the documents that were visible.
- **Frame.** In the Present hook, before the real Present: `Context::Update`, then `BeginScene`, render, `EndScene`, inside a full
  state block (`D3DSBT_ALL`) with the render target and depth surface saved and restored. Nothing is done when no document is visible.
- **Shaders.** HLSL compiled at start through `d3dcompiler_47.dll` (then `_43`) loaded at run time (no import). No compiler: the host logs
  "UI off" and the lifecycle goes `Off`; the game runs on.
- **Text and art.** The context's dp ratio is the scale model's, so FreeType rasterises at the final pixel size. Loaded images (PNG, JPEG,
  TGA through stb_image) get a full premultiplied mip chain and trilinear sampling; font atlases and generated textures do not.
- **Input.** `UiDecide` (pure, host-tested) routes each event: the pointer is RmlUi's only over an interactive element
  (`Context::IsMouseInteracting`), a press that began on the engine stays the engine's until every button is up, the wheel goes to RmlUi
  only over a scrollable element, keys only while a text field has focus. The DirectInput mouse and keyboard devices are hooked
  (`IDirectInput8::CreateDevice` [3] from the exe's `DirectInput8Create` import, then `GetDeviceState` [9] and `GetDeviceData` [10]): their
  buttons, wheel or keys are blanked while RmlUi owns them; movement always passes. With no document visible everything goes to the engine.
- **Lua.** The host does not use the proxy's engine-patched Lua (its tables need the engine's dummynode, its collector never runs). It links
  a second Lua 5.1.1 (float numbers only, the review viewer's) with RmlUi's Lua plugin into one object whose `lua*` symbols are all made
  local (`build.sh`: `ld -r`, `objcopy --localize-symbol`, then a check that none is left global). A document with no script needs no Lua.
- **Threads.** Every RmlUi call is under one lock. The ctl thread never calls RmlUi or the device: `show`, `hide`, `reload`, `scale` and
  `dump` run at the next Present; `click` and `wheel` send window messages, so they take the route real input takes.

## `ctl ui` (dev.ctl)
`ui show|hide|reload <doc>`, `ui scale <percent>`, `ui click <x> <y> [left|right|middle] [down|up|move]`, `ui wheel <x> <y> <notches>`,
`ui dump <name> [x y w h]` (lossless PNG of the back buffer after the UI drew, through a plain render target, so a multisampled back buffer
works), `ui state [seconds]` (life, device, back buffer, dp ratio, documents, hovered element, scrolled elements, routing counters per
event type, which input paths carried clicks, Lua, and frame cost p50/p99/max of update, render and the whole hook over the window).

## Build
`proxy/tools/fetch_ui.py` fetches RmlUi, FreeType, Lua and stb by the game's pin file (`layout.py ui-pins`: `[proxy] ui_pins`, else
`viewer/pins.json`). `build.sh` compiles RmlUi Core with its FreeType font engine and FreeType (TrueType modules only, no zlib) into the
DLL, cached per compiler under `build/ui/obj/<tag>` (a stamp of the pins, the compat header, the compiler and the flags). The DLL's imports
stay system-only and `repro` stays byte-identical. Loose UI files reach the game through the harness adapter's `kit_ui` list
(`pc_deploy.py kit`, sha-checked install, byte-exact uninstall).

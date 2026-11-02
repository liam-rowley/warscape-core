#pragma once
// ui_host.h - the RmlUi host's entry points for the rest of the proxy (napoleon J30). No RmlUi, Lua or D3D types here.
// Keys (config_keys rows in the game, all off in release): ui.enabled (0: nothing is hooked, loaded or allocated), ui.scale (85-125,
// default 100), ui.dir (the UI folder, relative to the game folder), ui.show (dev: a document shown once the device is ready),
// ui.dump_dir (where `ctl ui dump` writes PNGs, outside the game folder).
#include <string>

namespace wsp {

void UiInit();                          // DllMain, after the dev side (reads the keys; with ui.enabled=0 returns at once)
void UiOnDirect3DCreate(void* d3d);     // the Direct3DCreate9 export: hooks IDirect3D9::CreateDevice when the UI is on
bool UiEnabled();
// The `ui` control verb (dev.cpp Execute; grammar in ui_core.h ParseUiArgs). Fills `result` with JSON members (no braces) or `why`.
bool UiCtl(const std::string& arg, double timeoutS, std::string& result, std::string& why);

} // namespace wsp

#pragma once
// gesture_host.h - the gesture layer's entry points (W6) for the rest of the proxy. The layer has no hook of its own: it is a stage in the
// RmlUi host's window subclass and Present chain (ui_host.cpp: RmlUi panels first, then gestures, then the game), so it needs
// ui.enabled=1 as well as controls.gestures=1 (with ui.enabled=0 the host hooks nothing, W2's rule, and the layer is inert).
// Pure decisions in gesture_*.h (host-tested); the driver is gesture.cpp; contract in docs/PROXY_GESTURES.md.
#include <cstdint>
#include <string>

namespace wsp {

void GestureInit();     // DllMain, after the dev side and before UiInit: reads controls.gestures, checks the adapter
bool GestureOn();       // the key is on, the adapter has gestures and the plan allows D3D hooks
void GestureSetWindow(void* hwnd);   // the subclassed game window (ui_host.cpp Subclass)

// One window message, on the window thread. mouseToEngine: the RmlUi stage gave this mouse message to the engine. The caller passes the
// message on (with `wp`, the left-button flag cleared for kPassNoButton), swallows it, or replays a plain click at (rx, ry) instead.
struct GestureMsgResult { int action = 0; bool replay = false; int rx = 0, ry = 0; uint32_t wp = 0; };   // action: gest::Action
GestureMsgResult GestureMessage(void* hwnd, uint32_t msg, uint32_t wp, intptr_t lp, bool mouseToEngine);
void GesturePresent(void* device, int bbW, int bbH);   // Present, before the RmlUi pass: the release's orders, then the preview
bool GestureOwnsMouse();                               // a gesture holds the mouse buttons (DirectInput buttons blanked meanwhile)

// The `gesture` control verb (dev.cpp; grammar in gesture_feed.h ParseGestureArgs). Fills `result` with JSON members or `why`.
bool GestureCtl(const std::string& arg, double timeoutS, std::string& result, std::string& why, bool& refused);

} // namespace wsp

#pragma once
// ui_d3d9.h - the RmlUi host's Windows and Direct3D 9 includes and the proxy log (J30). Only ui_*.cpp include it: the rest of the
// proxy uses raw vtable slots and never sees <d3d9.h> (backend.cpp exports its own Direct3DCreate9 with a void* signature).
// windowsx.h is deliberately not included: its GetNextSibling/GetFirstChild macros break RmlUi headers (empire-remastered input.cpp).
#include "runtime.h"
#include <d3d9.h>

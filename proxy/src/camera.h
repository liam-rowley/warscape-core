#pragma once
// camera.h - the battle camera setter's pure parts (J43): the pose -> (target, position) conversion and its argument checks. No
// Windows headers, no globals: host tests in proxy/tests/test_camera.cpp. The driver is camera.cpp; the game's sites and offsets come
// from the adapter (CameraAdapter). Conventions match harness/core/campose.py (the readback): world y up; yaw = atan2(forward.x,
// forward.z) in degrees, so a camera looking along -z has yaw 180; pitch = asin(forward.y) in degrees, negative looks down.
#include <cmath>
#include <string>

namespace wsp {

// The game's battle camera layout (proxy/<game>/adapter.cpp). Every number is inside the named engine_sites row's stock bytes
// (test_camera.cpp checks each against the generated site table).
struct CameraAdapter {
    const char* chainSite; int globalOperand;   // instruction reading the battle owner global: owner = *global
    int battleOffOperand;                       // ... battle = *(owner + [operand])
    int controllerOffOperand;                   // ... controller = *(battle + [operand])
    const char* modeSite; int modeOffOperand;   // controller's read of its active mode: mode = *(controller + [operand])
    const char* setSite; int setSlot;           // the mode's SetTargetAndPosition(target*, pos*) and its vtable index
    float targetDistance;                       // metres from the position to the target the setter is given
};

struct CamPose { float x = 0, y = 0, z = 0, yaw = 0, pitch = 0; };

// The target the engine is given: `dist` metres along the pose's forward vector. Refuses non-finite numbers, a pitch at or beyond
// +-89 degrees (the look-at would lose its yaw) and a distance that is not positive.
inline bool CamTargetFor(const CamPose& p, float dist, float target[3], std::string& why) {
    const float v[] = { p.x, p.y, p.z, p.yaw, p.pitch, dist };
    for (float f : v) if (!std::isfinite(f)) { why = "a pose has finite numbers only"; return false; }
    if (std::fabs(p.pitch) >= 89.0f) { why = "pitch must be inside (-89, 89) degrees"; return false; }
    if (dist <= 0) { why = "target distance must be positive"; return false; }
    const double d2r = 3.14159265358979323846 / 180.0, yaw = p.yaw * d2r, pitch = p.pitch * d2r;
    target[0] = (float)(p.x + dist * std::sin(yaw) * std::cos(pitch));
    target[1] = (float)(p.y + dist * std::sin(pitch));
    target[2] = (float)(p.z + dist * std::cos(yaw) * std::cos(pitch));
    return true;
}

} // namespace wsp

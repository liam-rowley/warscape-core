// adapter.cpp - the null adapter (J12): the smallest game adapter the proxy core builds and tests against in warscape-core's CI. No real
// game: an identity no exe has, one engine site that is always refused, the config keys the core reads (fixture registries beside it),
// no console, no camera setter and no orders route. A game repo writes its own adapter.cpp in its proxy/<game>/ folder (docs/CONSUMING.md).
// W6: a null GestureAdapter (a fixed camera, flat ground at y 0, three fake units, a commit that only counts) so the gesture layer builds,
// starts and can be walked with `ctl gesture` without a game; controls.gestures ships off here.
#include "generated/tables.h"

namespace wsp {
namespace {
const char* const kNone[] = { nullptr };
const DevAdapter kDev = { kNone, kNone, kNone, "nullgame\\lua\\", "data\\battleterrain\\presets\\", "data\\*.pack" };

GestureScene NullScene(std::string& why) { why = "the null game's battle"; return GestureScene::Eligible; }
bool NullCamera(GestureCam& c, std::string&) {   // 60 m up, 80 m behind the origin, looking at it; 70 degrees vertical
    c.pos[0] = 0; c.pos[1] = 60; c.pos[2] = -80; c.target[0] = 0; c.target[1] = 0; c.target[2] = 0; c.fovYDeg = 70; return true;
}
bool NullGround(double x, double z, double& y) { y = 0; return x > -1000 && x < 1000 && z > -1000 && z < 1000; }
bool NullSelection(std::vector<GestureUnitIn>& u, std::string&) {
    u.clear();
    for (int i = 0; i < 3; ++i) u.push_back(GestureUnitIn{ (uint32_t)(i + 1), -30.0 + 30.0 * i, 0, 0, 0, 24, 6, 10, 60, false });
    return true;
}
int NullCommit(const GestureOrderOut*, size_t n, std::string& why) { why = "the null game orders nothing"; return (int)n; }
const GestureAdapter kGesture = { NullScene, NullCamera, NullGround, NullSelection, nullptr, NullCommit, 6, 3.0, 1, 3, 0.0, 0.0, 1 };
}

const GameAdapter& Adapter() {
    static const GameAdapter a = { gen::kGameName, gen::kConfigFile, gen::kModDir, gen::kInstanceMutex, gen::kIdentity,
                                   gen::kSites, gen::kSiteCount, gen::kKeys, gen::kKeyCount, &kDev, nullptr, nullptr, nullptr, &kGesture, nullptr };
    return a;
}

} // namespace wsp

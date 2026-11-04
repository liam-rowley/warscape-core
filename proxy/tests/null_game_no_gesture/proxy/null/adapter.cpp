// adapter.cpp - a test fixture, not a game (W37): the null game with GameAdapter::gesture = nullptr, as a real game has until it writes a
// GestureAdapter. build.sh smoke steps 6 and 7 must pass on the inert path ("gesture: ... no adapter ..."). Same identity, sites and keys as
// proxy/tests/null_game (a copy: regenerate with WSP_GAME_ROOT=proxy/tests/null_game_no_gesture python3 proxy/tools/gen_tables.py).
#include "generated/tables.h"

namespace wsp {
namespace {
const char* const kNone[] = { nullptr };
const DevAdapter kDev = { kNone, kNone, kNone, "nullgame\\lua\\", "data\\battleterrain\\presets\\", "data\\*.pack" };
}

const GameAdapter& Adapter() {
    static const GameAdapter a = { gen::kGameName, gen::kConfigFile, gen::kModDir, gen::kInstanceMutex, gen::kIdentity,
                                   gen::kSites, gen::kSiteCount, gen::kKeys, gen::kKeyCount, &kDev, nullptr, nullptr, nullptr, nullptr };
    return a;
}

} // namespace wsp

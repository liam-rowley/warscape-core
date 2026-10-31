// adapter.cpp - the null adapter (J12): the smallest game adapter the proxy core builds and tests against in warscape-core's CI. No real
// game: an identity no exe has, one engine site that is always refused, the config keys the core reads (fixture registries beside it),
// no console and no camera setter. A game repo writes its own adapter.cpp in its proxy/<game>/ folder (docs/CONSUMING.md).
#include "generated/tables.h"

namespace wsp {
namespace {
const char* const kNone[] = { nullptr };
const DevAdapter kDev = { kNone, kNone, kNone, "nullgame\\lua\\", "data\\battleterrain\\presets\\", "data\\*.pack" };
}

const GameAdapter& Adapter() {
    static const GameAdapter a = { gen::kGameName, gen::kConfigFile, gen::kModDir, gen::kInstanceMutex, gen::kIdentity,
                                   gen::kSites, gen::kSiteCount, gen::kKeys, gen::kKeyCount, &kDev, nullptr, nullptr };
    return a;
}

} // namespace wsp

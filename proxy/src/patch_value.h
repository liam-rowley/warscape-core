#pragma once
// Value rows (W7): an engine_sites patch row whose bytes come from a numeric config key (valueKey) instead of fixed patch_bytes. Pure
// core (no Windows headers, no globals; host tests in proxy/tests/test_patch_value.cpp). The driver resolves the whole table into an
// EFFECTIVE COPY before the plan (ResolveSites), so MakePatchPlan, ApplyPlanToBuffer and WritePlanAtomic run unchanged on it: anchor,
// stock, relocation and overlap checks and all-or-nothing hold for value rows exactly as for fixed rows.
//
// ResolveSiteValue, in this order (docs/PROXY_SITES.md):
//   configured 0                                  -> Stock ("key at stock")
//   written = configured x valueScale
//   not finite, outside int32 (int rows round to nearest), outside float32 -> Refused (THIS site stays stock, never the whole plan)
//   valueFloorStock: written = max(stock decoded, written)
//   encoded bytes == stock                        -> Stock ("equals stock")
//   else                                          -> Write
// Stock and Refused give the site its stock bytes and disable it (checked as part of the exe's identity, never written); Write enables
// it with the encoded bytes. The value's encoding is the key's type (float32 or int32, little-endian, 4 bytes).
#include <cfloat>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string>
#include <vector>
#include "config.h"
#include "patch_engine.h"

namespace wsp {

inline void EncodeF32(double v, uint8_t* out) { const float f = (float)v; uint32_t u; memcpy(&u, &f, 4); Wr32(out, u); }
inline double DecodeF32(const uint8_t* p) { const uint32_t u = Rd32(p); float f; memcpy(&f, &u, 4); return f; }
inline void EncodeI32(int32_t v, uint8_t* out) { Wr32(out, (uint32_t)v); }
inline double DecodeI32(const uint8_t* p) { return (double)(int32_t)Rd32(p); }

enum class ValueAction : uint8_t { Stock, Write, Refused };
inline const char* ValueActionName(ValueAction a) { return a == ValueAction::Write ? "write" : a == ValueAction::Stock ? "stock" : "REFUSED"; }

struct SiteValue {
    ValueAction action = ValueAction::Stock;
    uint8_t bytes[4] = {};   // what the effective table holds as patch bytes (stock unless Write)
    double written = 0;      // the value as encoded (Write), or the value that was refused
    std::string why;         // "key at stock", "equals stock", or the refusal
};

// The stock value of a value row (decoded from its 4 stock bytes); false = not a value row or not a finite number.
inline bool StockValue(const SiteDef& d, double& v) {
    if (d.len != 4 || (d.valueType != kValueF32 && d.valueType != kValueI32)) return false;
    v = d.valueType == kValueF32 ? DecodeF32(d.stock) : DecodeI32(d.stock);
    return std::isfinite(v);
}

inline SiteValue ResolveSiteValue(const SiteDef& d, double configured) {
    SiteValue r; char b[160];
    memcpy(r.bytes, d.stock, d.len < 4 ? d.len : 4);
    auto refuse = [&](const char* why) { r.action = ValueAction::Refused; r.why = why; return r; };
    if (d.kind != kPatch || d.len != 4 || (d.valueType != kValueF32 && d.valueType != kValueI32)) return refuse("not a 4-byte float32 or int32 value row");
    if (configured == 0) { r.why = "key at stock"; return r; }
    double w = configured * d.valueScale;
    r.written = w;
    if (!std::isfinite(w)) return refuse("value is not finite");
    if (d.valueType == kValueI32) {
        w = std::nearbyint(w);   // nearest (ties to even under the default rounding mode)
        if (w < -2147483648.0 || w > 2147483647.0) { snprintf(b, sizeof b, "%.17g is outside int32", r.written); r.why = b; r.action = ValueAction::Refused; return r; }
    } else if (std::fabs(w) > FLT_MAX) { snprintf(b, sizeof b, "%.17g is outside float32", w); r.why = b; r.action = ValueAction::Refused; return r; }
    if (d.valueFloorStock) {
        double s = 0;
        if (!StockValue(d, s)) return refuse("stock bytes are not a finite number (floor stock)");
        if (w < s) w = s;
    }
    if (d.valueType == kValueF32) EncodeF32(w, r.bytes); else EncodeI32((int32_t)w, r.bytes);
    r.written = d.valueType == kValueF32 ? DecodeF32(r.bytes) : DecodeI32(r.bytes);
    if (memcmp(r.bytes, d.stock, 4) == 0) { r.why = "equals stock"; return r; }
    r.action = ValueAction::Write;
    return r;
}

// The table the plan runs on: fixed rows as they are (enabled = their boolean key, or always), value rows with their resolved bytes
// (enabled only for Write). values[i] is meaningful for value rows only (sites[i].valueKey).
struct EffectiveSites {
    std::vector<SiteDef> sites;
    std::unique_ptr<bool[]> enabled;
    std::vector<SiteValue> values;
    int nValueRows = 0, nValueWrites = 0, nValueRefused = 0;
};

inline EffectiveSites ResolveSites(const SiteDef* s, size_t n, const Config& cfg) {
    EffectiveSites e;
    e.sites.assign(s, s + n);
    e.enabled.reset(new bool[n + 1]);
    e.values.resize(n);
    for (size_t i = 0; i < n; ++i) {
        SiteDef& d = e.sites[i];
        if (!d.valueKey) { e.enabled[i] = !d.configKey || cfg.Bool(d.configKey); continue; }
        ++e.nValueRows;
        SiteValue& v = e.values[i];
        v = ResolveSiteValue(d, cfg.Float(d.valueKey));
        memcpy(d.patch, v.bytes, d.len < 4 ? d.len : 4);
        e.enabled[i] = v.action == ValueAction::Write;
        e.nValueWrites += v.action == ValueAction::Write;
        e.nValueRefused += v.action == ValueAction::Refused;
    }
    return e;
}

// One log line per value row (the driver writes it before the plan): "value <id> <- <key>=<v> (x<scale>[, floor stock <s>]): ...".
inline std::string ValueLine(const SiteDef& d, const SiteValue& v, const Config& cfg) {
    char b[400], extra[80] = "";
    double s = 0;
    if (d.valueFloorStock && StockValue(d, s)) snprintf(extra, sizeof extra, ", floor stock %.9g", s);
    const std::string& key = cfg.Str(d.valueKey ? d.valueKey : "");
    if (v.action == ValueAction::Write)
        snprintf(b, sizeof b, "patch_engine: value %s <- %s=%s (x%.9g%s): %.9g %s [%02x %02x %02x %02x]", d.id, d.valueKey, key.c_str(), d.valueScale, extra,
                 v.written, d.valueType == kValueF32 ? "f32" : "i32", v.bytes[0], v.bytes[1], v.bytes[2], v.bytes[3]);
    else if (v.action == ValueAction::Stock)
        snprintf(b, sizeof b, "patch_engine: value %s <- %s=%s (x%.9g%s): stock (%s)", d.id, d.valueKey, key.c_str(), d.valueScale, extra, v.why.c_str());
    else
        snprintf(b, sizeof b, "patch_engine: value %s <- %s=%s (x%.9g%s): REFUSED %s, site left stock", d.id, d.valueKey ? d.valueKey : "?", key.c_str(),
                 d.valueScale, extra, v.why.c_str());
    return b;
}

} // namespace wsp

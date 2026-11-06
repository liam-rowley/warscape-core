#pragma once
// J25 spike, not for shipping: the pure half of the two-cascade prototype (no Windows headers; host tests in proxy/tests/test_cascade.cpp).
//   - CTAB reader and the swap gate: a replacement keeps every stock constant and sampler in its stock register, or it is refused
//   - the pass recogniser: which SetRenderTarget(0, ...) begins and ends the shadow pass
//   - the near cascade's fit: a bounding sphere of the frustum slice, snapped to whole texels so it does not shimmer
// Registers (read from the captures, run 20261106_j25pc): one register per output component, so c[base + i] is output i's row.
#include <cmath>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace wsp {

struct CtabEntry { std::string name; unsigned set = 0, index = 0, count = 0; };   // set: 0 bool, 1 int, 2 float, 3 sampler

// The constant table of a shader's bytecode; empty when it has none. Bounds-checked: bytecode comes from the engine or from a file.
inline std::vector<CtabEntry> ReadCtab(const void* code, size_t bytes) {
    std::vector<CtabEntry> out;
    const auto* b = static_cast<const uint8_t*>(code);
    auto u32 = [&](size_t o) { uint32_t v; memcpy(&v, b + o, 4); return v; };
    auto u16 = [&](size_t o) { uint16_t v; memcpy(&v, b + o, 2); return v; };
    size_t o = 4;
    while (o + 8 <= bytes) {
        const uint32_t tok = u32(o);
        if ((tok & 0xFFFF) != 0xFFFE) break;
        const size_t len = 4 * (size_t)((tok >> 16) & 0x7FFF);
        if (o + 4 + len > bytes) break;
        if (len >= 32 && memcmp(b + o + 4, "CTAB", 4) == 0) {
            const size_t base = o + 8, end = o + 4 + len;
            const uint32_t n = u32(base + 12), info = u32(base + 16);
            for (uint32_t i = 0; i < n; ++i) {
                const size_t e = base + info + 20 * (size_t)i;
                if (e + 20 > end) break;
                const size_t nm = base + u32(e);
                if (nm >= end) break;
                CtabEntry c;
                for (size_t p = nm; p < end && b[p]; ++p) c.name += (char)b[p];
                c.set = u16(e + 4); c.index = u16(e + 6); c.count = u16(e + 8);
                out.push_back(c);
            }
            return out;
        }
        o += 4 + len;
    }
    return out;
}

inline const CtabEntry* FindConst(const std::vector<CtabEntry>& t, const char* name) {
    for (const CtabEntry& c : t) if (c.name == name) return &c;
    return nullptr;
}

// One name can hold an entry per register set (a bool used as bool and float: flat_shading, campaign_snow_enabled), so entries match on both.
inline const CtabEntry* FindConst(const std::vector<CtabEntry>& t, const std::string& name, unsigned set) {
    for (const CtabEntry& c : t) if (c.name == name && c.set == set) return &c;
    return nullptr;
}

// The brief's gate: fail = no swap. The engine uploads by the registers of its own stock compile, so a moved register reads garbage.
inline bool CtabGate(const std::vector<CtabEntry>& stock, const std::vector<CtabEntry>& repl, std::string& why) {
    if (stock.empty()) { why = "the stock shader has no CTAB"; return false; }
    for (const CtabEntry& s : stock) {
        const CtabEntry* r = FindConst(repl, s.name, s.set);
        if (!r) { why = s.name + " is gone"; return false; }
        if (r->index != s.index || r->count < s.count) { why = s.name + " moved"; return false; }
    }
    if (!FindConst(repl, "cascade0_matrix")) { why = "no cascade code in the replacement"; return false; }
    for (const CtabEntry& r : repl)
        if (!FindConst(stock, r.name, r.set) && r.name.rfind("cascade0_", 0) != 0) { why = "new constant " + r.name; return false; }
    return true;
}

// D3DFMT_R16F 111, D3DFMT_R32F 114: the software path's map (fact napoleon.shadow.map); square, and a render target.
inline bool IsShadowMapDesc(uint32_t fmt, uint32_t usage, uint32_t w, uint32_t h) {
    return (fmt == 111 || fmt == 114) && (usage & 1) && w == h && w >= 512;
}

enum class PassStep { none, begin, end };
struct PassTracker {
    bool in = false; long passes = 0;
    PassStep OnRenderTarget0(bool isMap) {
        if (isMap && !in) { in = true; ++passes; return PassStep::begin; }
        if (!isMap && in) { in = false; return PassStep::end; }
        return PassStep::none;
    }
};

struct CascadeFit {
    bool ok = false;
    float clip[16] = {};   // caster: replaces shadow_map_projection_matrix; row 2 is unused (the shader writes linear z into position.z)
    float recv[16] = {};   // receiver: world -> (u, v, linear z, 1)
    float cx = 0, cy = 0, radius = 0, texelM = 0, tSlice = 0;
};

inline float Dot3(const float* a, const float* b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
inline void Cross3(const float* a, const float* b, float* o) { o[0] = a[1] * b[2] - a[2] * b[1]; o[1] = a[2] * b[0] - a[0] * b[2]; o[2] = a[0] * b[1] - a[1] * b[0]; }
inline bool Norm3(float* v) { const float l = std::sqrt(Dot3(v, v)); if (!(l > 1e-12f)) return false; v[0] /= l; v[1] /= l; v[2] /= l; return true; }

// cam, target: the camera. lzRow2: the engine's linear-z row (world -> depth, its xyz is the light direction scaled, w the offset), read from the
// casters' upload, so depth stays the engine's and the receivers' compare keeps its meaning. bias: the receivers' depth bias in that unit (the
// receiver's row differs from the caster's by exactly this: 0.0005, field +0xf4). tanHalfY, aspect: the view; nearD, splitD: the slice in metres.
// The radius depends only on the slice and the view, never on the camera's direction, so turning the camera cannot change the texel size.
inline CascadeFit FitCascade(const float cam[3], const float target[3], const float lzRow2[4], float bias, float tanHalfY, float aspect, float nearD, float splitD, int size) {
    CascadeFit f;
    float fwd[3] = { target[0] - cam[0], target[1] - cam[1], target[2] - cam[2] };
    float z[3] = { lzRow2[0], lzRow2[1], lzRow2[2] };
    if (!Norm3(fwd) || !Norm3(z) || size < 2 || !(splitD > nearD) || !(tanHalfY > 0) || !(aspect > 0)) return f;
    const float up[3] = { 0, 1, 0 };
    float x[3], y[3];
    Cross3(up, z, x);
    if (!Norm3(x)) { const float alt[3] = { 1, 0, 0 }; Cross3(alt, z, x); if (!Norm3(x)) return f; }
    Cross3(z, x, y);
    const float tx = tanHalfY * aspect, k2 = tx * tx + tanHalfY * tanHalfY;
    float t = 0.5f * (nearD + splitD) * (1 + k2);   // the smallest sphere through both end rings of the slice; past the far ring, the far ring's own
    if (t > splitD) t = splitD;
    const float dn = t - nearD, df = splitD - t;
    const float r = std::sqrt(std::fmax(dn * dn + k2 * nearD * nearD, df * df + k2 * splitD * splitD));
    const float c[3] = { cam[0] + fwd[0] * t, cam[1] + fwd[1] * t, cam[2] + fwd[2] * t };
    const float texel = 2 * r / (float)size;
    const float cx = std::round(Dot3(c, x) / texel) * texel, cy = std::round(Dot3(c, y) / texel) * texel;
    const float half = 0.5f / (float)size;   // the map's texel centre: the engine's receiver matrix carries the same term
    for (int i = 0; i < 3; ++i) {
        f.clip[i] = x[i] / r; f.clip[4 + i] = y[i] / r;
        f.recv[i] = 0.5f * x[i] / r; f.recv[4 + i] = -0.5f * y[i] / r; f.recv[8 + i] = lzRow2[i];
    }
    f.clip[3] = -cx / r; f.clip[7] = -cy / r; f.clip[15] = 1;
    f.recv[3] = -0.5f * cx / r + 0.5f + half; f.recv[7] = 0.5f * cy / r + 0.5f + half; f.recv[11] = lzRow2[3] - bias; f.recv[15] = 1;
    f.cx = cx; f.cy = cy; f.radius = r; f.texelM = texel; f.tSlice = t; f.ok = true;
    return f;
}

} // namespace wsp

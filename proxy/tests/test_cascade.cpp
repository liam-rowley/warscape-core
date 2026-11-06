// test_cascade.cpp - J25 spike: host tests for the prototype's pure half: the CTAB reader and swap gate, the pass recogniser on the recorded call
// shape of a captured frame, and the cascade fit (the texel snap, turning the camera, the receiver against the caster).
#include "testkit.h"
#include "cascade.h"
#include <vector>

using namespace wsp;

// A minimal shader: version token, one CTAB comment, end token.
static std::vector<uint32_t> Shader(const std::vector<CtabEntry>& cs) {
    std::vector<uint8_t> t(28 + 20 * cs.size(), 0);
    auto put = [&](size_t o, uint32_t v) { memcpy(&t[o], &v, 4); };
    auto put16 = [&](size_t o, uint16_t v) { memcpy(&t[o], &v, 2); };
    put(12, (uint32_t)cs.size()); put(16, 28);
    for (size_t i = 0; i < cs.size(); ++i) {
        const size_t e = 28 + 20 * i, nm = t.size();
        put(e, (uint32_t)nm); put16(e + 4, (uint16_t)cs[i].set); put16(e + 6, (uint16_t)cs[i].index); put16(e + 8, (uint16_t)cs[i].count);
        t.insert(t.end(), cs[i].name.begin(), cs[i].name.end()); t.push_back(0);
    }
    while (t.size() % 4) t.push_back(0);
    std::vector<uint32_t> s; s.push_back(0xFFFF0300);
    s.push_back(0xFFFE | (uint32_t)((t.size() / 4 + 1) << 16)); s.push_back(0x42415443);   // 'CTAB'
    const size_t at = s.size(); s.resize(at + t.size() / 4); memcpy(&s[at], t.data(), t.size());
    s.push_back(0x0000FFFF);
    return s;
}
static std::vector<CtabEntry> Read(const std::vector<uint32_t>& s) { return ReadCtab(s.data(), s.size() * 4); }

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    const std::vector<CtabEntry> stock = { { "camera_position", 2, 11, 1 }, { "shadow_map_texture_sampler", 3, 1, 1 } };
    auto parsed = Read(Shader(stock));
    CHECK(parsed.size() == 2 && parsed[0].name == "camera_position" && parsed[0].index == 11 && parsed[1].set == 3);
    CHECK(ReadCtab(Shader(stock).data(), 8).empty());

    auto with = stock; with.push_back({ "cascade0_matrix", 2, 216, 4 }); with.push_back({ "cascade0_sampler", 3, 15, 1 });
    std::string why;
    CHECK(CtabGate(Read(Shader(stock)), Read(Shader(with)), why));
    auto moved = with; moved[0].index = 12;
    CHECK(!CtabGate(Read(Shader(stock)), Read(Shader(moved)), why) && why == "camera_position moved");
    auto gone = with; gone.erase(gone.begin());
    CHECK(!CtabGate(Read(Shader(stock)), Read(Shader(gone)), why));
    CHECK(!CtabGate(Read(Shader(stock)), Read(Shader(stock)), why) && why == "no cascade code in the replacement");
    auto extra = with; extra.push_back({ "something_else", 2, 100, 1 });
    CHECK(!CtabGate(Read(Shader(stock)), Read(Shader(extra)), why));

    // the case the PC found (run 20261106_j25pc, raw/c_on): one name in two register sets, in the opposite order in the replacement
    const std::vector<CtabEntry> two = { { "flat_shading", 0, 3, 1 }, { "flat_shading", 2, 30, 1 } };
    auto twoNew = std::vector<CtabEntry>{ { "flat_shading", 2, 30, 1 }, { "flat_shading", 0, 3, 1 }, { "cascade0_matrix", 2, 216, 4 } };
    CHECK(CtabGate(Read(Shader(two)), Read(Shader(twoNew)), why));
    twoNew[0].index = 31;
    CHECK(!CtabGate(Read(Shader(two)), Read(Shader(twoNew)), why) && why == "flat_shading moved");
    twoNew[0].index = 30; twoNew.erase(twoNew.begin() + 1);
    CHECK(!CtabGate(Read(Shader(two)), Read(Shader(twoNew)), why) && why == "flat_shading is gone");

    CHECK(IsShadowMapDesc(111, 1, 2048, 2048) && IsShadowMapDesc(114, 1, 8192, 8192));
    CHECK(!IsShadowMapDesc(21, 1, 2048, 2048) && !IsShadowMapDesc(111, 0, 2048, 2048) && !IsShadowMapDesc(111, 1, 1920, 1080));

    // the recorded shape (run 20261106_j25pc): map, then the 960 reflection target, then the back buffer chain; a repeated set is not a new pass
    PassTracker p;
    CHECK(p.OnRenderTarget0(false) == PassStep::none);
    CHECK(p.OnRenderTarget0(true) == PassStep::begin && p.OnRenderTarget0(true) == PassStep::none);
    CHECK(p.OnRenderTarget0(false) == PassStep::end && p.OnRenderTarget0(false) == PassStep::none);
    CHECK(p.OnRenderTarget0(true) == PassStep::begin && p.passes == 2);

    const float lz[4] = { 5.99e-11f, -0.00161340262f, 0.0025127253f, -0.0627065003f };   // captured, land_40 deploy
    const float cam[3] = { -0.08f, 61.39f, 451.38f }, tgt[3] = { -0.08f, 40.0f, 405.0f };
    const float th = 0.70020753f, as = 16.0f / 9.0f;
    CascadeFit f = FitCascade(cam, tgt, lz, 0.0005f, th, as, 1, 40, 2048);
    CHECK(f.ok && f.radius > 50 && f.radius < 60);
    CHECK(std::fabs(f.texelM - 2 * f.radius / 2048) < 1e-6f);

    // the world point at the fit's centre lands mid-map, and the receiver is the caster plus the texel-centre term
    auto apply = [](const float* m, int row, const float* w) { return m[4 * row] * w[0] + m[4 * row + 1] * w[1] + m[4 * row + 2] * w[2] + m[4 * row + 3]; };
    const float w[3] = { 3.0f, 20.0f, 420.0f };
    const float nx = apply(f.clip, 0, w), ny = apply(f.clip, 1, w), u = apply(f.recv, 0, w), v = apply(f.recv, 1, w);
    CHECK(std::fabs(u - (0.5f * nx + 0.5f + 0.5f / 2048)) < 1e-5f && std::fabs(v - (-0.5f * ny + 0.5f + 0.5f / 2048)) < 1e-5f);
    const float zc = lz[0] * w[0] + lz[1] * w[1] + lz[2] * w[2] + lz[3];
    CHECK(std::fabs(apply(f.recv, 2, w) - (zc - 0.0005f)) < 1e-6f);
    CHECK(f.clip[15] == 1 && f.clip[12] == 0 && f.clip[13] == 0 && f.clip[14] == 0);

    // shimmer: the snapped centre stays on the texel grid while the camera slides, and moves by whole texels only
    for (int i = 0; i < 200; ++i) {
        const float c2[3] = { cam[0] + 0.0137f * (float)i, cam[1], cam[2] - 0.0071f * (float)i }, t2[3] = { tgt[0] + 0.0137f * (float)i, tgt[1], tgt[2] - 0.0071f * (float)i };
        const CascadeFit g = FitCascade(c2, t2, lz, 0.0005f, th, as, 1, 40, 2048);
        const float a = g.cx / g.texelM, b = g.cy / g.texelM;
        CHECK(std::fabs(a - std::round(a)) < 2e-2f && std::fabs(b - std::round(b)) < 2e-2f);
    }
    // turning the camera never changes the texel size: the density cannot depend on yaw
    for (int y = 0; y < 8; ++y) {
        const float a = 0.785398f * (float)y, t2[3] = { cam[0] + std::sin(a), cam[1] - 0.4f, cam[2] + std::cos(a) };
        CHECK(std::fabs(FitCascade(cam, t2, lz, 0.0005f, th, as, 1, 40, 2048).texelM - f.texelM) < 1e-6f);
    }
    CHECK(!FitCascade(cam, cam, lz, 0.0005f, th, as, 1, 40, 2048).ok);
    CHECK(!FitCascade(cam, tgt, lz, 0.0005f, th, as, 40, 40, 2048).ok);
    return tk::Done("test_cascade");
}

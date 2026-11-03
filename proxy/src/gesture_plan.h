#pragma once
// gesture_plan.h - the per-unit plan and the preview geometry (W6), platform-free; host-tested by proxy/tests/test_gesture.cpp.
//   - each target's rectangle draped on the ground (every corner at the ground height under it), its facing tick (front centre to 3 m
//     ahead) and whether the game would refuse the order (off the ground, or the adapter's check): refused units draw red and are
//     skipped at the release, the rest are ordered (empire-remastered's per-unit fallback, without the search)
//   - the orders a release sends, one per accepted unit
//   - the overlay's screen-space vertices (XYZRHW + diffuse, the D3D9 fixed-function layout): two triangles per rectangle, its outline
//     and the tick as a line list; a unit with any point behind the camera is not drawn
#include "gesture_math.h"
#include <cstdint>
#include <string>
#include <vector>

namespace wsp {
namespace gest {

struct UnitPlan {
    Unit t;                  // the target (order point, facing, width, depth)
    V3 corners[4];           // draped: front-left, front-right, back-right, back-left
    V3 tick[2];              // front centre -> 3 m ahead, draped
    bool refused = false;
    std::string why;         // why refused
};
struct Order { uint32_t id = 0; double x = 0, z = 0, bearing = 0, width = 0; };

// ground(x, z, &y): the game's ground height (false = no ground there); check(target, why): the adapter's refusal test (true = fine).
template <class Ground, class Check>
std::vector<UnitPlan> MakePlan(const std::vector<Unit>& targets, Ground ground, Check check) {
    std::vector<UnitPlan> plan;
    for (const Unit& t : targets) {
        UnitPlan p; p.t = t;
        V2 fp[4]; Footprint(t, fp);
        bool onGround = true;
        for (int i = 0; i < 4; ++i) { double y = 0; if (!ground(fp[i].x, fp[i].z, &y)) { onGround = false; y = t.y; } p.corners[i] = V3{ fp[i].x, y, fp[i].z }; }
        const V2 f = Facing(t.bearing), c = UnitCentre(t); const double hd = FootDepth(t) / 2;
        const V2 front{ c.x + f.x * hd, c.z + f.z * hd }, ahead{ front.x + f.x * 3.0, front.z + f.z * 3.0 };
        double y0 = 0, y1 = 0;
        if (!ground(front.x, front.z, &y0)) { onGround = false; y0 = t.y; }
        if (!ground(ahead.x, ahead.z, &y1)) y1 = y0;
        p.tick[0] = V3{ front.x, y0, front.z }; p.tick[1] = V3{ ahead.x, y1, ahead.z };
        double gy = 0;
        if (ground(t.x, t.z, &gy)) p.t.y = gy; else onGround = false;
        if (!onGround) { p.refused = true; p.why = "no ground under the target (off the map)"; }
        else { std::string why; if (!check(p.t, why)) { p.refused = true; p.why = why.empty() ? "refused by the game" : why; } }
        plan.push_back(p);
    }
    return plan;
}
inline std::vector<Order> OrdersOf(const std::vector<UnitPlan>& plan) {
    std::vector<Order> o;
    for (const UnitPlan& p : plan) if (!p.refused) o.push_back(Order{ p.t.id, p.t.x, p.t.z, p.t.bearing, p.t.width });
    return o;
}
inline size_t RefusedCount(const std::vector<UnitPlan>& plan) { size_t n = 0; for (const UnitPlan& p : plan) n += p.refused ? 1 : 0; return n; }

// ---- the overlay -----------------------------------------------------------------------------------------------------------------
struct Vtx { float x, y, z, rhw; uint32_t color; };   // D3DFVF_XYZRHW | D3DFVF_DIFFUSE (20 bytes)
struct Colors { uint32_t fill = 0x4840D0FFu, edge = 0xE0E8F8FFu, tick = 0xF0FFFFFFu, badFill = 0x58FF2020u, badEdge = 0xF0FF4040u; };
struct Overlay { std::vector<Vtx> tris, lines; size_t drawn = 0, hidden = 0; };
inline Overlay BuildOverlay(const std::vector<UnitPlan>& plan, const double* vp, double w, double h, const Colors& col = Colors()) {
    Overlay o;
    for (const UnitPlan& p : plan) {
        double s[6][2]; bool ok = true;
        for (int i = 0; i < 4 && ok; ++i) ok = WorldToScreen(p.corners[i], vp, w, h, &s[i][0], &s[i][1]);
        for (int i = 0; i < 2 && ok; ++i) ok = WorldToScreen(p.tick[i], vp, w, h, &s[4 + i][0], &s[4 + i][1]);
        if (!ok) { ++o.hidden; continue; }
        const uint32_t fill = p.refused ? col.badFill : col.fill, edge = p.refused ? col.badEdge : col.edge, tick = p.refused ? col.badEdge : col.tick;
        auto V = [&](int i, uint32_t c) { return Vtx{ (float)s[i][0], (float)s[i][1], 0.0f, 1.0f, c }; };
        for (int i : { 0, 1, 2, 0, 2, 3 }) o.tris.push_back(V(i, fill));
        for (int e = 0; e < 4; ++e) { o.lines.push_back(V(e, edge)); o.lines.push_back(V((e + 1) % 4, edge)); }
        o.lines.push_back(V(4, tick)); o.lines.push_back(V(5, tick));
        ++o.drawn;
    }
    return o;
}

}  // namespace gest
}  // namespace wsp

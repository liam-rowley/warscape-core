#pragma once
// gesture_math.h - the gesture layer's maths (W6), header-only, no Windows types: host-tested by proxy/tests/test_gesture.cpp.
// Ported from empire-remastered rml_mod/src/gesture_math.h, gesture_v4.h and gesture_v5.h (the selftest, the Python cross-check
// vectors and the v3-v5 rotate cases come with it), without the depth-prepass pick, the reach search and the sound gate. New here:
// the camera matrices from a readable pose (position, target, vertical field of view, client aspect), the ray pick refined against
// the game's ground height, and the line layout (Alt+drag = move to the drawn line).
// Conventions: D3D row vectors, clip = (x, y, z, 1) * VP; NDC y up; pixel p -> uv = (p + 0.5) / size (the D3D9 pixel centre, so a
// projected point is also an XYZRHW vertex position); world y up, ground = xz; bearing in degrees, facing(b) = (sin b, cos b) in (x, z)
// with BearingSign() = +1 (clockwise from +z seen from above; a game with the other sense sets -1 once at start-up).
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

namespace wsp {
namespace gest {

struct V3 { double x = 0, y = 0, z = 0; };
struct V2 { double x = 0, z = 0; };                       // a ground point (xz)
// One selected unit, or one unit's target. (x, z) is the point the game's move order takes: the block's centre, or with frontRef the
// middle of its front edge (the block lies behind it). minWidth / maxWidth: the frontage clamps (0 = none).
struct Unit {
    uint32_t id = 0;
    double x = 0, y = 0, z = 0, bearing = 0, width = 0, depth = 0;
    double minWidth = 0, maxWidth = 0;
    bool frontRef = false;
};

inline double& BearingSign() { static double s = 1.0; return s; }
constexpr double kPi = 3.14159265358979323846;
inline double Rad(double d) { return d * kPi / 180.0; }
inline double Deg(double r) { return r * 180.0 / kPi; }
inline double PyMod(double a, double m) { double r = std::fmod(a, m); if (r < 0) r += m; return r; }   // Python's % (sign of m)

// ------------------------------------------------------------------------------------------------ small linear algebra
inline void MatMul(const double* a, const double* b, double* out) {          // 4x4 row-major
    double t[16];
    for (int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) { double s = 0; for (int k = 0; k < 4; ++k) s += a[r * 4 + k] * b[k * 4 + c]; t[r * 4 + c] = s; }
    for (int i = 0; i < 16; ++i) out[i] = t[i];
}
inline void VecMat(const double* v, const double* m, double* out) {        // row vector (4) * matrix (16)
    double t[4];
    for (int c = 0; c < 4; ++c) { double s = 0; for (int k = 0; k < 4; ++k) s += v[k] * m[k * 4 + c]; t[c] = s; }
    for (int i = 0; i < 4; ++i) out[i] = t[i];
}
inline bool MatInv(const double* a, double* out) {                           // cofactor inverse; false = singular
    double inv[16];
    inv[0] = a[5]*a[10]*a[15]-a[5]*a[11]*a[14]-a[9]*a[6]*a[15]+a[9]*a[7]*a[14]+a[13]*a[6]*a[11]-a[13]*a[7]*a[10];
    inv[4] = -a[4]*a[10]*a[15]+a[4]*a[11]*a[14]+a[8]*a[6]*a[15]-a[8]*a[7]*a[14]-a[12]*a[6]*a[11]+a[12]*a[7]*a[10];
    inv[8] = a[4]*a[9]*a[15]-a[4]*a[11]*a[13]-a[8]*a[5]*a[15]+a[8]*a[7]*a[13]+a[12]*a[5]*a[11]-a[12]*a[7]*a[9];
    inv[12] = -a[4]*a[9]*a[14]+a[4]*a[10]*a[13]+a[8]*a[5]*a[14]-a[8]*a[6]*a[13]-a[12]*a[5]*a[10]+a[12]*a[6]*a[9];
    inv[1] = -a[1]*a[10]*a[15]+a[1]*a[11]*a[14]+a[9]*a[2]*a[15]-a[9]*a[3]*a[14]-a[13]*a[2]*a[11]+a[13]*a[3]*a[10];
    inv[5] = a[0]*a[10]*a[15]-a[0]*a[11]*a[14]-a[8]*a[2]*a[15]+a[8]*a[3]*a[14]+a[12]*a[2]*a[11]-a[12]*a[3]*a[10];
    inv[9] = -a[0]*a[9]*a[15]+a[0]*a[11]*a[13]+a[8]*a[1]*a[15]-a[8]*a[3]*a[13]-a[12]*a[1]*a[11]+a[12]*a[3]*a[9];
    inv[13] = a[0]*a[9]*a[14]-a[0]*a[10]*a[13]-a[8]*a[1]*a[14]+a[8]*a[2]*a[13]+a[12]*a[1]*a[10]-a[12]*a[2]*a[9];
    inv[2] = a[1]*a[6]*a[15]-a[1]*a[7]*a[14]-a[5]*a[2]*a[15]+a[5]*a[3]*a[14]+a[13]*a[2]*a[7]-a[13]*a[3]*a[6];
    inv[6] = -a[0]*a[6]*a[15]+a[0]*a[7]*a[14]+a[4]*a[2]*a[15]-a[4]*a[3]*a[14]-a[12]*a[2]*a[7]+a[12]*a[3]*a[6];
    inv[10] = a[0]*a[5]*a[15]-a[0]*a[7]*a[13]-a[4]*a[1]*a[15]+a[4]*a[3]*a[13]+a[12]*a[1]*a[7]-a[12]*a[3]*a[5];
    inv[14] = -a[0]*a[5]*a[14]+a[0]*a[6]*a[13]+a[4]*a[1]*a[14]-a[4]*a[2]*a[13]-a[12]*a[1]*a[6]+a[12]*a[2]*a[5];
    inv[3] = -a[1]*a[6]*a[11]+a[1]*a[7]*a[10]+a[5]*a[2]*a[11]-a[5]*a[3]*a[10]-a[9]*a[2]*a[7]+a[9]*a[3]*a[6];
    inv[7] = a[0]*a[6]*a[11]-a[0]*a[7]*a[10]-a[4]*a[2]*a[11]+a[4]*a[3]*a[10]+a[8]*a[2]*a[7]-a[8]*a[3]*a[6];
    inv[11] = -a[0]*a[5]*a[11]+a[0]*a[7]*a[9]+a[4]*a[1]*a[11]-a[4]*a[3]*a[9]-a[8]*a[1]*a[7]+a[8]*a[3]*a[5];
    inv[15] = a[0]*a[5]*a[10]-a[0]*a[6]*a[9]-a[4]*a[1]*a[10]+a[4]*a[2]*a[9]+a[8]*a[1]*a[6]-a[8]*a[2]*a[5];
    const double det = a[0]*inv[0]+a[1]*inv[4]+a[2]*inv[8]+a[3]*inv[12];
    if (std::fabs(det) < 1e-30) return false;
    for (int i = 0; i < 16; ++i) out[i] = inv[i] / det;
    return true;
}
inline void LookAtLH(V3 eye, V3 at, double* m, V3 up = V3{ 0, 1, 0 }) {     // D3DXMatrixLookAtLH
    auto sub = [](V3 a, V3 b) { return V3{ a.x - b.x, a.y - b.y, a.z - b.z }; };
    auto nrm = [](V3 a) { const double l = std::sqrt(a.x * a.x + a.y * a.y + a.z * a.z); return V3{ a.x / l, a.y / l, a.z / l }; };
    auto cross = [](V3 a, V3 b) { return V3{ a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x }; };
    auto dot = [](V3 a, V3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; };
    const V3 z = nrm(sub(at, eye)), x = nrm(cross(up, z)), y = cross(z, x);
    const double r[16] = { x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0, -dot(x, eye), -dot(y, eye), -dot(z, eye), 1 };
    for (int i = 0; i < 16; ++i) m[i] = r[i];
}
inline void PerspectiveFovLH(double fovyDeg, double aspect, double zn, double zf, double* m) {   // D3DXMatrixPerspectiveFovLH
    const double ys = 1.0 / std::tan(Rad(fovyDeg) / 2), xs = ys / aspect;
    const double r[16] = { xs, 0, 0, 0, 0, ys, 0, 0, 0, 0, zf / (zf - zn), 1, 0, 0, -zn * zf / (zf - zn), 0 };
    for (int i = 0; i < 16; ++i) m[i] = r[i];
}

// ------------------------------------------------------------------------------------------------ the camera from a readable pose
// The game's camera as the adapter reads it: eye, look-at target, vertical field of view; w and h are the pixel size the cursor and
// the overlay use (the client area for the pick, the back buffer for the overlay; the same aspect). zn / zf only shape the depth.
struct Camera { V3 pos, target; double fovYDeg = 0, w = 0, h = 0, zn = 1.0, zf = 20000.0; };
// VP = LookAtLH(pos, target) x PerspectiveFovLH(fov, w / h). False for a pose it cannot invert: non-finite numbers, eye on the
// target, a look straight up or down (no yaw), a field of view outside (1, 179) degrees or an empty size.
inline bool CameraVP(const Camera& c, double* vp, double* viewOut = nullptr) {
    const double v[] = { c.pos.x, c.pos.y, c.pos.z, c.target.x, c.target.y, c.target.z, c.fovYDeg, c.w, c.h };
    for (double f : v) if (!std::isfinite(f)) return false;
    if (!(c.w > 0) || !(c.h > 0) || !(c.fovYDeg > 1) || !(c.fovYDeg < 179) || !(c.zf > c.zn) || !(c.zn > 0)) return false;
    const double fx = c.target.x - c.pos.x, fy = c.target.y - c.pos.y, fz = c.target.z - c.pos.z, l = std::sqrt(fx * fx + fy * fy + fz * fz);
    if (l < 1e-6 || std::hypot(fx, fz) / l < 1e-6) return false;
    double view[16], proj[16];
    LookAtLH(c.pos, c.target, view);
    PerspectiveFovLH(c.fovYDeg, c.w / c.h, c.zn, c.zf, proj);
    MatMul(view, proj, vp);
    if (viewOut) for (int i = 0; i < 16; ++i) viewOut[i] = view[i];
    return true;
}

// ------------------------------------------------------------------------------------------------ world <-> screen
// World point -> pixel (px, py) + device depth; false when behind the camera.
inline bool WorldToScreen(V3 p, const double* vp, double w, double h, double* px, double* py, double* depth = nullptr) {
    const double v[4] = { p.x, p.y, p.z, 1.0 }; double c[4]; VecMat(v, vp, c);
    if (c[3] <= 1e-6) return false;
    const double nx = c[0] / c[3], ny = c[1] / c[3], nz = c[2] / c[3];
    const double u = nx * 0.5 + 0.5, vv = 0.5 - ny * 0.5;
    *px = u * w - 0.5; *py = vv * h - 0.5; if (depth) *depth = nz;
    return true;
}
// Pixel -> (p0 on the near plane, direction towards device depth 1).
inline void PixelRay(double px, double py, const double* vpInv, double w, double h, V3* p0, V3* d) {
    const double u = (px + 0.5) / w, v = (py + 0.5) / h, nx = 2 * u - 1, ny = 1 - 2 * v;
    const double a[4] = { nx, ny, 0.0, 1.0 }, b[4] = { nx, ny, 1.0, 1.0 }; double h0[4], h1[4];
    VecMat(a, vpInv, h0); VecMat(b, vpInv, h1);
    *p0 = V3{ h0[0] / h0[3], h0[1] / h0[3], h0[2] / h0[3] };
    *d = V3{ h1[0] / h1[3] - p0->x, h1[1] / h1[3] - p0->y, h1[2] / h1[3] - p0->z };
}
inline bool PickFromDeviceDepth(double px, double py, double depth, const double* vp, double w, double h, V3* out) {
    double inv[16]; if (!MatInv(vp, inv)) return false;
    const double u = (px + 0.5) / w, v = (py + 0.5) / h;
    const double a[4] = { 2 * u - 1, 1 - 2 * v, depth, 1.0 }; double hh[4]; VecMat(a, inv, hh);
    *out = V3{ hh[0] / hh[3], hh[1] / hh[3], hh[2] / hh[3] };
    return true;
}
// The pixel ray against the horizontal plane y = planeY; false when the ray never meets it ahead of the camera (sky).
inline bool PickPlane(double px, double py, double planeY, const double* vp, double w, double h, V3* out) {
    double inv[16]; if (!MatInv(vp, inv)) return false;
    V3 p0, d; PixelRay(px, py, inv, w, h, &p0, &d);
    if (std::fabs(d.y) < 1e-12) return false;
    const double t = (planeY - p0.y) / d.y;
    if (t < 0) return false;
    *out = V3{ p0.x + t * d.x, p0.y + t * d.y, p0.z + t * d.z };
    return true;
}
// The ground pick (W6): the ray through the pixel meets the plane through planeY (the selection's mean ground height), then `iters`
// refinements re-cut the ray at the ground height under the last hit (ground(x, z, &y): the game's ground projector). The answer is
// always ON the ray, so it projects back onto the cursor exactly; `residual` = |ground height under it - its y| says how well it sits on
// the terrain (0 on flat ground; it shrinks each step where the terrain is flatter than the ray). False: the ray misses the plane.
template <class Ground>
bool PickGround(double px, double py, double planeY, const double* vp, double w, double h, Ground ground, int iters, V3* out, double* residual = nullptr) {
    V3 hit; if (!PickPlane(px, py, planeY, vp, w, h, &hit)) return false;
    double res = 0;
    for (int i = 0; i <= iters; ++i) {
        double gy = 0;
        if (!ground(hit.x, hit.z, &gy)) { res = -1; break; }   // no height there (off the map): keep the last hit
        res = std::fabs(gy - hit.y);
        if (i == iters || res < 1e-4) break;
        V3 next; if (!PickPlane(px, py, gy, vp, w, h, &next)) break;
        hit = next;
    }
    *out = hit; if (residual) *residual = res;
    return true;
}

// ------------------------------------------------------------------------------------------------ bearings
inline V2 Facing(double bDeg) { const double r = Rad(bDeg) * BearingSign(); return V2{ std::sin(r), std::cos(r) }; }
inline double BearingOf(double vx, double vz) { return PyMod(Deg(std::atan2(vx, vz)) * BearingSign(), 360.0); }
inline double Wrap180(double a) { a = PyMod(a + 180.0, 360.0) - 180.0; return a == -180.0 ? 180.0 : a; }
inline V2 RotateXZ(double x, double z, double thetaDeg) {                     // facing(b) -> facing(b + theta)
    const double r = Rad(thetaDeg) * BearingSign(), c = std::cos(r), s = std::sin(r);
    return V2{ x * c + z * s, -x * s + z * c };
}

// ------------------------------------------------------------------------------------------------ block transforms
inline V2 Centroid(const std::vector<Unit>& u) {                              // arithmetic mean of the order points (xz)
    V2 c; if (u.empty()) return c;
    for (const Unit& a : u) { c.x += a.x; c.z += a.z; }
    c.x /= (double)u.size(); c.z /= (double)u.size(); return c;
}
// Every unit translates by g1 - g0; bearing and width unchanged (the move after a switch back from rotate).
inline std::vector<Unit> BlockMove(const std::vector<Unit>& u, V2 g0, V2 g1) {
    std::vector<Unit> o = u; const double dx = g1.x - g0.x, dz = g1.z - g0.z;
    for (Unit& a : o) { a.x += dx; a.z += dz; }
    return o;
}
// Rigid rotation about the pivot (default: the centroid): positions AND bearings turn by theta.
inline std::vector<Unit> BlockRotate(const std::vector<Unit>& u, double thetaDeg, const V2* pivot = nullptr) {
    const V2 c = pivot ? *pivot : Centroid(u);
    std::vector<Unit> o = u;
    for (Unit& a : o) { const V2 r = RotateXZ(a.x - c.x, a.z - c.z, thetaDeg); a.x = c.x + r.x; a.z = c.z + r.z; a.bearing = PyMod(a.bearing + thetaDeg, 360.0); }
    return o;
}
// A unit's block depth for drawing and for its centre: max(4, its own depth, else width / 4), the provenance's rule (block_math.py
// footprint; the 4 m floor holds for a given depth too: gesture_vectors.txt line 53, depth 3.03, is drawn 4 deep).
inline double FootDepth(const Unit& u) { return std::max(4.0, u.depth > 0 ? u.depth : u.width * 0.25); }
// The centre of a unit's block on the ground: (x, z) itself, or for a front-referenced unit half the depth behind it.
inline V2 UnitCentre(const Unit& u) {
    if (!u.frontRef) return V2{ u.x, u.z };
    const V2 f = Facing(u.bearing); const double hd = FootDepth(u) / 2.0;
    return V2{ u.x - f.x * hd, u.z - f.z * hd };
}
// One unit turns about its own centre; two or more about the mean of their block centres.
inline V2 RotatePivot(const std::vector<Unit>& u) {
    V2 c; if (u.empty()) return c;
    for (const Unit& a : u) { const V2 k = UnitCentre(a); c.x += k.x; c.z += k.z; }
    c.x /= (double)u.size(); c.z /= (double)u.size(); return c;
}
inline double MeanBearing(const std::vector<Unit>& u) {                        // circular mean; the first unit's for opposed facings
    double sx = 0, sz = 0;
    for (const Unit& a : u) { const V2 f = Facing(a.bearing); sx += f.x; sz += f.z; }
    if (std::hypot(sx, sz) < 1e-9) return u.empty() ? 0.0 : u[0].bearing;
    return BearingOf(sx, sz);
}
// The rotate pivot moved fwdM metres along the block's mean facing (the adapter's pivot offset; 0 = "in place").
inline V2 RotatePivotFwd(const std::vector<Unit>& u, double fwdM) {
    V2 c = RotatePivot(u);
    if (u.empty() || fwdM == 0.0) return c;
    const V2 f = Facing(MeanBearing(u));
    c.x += f.x * fwdM; c.z += f.z * fwdM;
    return c;
}
// Rotate by horizontal mouse travel (v3-v5): theta = gain x the horizontal cursor travel since the rotate began; mouse right =
// clockwise from above. gainPer1000 = degrees per 1000 px at a 3840-wide client; other widths scale by the same screen fraction.
// Not wrapped: theta is absolute, so travelling back to the start x returns the pose exactly (no drift).
const double kRotRefWidth = 3840.0;
const double kRotGainDefault = 225.0;   // deg per 1000 px at 3840: 90 deg over 400 px
inline double DegPerPx(double w, double gainPer1000) { return gainPer1000 / 1000.0 * (kRotRefWidth / (w > 0 ? w : kRotRefWidth)); }
inline double DxAngle(double pxDx, double w, double gainPer1000) { return pxDx * DegPerPx(w, gainPer1000); }
inline double DxAngleSigned(double pxDx, double w, double gainPer1000, int sign) { return (sign < 0 ? -1.0 : 1.0) * DxAngle(pxDx, w, gainPer1000); }
// The orbit: the pose turned rigidly by theta about the pivot fixed at the start of the rotate.
inline std::vector<Unit> OrbitPose(const std::vector<Unit>& pose, V2 pivot, double theta) { return BlockRotate(pose, theta, &pivot); }

// ------------------------------------------------------------------------------------------------ footprints
// Block rectangle corners (xz), width across the front, depth front to back; corner order (right, forward) half-extents
// (-1, 1), (1, 1), (1, -1), (-1, -1): front-left, front-right, back-right, back-left.
inline void Footprint(const Unit& u, V2 out[4]) {
    const double d = FootDepth(u);
    const V2 f = Facing(u.bearing), r = Facing(u.bearing + 90.0);
    const double hw = u.width / 2.0, hd = d / 2.0;
    const double cx = u.frontRef ? u.x - f.x * hd : u.x, cz = u.frontRef ? u.z - f.z * hd : u.z;
    static const int s[4][2] = { { -1, 1 }, { 1, 1 }, { 1, -1 }, { -1, -1 } };
    for (int i = 0; i < 4; ++i) out[i] = V2{ cx + s[i][0] * hw * r.x + s[i][1] * hd * f.x, cz + s[i][0] * hw * r.z + s[i][1] * hd * f.z };
}
// Two convex quads overlap (separating-axis test on the 4 edge normals); gapM: they must also be this far apart.
inline bool QuadsOverlap(const V2 a[4], const V2 b[4], double gapM = 0.0) {
    const V2* q[2] = { a, b };
    for (int s = 0; s < 2; ++s)
        for (int e = 0; e < 4; ++e) {
            const V2 p0 = q[s][e], p1 = q[s][(e + 1) % 4];
            const double nx = -(p1.z - p0.z), nz = p1.x - p0.x, nl = std::hypot(nx, nz);
            if (nl < 1e-12) continue;
            double amin = 1e30, amax = -1e30, bmin = 1e30, bmax = -1e30;
            for (int i = 0; i < 4; ++i) {
                const double pa = (a[i].x * nx + a[i].z * nz) / nl, pb = (b[i].x * nx + b[i].z * nz) / nl;
                amin = std::fmin(amin, pa); amax = std::fmax(amax, pa); bmin = std::fmin(bmin, pb); bmax = std::fmax(bmax, pb);
            }
            if (amax + gapM <= bmin || bmax + gapM <= amin) return false;
        }
    return true;
}
inline bool UnitsOverlap(const Unit& a, const Unit& b, double gapM = 0.0) { V2 fa[4], fb[4]; Footprint(a, fa); Footprint(b, fb); return QuadsOverlap(fa, fb, gapM); }

// ------------------------------------------------------------------------------------------------ the line layout (W6)
// Alt+drag = move to the drawn line from a (the press) to b (the cursor):
//   - shorter than shortM: every unit keeps its width and facing, the block's centre (mean order point) moves to a;
//   - else the facing is the line's normal on the side the selection already faces (its mean facing), the units take their current
//     left-to-right order across that facing (ties: the feed's order), each gets an equal share L / n of the line as its frontage,
//     clamped to its own [minWidth, maxWidth], centred in its share; when the clamped widths add up to more than L (minimum clamps)
//     they stand edge to edge, centred on the line's middle. The front edge of every block is on the line. The depth keeps the
//     block's area (depth x width); a unit without a depth keeps none (FootDepth's default applies).
// One unit: its frontage is the line length (clamped), centred on the line.
struct Layout { std::vector<Unit> t; double length = 0, bearing = 0; bool shortDrag = false; std::vector<size_t> order; };
inline double ClampWidth(const Unit& u, double w) {
    if (u.minWidth > 0 && w < u.minWidth) w = u.minWidth;
    if (u.maxWidth > 0 && w > u.maxWidth) w = u.maxWidth;
    return w;
}
inline Layout LineLayout(const std::vector<Unit>& u, V2 a, V2 b, double shortM) {
    Layout L; const size_t n = u.size();
    if (!n) return L;
    L.length = std::hypot(b.x - a.x, b.z - a.z);
    if (L.length < shortM || L.length < 1e-6) {
        L.shortDrag = true; L.t = BlockMove(u, Centroid(u), a); L.bearing = MeanBearing(u);
        for (size_t i = 0; i < n; ++i) L.order.push_back(i);
        return L;
    }
    const double dx = (b.x - a.x) / L.length, dz = (b.z - a.z) / L.length;
    const V2 mf = Facing(MeanBearing(u));
    double nx = dz, nz = -dx;                                            // one normal of the line ...
    if (nx * mf.x + nz * mf.z < 0) { nx = -nx; nz = -nz; }               // ... the one on the side the selection faces
    L.bearing = BearingOf(nx, nz);
    const V2 f = Facing(L.bearing), r = Facing(L.bearing + 90.0);
    for (size_t i = 0; i < n; ++i) L.order.push_back(i);
    std::stable_sort(L.order.begin(), L.order.end(), [&](size_t i, size_t j) { return u[i].x * r.x + u[i].z * r.z < u[j].x * r.x + u[j].z * r.z - 1e-9; });
    const bool aLeft = a.x * r.x + a.z * r.z <= b.x * r.x + b.z * r.z;
    const V2 left = aLeft ? a : b;
    const double share = L.length / (double)n;
    std::vector<double> w(n); double total = 0;
    for (size_t k = 0; k < n; ++k) { w[k] = ClampWidth(u[L.order[k]], share); total += w[k]; }
    const bool packed = total > L.length + 1e-9;
    const double mx = (a.x + b.x) / 2, mz = (a.z + b.z) / 2;
    double s = -total / 2;                                               // packed: along r from the middle
    L.t = u;
    for (size_t k = 0; k < n; ++k) {
        const size_t i = L.order[k];
        double cx, cz;
        if (packed) { const double c = s + w[k] / 2; s += w[k]; cx = mx + r.x * c; cz = mz + r.z * c; }
        else { const double c = (k + 0.5) * share; cx = left.x + r.x * c; cz = left.z + r.z * c; }
        Unit& t = L.t[i];
        if (u[i].depth > 0 && u[i].width > 0) t.depth = u[i].depth * u[i].width / w[k];
        t.width = w[k]; t.bearing = L.bearing;
        if (t.frontRef) { t.x = cx; t.z = cz; }
        else { const double hd = FootDepth(t) / 2; t.x = cx - f.x * hd; t.z = cz - f.z * hd; }
    }
    return L;
}

}  // namespace gest
}  // namespace wsp

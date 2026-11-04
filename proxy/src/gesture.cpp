// gesture.cpp - the gesture layer's driver (W6): a stage in the RmlUi host's window subclass and Present chain (ui_host.cpp), between
// the RmlUi panels and the game. A left press with the move or rotate binding (the adapter's modifier sets, Alt and Alt+Ctrl in the
// provenance) over the world starts a gesture: the move draws the selection onto the line the drag draws, the rotate turns it in place by
// horizontal travel, a footprint preview is drawn while the button is down, and the release sends one order per accepted unit through the
// adapter, once, from the next Present. Pure decisions in gesture_*.h (host-tested by test_gesture.cpp); contract docs/PROXY_GESTURES.md.
// Ported in design from empire-remastered rml_mod/src/controls.cpp without its depth-prepass pick, camera shader capture, engine
// markers, reach search or sound gate.
//
// controls.gestures=0, ui.enabled=0 or no GestureAdapter: GestureMessage returns "pass" at once and GesturePresent does nothing; no
// hook of its own (the RmlUi host's are the only ones, and W2 keeps them out entirely while ui.enabled=0).
// Threads: the window thread (messages, the eligibility and pick calls into the adapter), Present (commit, preview) and the ctl thread
// (sends window messages and reads state; it never calls the adapter: a probe message makes the window thread do it). State under s_lock.
#include "ui_d3d9.h"
#include "gesture_host.h"
#include "ui_host.h"
#include "gesture_feed.h"
#include "gesture_plan.h"
#include "devcore.h"
#include "adapter.h"
#include <cstdio>
#include <vector>

namespace wsp {
namespace {
using namespace gest;

SRWLOCK s_lock = SRWLOCK_INIT;
// B58 a: the thread that holds s_lock (0: none). Set after acquiring, cleared before releasing, so only the owning thread can ever read its
// own id here: a callback that sends a window message to the game from that thread re-enters GestureMessage and is recognised, never waited on.
volatile DWORD s_lockOwner = 0;
volatile LONG s_reentered = 0;         // messages passed untouched because the lock owner sent them (reported in gesture info)
volatile LONG s_ownsMouse = 0;         // B53: a gesture holds the buttons; GestureMessage publishes it under s_lock, GestureOwnsMouse reads it
struct Lock {
    Lock() { AcquireSRWLockExclusive(&s_lock); s_lockOwner = GetCurrentThreadId(); }
    ~Lock() { s_lockOwner = 0; ReleaseSRWLockExclusive(&s_lock); }
};

bool s_key = false, s_on = false;
std::string s_offWhy = "not initialised (the proxy is in pass-through)";
const GestureAdapter* s_ad = nullptr;
HWND s_hwnd = nullptr;
UINT s_probeMsg = 0;

Machine s_m;
Planner s_pl;
std::vector<UnitPlan> s_plan;
V2 s_g; double s_planeY = 0;
std::string s_lastWhy;                 // the last press that could not start, or the last probe
struct Counters {
    long long passed = 0, swallowed = 0, noButton = 0, presses = 0, inert = 0, begins = 0, switches = 0, cancels = 0, replays = 0,
              commits = 0, ordersSent = 0, ordersRefused = 0;
} C;
std::vector<Order> s_pending; bool s_commitPending = false;
long s_commitSeq = 0, s_commitDone = 0; int s_commitSent = 0; std::string s_commitWhy;
HANDLE s_commitEvt = nullptr;
volatile LONG s_injectMods = -1;       // the ctl verb's modifier set for the messages it sends (-1: read the keyboard)
bool s_ctlHeld = false;                // B58 c: the stage took the last ctl press (phase Pending or Active)
int s_ctlX = 0, s_ctlY = 0;
uint64_t s_previewFrames = 0; size_t s_lastDrawn = 0, s_lastHidden = 0;
std::string s_probe;                   // the window thread's answer to a probe (JSON members)

unsigned ReadMods() {
    const LONG inj = s_injectMods;
    if (inj >= 0) return (unsigned)inj;
    unsigned m = 0;
    if (GetKeyState(VK_MENU) & 0x8000) m |= kModAlt;
    if (GetKeyState(VK_CONTROL) & 0x8000) m |= kModCtrl;
    if (GetKeyState(VK_SHIFT) & 0x8000) m |= kModShift;
    return m;
}
bool Client(double& w, double& h) {
    RECT rc; if (!s_hwnd || !GetClientRect(s_hwnd, &rc) || rc.right <= 0 || rc.bottom <= 0) return false;
    w = rc.right; h = rc.bottom; return true;
}
bool CameraNow(double w, double h, double* vp, std::string& why) {
    GestureCam gc{};
    if (!s_ad->cameraRead(gc, why)) { if (why.empty()) why = "the camera is not readable"; return false; }
    Camera c; c.pos = V3{ gc.pos[0], gc.pos[1], gc.pos[2] }; c.target = V3{ gc.target[0], gc.target[1], gc.target[2] }; c.fovYDeg = gc.fovYDeg; c.w = w; c.h = h;
    if (!CameraVP(c, vp)) { why = "the camera pose cannot be inverted (straight down, or no field of view)"; return false; }
    return true;
}
bool GroundY(double x, double z, double* y) { double v = 0; if (!s_ad->groundAt(x, z, v)) return false; *y = v; return true; }
bool Pick(int px, int py, V2& g, std::string& why) {
    double w = 0, h = 0, vp[16];
    if (!Client(w, h)) { why = "no client area"; return false; }
    if (!CameraNow(w, h, vp, why)) return false;
    V3 hit; double res = 0;
    if (!PickGround(px, py, s_planeY, vp, w, h, GroundY, 3, &hit, &res)) { why = "no ground under the cursor (sky)"; return false; }
    g = V2{ hit.x, hit.z };
    return true;
}
std::vector<Unit> Selection(std::string& why) {
    std::vector<GestureUnitIn> in; std::vector<Unit> out;
    if (!s_ad->selection(in, why)) { if (why.empty()) why = "the selection is not readable"; return out; }
    for (const GestureUnitIn& a : in) {
        Unit u; u.id = a.id; u.x = a.x; u.y = a.y; u.z = a.z; u.bearing = a.bearing; u.width = a.width; u.depth = a.depth;
        u.minWidth = a.minWidth; u.maxWidth = a.maxWidth; u.frontRef = a.frontRef; out.push_back(u);
    }
    if (out.empty()) why = "empty selection (no orderable unit selected)";
    return out;
}
// The eligibility of a press that would start a gesture, and on success the planner's start. Window thread, under s_lock.
bool PressEligible(int px, int py, unsigned mods, std::string& why) {
    std::string sw;
    const GestureScene sc = s_ad->scene(sw);
    if (sc == GestureScene::Deployment) { why = "deployment: gestures are inert" + (sw.empty() ? std::string() : " (" + sw + ")"); return false; }
    if (sc != GestureScene::Eligible) { why = "ineligible scene" + (sw.empty() ? std::string() : ": " + sw); return false; }
    const std::vector<Unit> sel = Selection(why);
    if (sel.empty()) return false;
    double y = 0; for (const Unit& u : sel) y += u.y; s_planeY = y / (double)sel.size();
    V2 g; if (!Pick(px, py, g, why)) return false;
    s_g = g;
    const Kind k = s_m.KindFor(mods);
    s_pl.Begin(sel, k == kNone ? kMove : k, g, px);
    return true;
}
void Rebuild() {
    V2 g; std::string why;
    if (Pick(s_m.x, s_m.y, g, why)) s_g = g;   // a cursor over the sky keeps the last ground point
    auto check = [](const Unit& t, std::string& w) {
        if (!s_ad->placeable) return true;
        const GestureOrderOut o{ t.id, t.x, t.z, t.bearing, t.width };
        return s_ad->placeable(o, w);
    };
    s_plan = MakePlan(s_pl.Pose(s_g, s_m.x), GroundY, check);
}
std::string Probe() {   // the window thread (the probe message): why the layer would be inert now
    std::string why, sw; char b[256];
    const GestureScene sc = s_ad->scene(sw);
    std::string selWhy; const std::vector<Unit> sel = Selection(selWhy);
    double w = 0, h = 0, vp[16]; std::string camWhy; bool cam = Client(w, h) && CameraNow(w, h, vp, camWhy);
    if (sc == GestureScene::Deployment) why = "deployment";
    else if (sc != GestureScene::Eligible) why = "ineligible scene" + (sw.empty() ? std::string() : ": " + sw);
    else if (sel.empty()) why = selWhy;
    else if (!cam) why = "camera: " + camWhy;
    snprintf(b, sizeof b, "\"scene\": \"%s\", \"selected\": %zu, \"camera\": %s, ", sc == GestureScene::Eligible ? "eligible" : sc == GestureScene::Deployment ? "deployment" : "ineligible",
             sel.size(), cam ? "true" : "false");
    return b + std::string("\"inert_why\": ") + JStr(why);
}

std::string PlanJson() {   // under s_lock
    std::string j = "\"plan\": {\"kind\": " + JStr(KindName(s_m.kind)) + ", \"phase\": " + JStr(PhaseName(s_m.phase)) + ", \"units\": [";
    char b[400]; bool first = true;
    for (const UnitPlan& p : s_plan) {
        snprintf(b, sizeof b, "%s{\"id\": %u, \"x\": %.3f, \"y\": %.3f, \"z\": %.3f, \"bearing\": %.3f, \"width\": %.3f, \"depth\": %.3f, \"refused\": %s, \"why\": %s, "
                 "\"corners\": [[%.3f, %.3f, %.3f], [%.3f, %.3f, %.3f], [%.3f, %.3f, %.3f], [%.3f, %.3f, %.3f]]}",
                 first ? "" : ", ", p.t.id, p.t.x, p.t.y, p.t.z, p.t.bearing, p.t.width, FootDepth(p.t), p.refused ? "true" : "false", JStr(p.why).c_str(),
                 p.corners[0].x, p.corners[0].y, p.corners[0].z, p.corners[1].x, p.corners[1].y, p.corners[1].z,
                 p.corners[2].x, p.corners[2].y, p.corners[2].z, p.corners[3].x, p.corners[3].y, p.corners[3].z);
        j += b; first = false;
    }
    snprintf(b, sizeof b, "], \"refused\": %zu, \"press\": [%d, %d], \"cursor\": [%d, %d], \"ground\": [%.3f, %.3f], \"theta\": %.3f, \"segments\": %d}",
             RefusedCount(s_plan), s_m.x0, s_m.y0, s_m.x, s_m.y, s_g.x, s_g.z, s_pl.Theta(s_m.x), s_pl.segments);
    return j + b;
}
std::string CountersJson(const Counters& c) {
    char b[400];
    snprintf(b, sizeof b, "{\"passed\": %lld, \"swallowed\": %lld, \"passed_no_button\": %lld, \"presses\": %lld, \"inert_presses\": %lld, \"begins\": %lld, "
             "\"switches\": %lld, \"cancels\": %lld, \"replays\": %lld, \"commits\": %lld, \"orders_sent\": %lld, \"orders_refused\": %lld}",
             c.passed, c.swallowed, c.noButton, c.presses, c.inert, c.begins, c.switches, c.cancels, c.replays, c.commits, c.ordersSent, c.ordersRefused);
    return b;
}
Counters Delta(const Counters& a, const Counters& b) {
    Counters d;
    d.passed = b.passed - a.passed; d.swallowed = b.swallowed - a.swallowed; d.noButton = b.noButton - a.noButton; d.presses = b.presses - a.presses;
    d.inert = b.inert - a.inert; d.begins = b.begins - a.begins; d.switches = b.switches - a.switches; d.cancels = b.cancels - a.cancels;
    d.replays = b.replays - a.replays; d.commits = b.commits - a.commits; d.ordersSent = b.ordersSent - a.ordersSent; d.ordersRefused = b.ordersRefused - a.ordersRefused;
    return d;
}
std::string InfoJson() {   // under s_lock
    char b[800];
    snprintf(b, sizeof b, "\"gesture\": {\"on\": %s, \"key\": %s, \"adapter\": %s, \"off_why\": %s, \"window\": %s, \"phase\": \"%s\", \"kind\": \"%s\", "
             "\"bindings\": {\"move\": %u, \"rotate\": %u}, \"drag_px\": %d, \"short_drag_m\": %.2f, \"pivot_fwd_m\": %.2f, \"last_why\": %s, "
             "\"preview_frames\": %llu, \"preview_last_drawn\": %zu, \"preview_last_hidden\": %zu, \"reentered\": %ld, \"commit\": {\"seq\": %ld, \"done\": %ld, \"sent\": %d, \"why\": %s}, \"counters\": ",
             s_on ? "true" : "false", s_key ? "true" : "false", s_ad ? "true" : "false", JStr(s_on ? "" : s_offWhy).c_str(), s_hwnd ? "true" : "false",
             PhaseName(s_m.phase), KindName(s_m.kind), s_m.moveMods, s_m.rotateMods, s_m.dragPx, s_pl.p.shortDragM, s_pl.p.pivotFwdM, JStr(s_lastWhy).c_str(),
             (unsigned long long)s_previewFrames, s_lastDrawn, s_lastHidden, (long)s_reentered, s_commitSeq, s_commitDone, s_commitSent, JStr(s_commitWhy).c_str());
    return b + CountersJson(C) + "}";
}

// ---- the preview ---------------------------------------------------------------------------------------------------------------
void Draw(IDirect3DDevice9* dev, const Overlay& ov, int bbW, int bbH) {
    IDirect3DStateBlock9* sb = nullptr;
    if (FAILED(dev->CreateStateBlock(D3DSBT_ALL, &sb)) || !sb) return;
    IDirect3DSurface9 *rt = nullptr, *ds = nullptr, *bb = nullptr;
    dev->GetRenderTarget(0, &rt); dev->GetDepthStencilSurface(&ds); dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &bb);
    if (bb) dev->SetRenderTarget(0, bb);
    dev->SetDepthStencilSurface(nullptr);   // no depth test; a game depth surface of another size must not meet the back buffer
    if (SUCCEEDED(dev->BeginScene())) {
        D3DVIEWPORT9 vp{ 0, 0, (DWORD)bbW, (DWORD)bbH, 0.f, 1.f };
        dev->SetViewport(&vp);
        dev->SetVertexShader(nullptr); dev->SetPixelShader(nullptr);
        dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_DIFFUSE);
        dev->SetTexture(0, nullptr);
        const DWORD rs[][2] = { { D3DRS_ZENABLE, FALSE }, { D3DRS_ZWRITEENABLE, FALSE }, { D3DRS_LIGHTING, FALSE }, { D3DRS_CULLMODE, D3DCULL_NONE },
            { D3DRS_FOGENABLE, FALSE }, { D3DRS_ALPHATESTENABLE, FALSE }, { D3DRS_ALPHABLENDENABLE, TRUE }, { D3DRS_SEPARATEALPHABLENDENABLE, FALSE },
            { D3DRS_SRCBLEND, D3DBLEND_SRCALPHA }, { D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA }, { D3DRS_BLENDOP, D3DBLENDOP_ADD },
            { D3DRS_COLORWRITEENABLE, 0xF }, { D3DRS_SRGBWRITEENABLE, FALSE }, { D3DRS_FILLMODE, D3DFILL_SOLID }, { D3DRS_STENCILENABLE, FALSE },
            { D3DRS_SCISSORTESTENABLE, FALSE }, { D3DRS_CLIPPING, TRUE }, { D3DRS_ANTIALIASEDLINEENABLE, FALSE } };
        for (const auto& r : rs) dev->SetRenderState((D3DRENDERSTATETYPE)r[0], r[1]);
        dev->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1); dev->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
        dev->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1); dev->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
        dev->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE); dev->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
        if (!ov.tris.empty()) dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST, (UINT)(ov.tris.size() / 3), ov.tris.data(), sizeof(Vtx));
        if (!ov.lines.empty()) dev->DrawPrimitiveUP(D3DPT_LINELIST, (UINT)(ov.lines.size() / 2), ov.lines.data(), sizeof(Vtx));
        dev->EndScene();
    }
    dev->SetRenderTarget(0, rt); dev->SetDepthStencilSurface(ds);
    sb->Apply(); sb->Release();
    for (IDirect3DSurface9* s : { rt, ds, bb })
        if (s) s->Release();
}

bool Send(UINT msg, WPARAM wp, LPARAM lp, double timeoutS) {
    DWORD_PTR res = 0;
    return SendMessageTimeoutW(s_hwnd, msg, wp, lp, SMTO_ABORTIFHUNG, (UINT)(timeoutS * 1000), &res) != 0;
}
WPARAM MkFlags(unsigned mods) { return (mods & kModCtrl ? MK_CONTROL : 0) | (mods & kModShift ? MK_SHIFT : 0); }

} // namespace

bool GestureOn() { return s_on; }
void GestureSetWindow(void* hwnd) {
    if (ReenteredBy(s_lockOwner, GetCurrentThreadId())) return;   // B58 a: called from a callback under the lock; the window is set already or will be
    Lock l; if (!s_hwnd) s_hwnd = (HWND)hwnd;
}

void GestureInit() {
    Runtime& rt = Rt();
    Lock l;
    s_key = rt.cfg.Bool("controls.gestures");
    s_ad = Adapter().gesture;
    if (!s_key) { s_offWhy = "config off (controls.gestures=0)"; if (s_ad) LOGI("gesture: controls.gestures=0: the layer is inert"); return; }
    if (!s_ad) { s_offWhy = "no adapter (the game has no GestureAdapter)"; LOGW("gesture: controls.gestures=1 but %s: the layer is inert", s_offWhy.c_str()); return; }
    if (!rt.plan.d3dHooks) { s_offWhy = "the plan forbids D3D hooks (pass-through)"; LOGW("gesture: %s: the layer is inert", s_offWhy.c_str()); return; }
    if (!rt.cfg.Bool("ui.enabled")) {   // W2 keeps "ui.enabled=0: nothing hooked" (test_ui_core lints it): the stage needs the host's hooks
        s_offWhy = "the RmlUi host is off (ui.enabled=0): the gesture stage rides on its window subclass and Present chain"; LOGW("gesture: %s: the layer is inert", s_offWhy.c_str()); return;
    }
    if (!s_ad->scene || !s_ad->cameraRead || !s_ad->groundAt || !s_ad->selection || !s_ad->commit) {
        s_offWhy = "the GestureAdapter lacks a callback (scene, cameraRead, groundAt, selection and commit are required)"; LOGE("gesture: %s: the layer is inert", s_offWhy.c_str()); return;
    }
    s_m.dragPx = s_ad->dragPx > 0 ? s_ad->dragPx : 6;
    if (s_ad->moveMods) s_m.moveMods = s_ad->moveMods;
    if (s_ad->rotateMods) s_m.rotateMods = s_ad->rotateMods;
    if (s_m.moveMods == s_m.rotateMods) s_m.rotateMods = 0;   // one set cannot mean both: the move wins
    s_pl.p.shortDragM = s_ad->shortDragM > 0 ? s_ad->shortDragM : 3.0;
    s_pl.p.pivotFwdM = s_ad->pivotFwdM;
    s_pl.p.rotGain = s_ad->rotGain > 0 ? s_ad->rotGain : kRotGainDefault;
    s_pl.p.rotSign = s_ad->rotSign < 0 ? -1 : 1;
    s_commitEvt = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    s_probeMsg = RegisterWindowMessageW(L"wsp.gesture.probe");
    s_on = true; s_offWhy.clear();
    LOGI("gesture: on: drag %d px, short drag %.1f m, bindings move %u rotate %u (1 Alt, 2 Ctrl, 4 Shift), pivot %.2f m, gain %.0f, sign %d",
         s_m.dragPx, s_pl.p.shortDragM, s_m.moveMods, s_m.rotateMods, s_pl.p.pivotFwdM, s_pl.p.rotGain, s_pl.p.rotSign);
}

GestureMsgResult GestureMessage(void* hwnd, uint32_t msg, uint32_t wp, intptr_t lp, bool mouseToEngine) {
    GestureMsgResult r; r.wp = wp;
    if (!s_on) return r;
    // B58 a: a callback of the adapter (called under s_lock, which is not re-entrant) sent a message to the window on this very thread. It
    // passes to the game untouched: no state change, no wait.
    if (ReenteredBy(s_lockOwner, GetCurrentThreadId())) {
        if (InterlockedIncrement(&s_reentered) == 1) LOGW("gesture: an adapter callback sent window message 0x%04X while the stage held its lock: passed to the game untouched (counted as reentered)", msg);
        return r;
    }
    const bool probe = s_probeMsg && msg == s_probeMsg;
    if (!probe && Classify(msg, wp, lp, (uintptr_t)hwnd) == kClsOther) return r;
    Lock l;
    if (!s_hwnd) s_hwnd = (HWND)hwnd;
    if (probe) { s_probe = Probe(); r.action = kSwallow; return r; }   // our own message: never the game's
    const unsigned mods = ReadMods();
    const int x = (int)(short)LOWORD((DWORD)lp), y = (int)(short)HIWORD((DWORD)lp);
    FeedOut f = Feed(s_m, msg, wp, x, y, mods, mouseToEngine, false, false, kNone, lp, (uintptr_t)hwnd);
    if (f.needsEligibility) {
        ++C.presses;
        std::string why; const bool ok = PressEligible(x, y, mods, why);
        if (!ok) { ++C.inert; s_lastWhy = why; }
        f = Feed(s_m, msg, wp, x, y, mods, mouseToEngine, true, ok, kNone, lp, (uintptr_t)hwnd);
    }
    if (f.fed) {
        const Out& o = f.sm;
        if (o.kindSwitch) {
            ++C.switches;
            if (msg == kWmMouseMove) { V2 g; std::string why; if (Pick(s_m.x, s_m.y, g, why)) s_g = g; }
            s_pl.Switch(s_m.kind, s_g, s_m.x, s_m.phase == kActive);
        }
        if (o.begin) ++C.begins;
        if (o.update || o.commit) Rebuild();
        if (o.commit) {
            s_pending = OrdersOf(s_plan); s_commitPending = true; ++s_commitSeq; ++C.commits;
            C.ordersRefused += (long long)RefusedCount(s_plan);
            if (s_commitEvt) ResetEvent(s_commitEvt);
        }
        if (o.cancel) ++C.cancels;
        if (o.replayClick) { ++C.replays; r.replay = true; r.rx = s_m.x0; r.ry = s_m.y0; }
        if (s_m.phase == kIdle || s_m.phase == kDrain) { if (!o.commit) s_plan.clear(); }
    }
    r.action = f.action;
    if (f.action == kSwallow) ++C.swallowed; else ++C.passed;
    if (f.action == kPassNoButton) { r.wp = ClearLButton(wp); ++C.noButton; }
    InterlockedExchange(&s_ownsMouse, (s_m.phase != kIdle || s_m.swallowRUp) ? 1 : 0);   // B53: after every message fed
    return r;
}

bool GestureOwnsMouse() { return s_ownsMouse != 0; }   // B53: one published word, not two machine fields read unlocked

void GesturePresent(void* device, int bbW, int bbH) {
    if (!s_on || !device) return;
    IDirect3DDevice9* dev = (IDirect3DDevice9*)device;
    std::vector<Order> commit; bool doCommit = false; long seq = 0;
    { Lock l; if (s_commitPending) { commit.swap(s_pending); s_commitPending = false; doCommit = true; seq = s_commitSeq; } }
    if (doCommit) {   // the release's orders, once, on the Present thread (the engine thread in the games proven so far)
        std::vector<GestureOrderOut> o;
        for (const Order& a : commit) o.push_back(GestureOrderOut{ a.id, a.x, a.z, a.bearing, a.width });
        std::string why; const int sent = o.empty() ? 0 : s_ad->commit(o.data(), o.size(), why);
        LOGI("gesture: commit #%ld: %d of %zu orders sent%s%s", seq, sent, o.size(), why.empty() ? "" : ": ", why.c_str());
        Lock l; s_commitDone = seq; s_commitSent = sent; s_commitWhy = o.empty() ? "every unit refused: no order" : why; C.ordersSent += sent > 0 ? sent : 0;
        if (s_commitEvt) SetEvent(s_commitEvt);
    }
    Overlay ov;
    {
        Lock l;
        if (s_m.phase != kActive || s_plan.empty() || bbW <= 0 || bbH <= 0) return;
        double vp[16]; std::string why;
        if (!CameraNow(bbW, bbH, vp, why)) return;
        ov = BuildOverlay(s_plan, vp, bbW, bbH);
        ++s_previewFrames; s_lastDrawn = ov.drawn; s_lastHidden = ov.hidden;
    }
    if (ov.drawn) Draw(dev, ov, bbW, bbH);
}

bool GestureCtl(const std::string& arg, double timeoutS, std::string& result, std::string& why, bool& refused) {
    refused = false;
    const GestureArgs a = ParseGestureArgs(arg);
    if (!a.error.empty()) { why = a.error; refused = true; return false; }
    if (a.op == "info") {
        HWND w; bool on; { Lock l; w = s_hwnd; on = s_on; }
        std::string probe = "\"probe\": null";
        if (on && w) { if (Send(s_probeMsg, 0, 0, timeoutS)) { Lock l; probe = "\"probe\": {" + s_probe + "}"; } else probe = "\"probe\": \"the window did not answer\""; }
        Lock l; result = InfoJson() + ", " + probe;
        return true;
    }
    if (!s_on) { why = "the gesture layer is inert: " + s_offWhy; refused = true; return false; }
    if (!UiEnabled()) { why = "the gesture layer is inert: the RmlUi host did not start (ui.dir empty, or the plan forbids D3D hooks)"; refused = true; return false; }
    if (a.op == "plan") { Lock l; result = PlanJson() + ", \"counters\": " + CountersJson(C); return true; }
    { Lock l; if (!s_hwnd) { why = "no game window yet"; return false; } }
    Counters before; long seqBefore; { Lock l; before = C; seqBefore = s_commitSeq; }
    InterlockedExchange(&s_injectMods, (LONG)a.mods);
    bool ok = true;
    const WPARAM mk = MkFlags(a.mods);
    if (a.op == "press") {
        const LPARAM lp = MAKELPARAM((WORD)(short)a.x, (WORD)(short)a.y);
        ok = Send(WM_MOUSEMOVE, mk, lp, timeoutS) && Send(WM_LBUTTONDOWN, MK_LBUTTON | mk, lp, timeoutS);
        // B58 c: held only if the stage took the press (a gesture started). An inert press, one over a panel, or one eligibility refused
        // went to the game as a real press; the next `move` is then a plain cursor move, not a drag, and the driver sends `release`.
        Lock l; s_ctlHeld = (s_m.phase == kPending || s_m.phase == kActive); s_ctlX = a.x; s_ctlY = a.y;
    } else if (a.op == "move") {
        ok = Send(WM_MOUSEMOVE, (s_ctlHeld ? MK_LBUTTON : 0) | mk, MAKELPARAM((WORD)(short)a.x, (WORD)(short)a.y), timeoutS);
        s_ctlX = a.x; s_ctlY = a.y;
    } else if (a.op == "release") {
        ok = Send(WM_LBUTTONUP, mk, MAKELPARAM((WORD)(short)a.x, (WORD)(short)a.y), timeoutS);
        s_ctlHeld = false; s_ctlX = a.x; s_ctlY = a.y;
    } else if (a.op == "cancel") {
        if (a.how == "right") {
            const LPARAM lp = MAKELPARAM((WORD)(short)s_ctlX, (WORD)(short)s_ctlY);
            ok = Send(WM_RBUTTONDOWN, MK_RBUTTON | (s_ctlHeld ? MK_LBUTTON : 0), lp, timeoutS) && Send(WM_RBUTTONUP, s_ctlHeld ? MK_LBUTTON : 0, lp, timeoutS);
        } else ok = Send(WM_KEYDOWN, VK_ESCAPE, 1, timeoutS) && Send(WM_KEYUP, VK_ESCAPE, (LPARAM)0xC0000001u, timeoutS);
    }
    InterlockedExchange(&s_injectMods, -1);
    if (!ok) { why = "the window did not take the messages within the timeout"; return false; }
    // a release that committed: the readback is the adapter's answer from the next Present
    long seqAfter; { Lock l; seqAfter = s_commitSeq; }
    std::string commit = "\"commit\": null";
    if (seqAfter != seqBefore) {
        const DWORD wait = WaitForSingleObject(s_commitEvt, (DWORD)(timeoutS * 1000));
        Lock l;
        if (wait != WAIT_OBJECT_0 || s_commitDone != seqAfter) { why = "the release was taken but no Present committed the orders within the timeout"; return false; }
        char b[160]; snprintf(b, sizeof b, "\"commit\": {\"seq\": %ld, \"sent\": %d, \"why\": ", s_commitDone, s_commitSent);
        commit = b + JStr(s_commitWhy) + "}";
    }
    Lock l;
    result = std::string("\"held\": ") + (s_ctlHeld ? "true" : "false") + ", \"delta\": " + CountersJson(Delta(before, C)) + ", \"phase\": " + JStr(PhaseName(s_m.phase)) + ", \"kind\": " + JStr(KindName(s_m.kind)) +
             ", \"last_why\": " + JStr(s_lastWhy) + ", " + commit + ", " + PlanJson();
    return true;
}

} // namespace wsp

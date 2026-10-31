// camera.cpp - the battle camera setter (J43, static RE and PC probes in harness/runs/20261030_j43pc): wsp.cam_set(x, y, z, yaw, pitch)
// from the dev Lua bridge calls the active camera mode's own SetTargetAndPosition(target, position) on the engine thread. The mode
// is read through a pointer chain from a global the exe writes (battle owner -> battle -> camera controller -> mode: no detour), and
// its vtable slot is compared with the checked engine_sites row before every call. Decisions are pure (camera.h, host-tested).
// dev.camera off: nothing here reads engine memory and cam_set is refused. Threads: CameraSet runs on the engine thread only (the
// Lua pump); install runs at the first Direct3DCreate9. State under s_cs.
#include "runtime.h"
#include "dev.h"
#include "camera.h"

namespace wsp {
namespace {
CRITICAL_SECTION s_cs;
struct Lock { Lock() { EnterCriticalSection(&s_cs); } ~Lock() { LeaveCriticalSection(&s_cs); } };

bool s_key = false, s_installed = false;
std::string s_sitesWhy = "not installed yet";
const CameraAdapter* s_ad = nullptr;
uintptr_t s_global = 0, s_setFn = 0;
uint32_t s_battleOff = 0, s_ctrlOff = 0, s_modeOff = 0;
int s_sets = 0;

bool Readable(uintptr_t p, size_t n) {
    if (!p) return false;
    MEMORY_BASIC_INFORMATION mbi{};
    if (!VirtualQuery((const void*)p, &mbi, sizeof mbi) || mbi.State != MEM_COMMIT || (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return false;
    return p + n <= (uintptr_t)mbi.BaseAddress + mbi.RegionSize;
}
bool ReadPtr(uintptr_t p, uintptr_t& out) { if (!Readable(p, 4)) return false; out = *(const uintptr_t*)p; return true; }
uint32_t Operand(const char* site, int off) { const uintptr_t a = SiteAddress(site); return a ? *(const uint32_t*)(a + off) : 0; }
bool InExe(uintptr_t p) {
    MEMORY_BASIC_INFORMATION mbi{};
    return p && VirtualQuery((const void*)p, &mbi, sizeof mbi) && mbi.AllocationBase == (void*)GetModuleHandleW(nullptr);
}

// owner = *global; battle = *(owner + a); controller = *(battle + b); mode = *(controller + c); mode's vtable in the exe, its slot
// = the checked SetTargetAndPosition. s_cs held.
bool Mode(uintptr_t& mode, std::string& why) {
    uintptr_t owner = 0, battle = 0, ctrl = 0, vt = 0, slot = 0;
    if (!ReadPtr(s_global, owner) || !owner) { why = "battle owner global empty"; return false; }
    if (!ReadPtr(owner + s_battleOff, battle) || !battle) { why = "no battle (not in a battle?)"; return false; }
    if (!ReadPtr(battle + s_ctrlOff, ctrl) || !ctrl) { why = "the battle has no camera controller"; return false; }
    if (!ReadPtr(ctrl + s_modeOff, mode) || !mode) { why = "the camera controller has no active mode"; return false; }
    if (!ReadPtr(mode, vt) || !InExe(vt)) { why = "camera mode vtable not in the exe (object torn down)"; return false; }
    if (!ReadPtr(vt + 4 * s_ad->setSlot, slot) || slot != s_setFn) {
        char b[160]; snprintf(b, sizeof b, "camera mode %p slot %d is %p, not SetTargetAndPosition %p (another mode class)", (void*)mode, s_ad->setSlot, (void*)slot, (void*)s_setFn);
        why = b; return false;
    }
    return true;
}

using SetFn = void(__thiscall*)(void* mode, const float* target, const float* pos);
} // namespace

void CameraInit(bool key, const CameraAdapter* ad) {
    InitializeCriticalSection(&s_cs);
    s_key = key && ad; s_ad = ad;
    LOGI("camera: dev.camera=%d%s", key ? 1 : 0, key && !ad ? " but the adapter has no camera: off" : "");
}

void CameraInstall() {
    Lock l;
    if (!s_key || s_installed) return;
    const Runtime& rt = Rt();
    if (!rt.plan.engineHooks || !rt.plan.engineReads) { s_sitesWhy = "the exe guard's plan allows no engine calls"; LOGW("camera: not installed: %s", s_sitesWhy.c_str()); return; }
    for (const char* s : { s_ad->chainSite, s_ad->modeSite, s_ad->setSite })
        if (!SiteAddress(s)) { s_sitesWhy = std::string("site ") + s + " not accepted by the patch engine" + (rt.sitesWhy.empty() ? "" : ": " + rt.sitesWhy); LOGE("camera: not installed: %s", s_sitesWhy.c_str()); return; }
    s_global = Operand(s_ad->chainSite, s_ad->globalOperand);
    s_battleOff = Operand(s_ad->chainSite, s_ad->battleOffOperand);
    s_ctrlOff = Operand(s_ad->chainSite, s_ad->controllerOffOperand);
    s_modeOff = Operand(s_ad->modeSite, s_ad->modeOffOperand);
    s_setFn = SiteAddress(s_ad->setSite);
    s_installed = true; s_sitesWhy.clear();
    LOGI("camera: install: owner global %p, battle +0x%x, controller +0x%x, mode +0x%x, SetTargetAndPosition %p (slot %d); sites %s %s %s",
         (void*)s_global, s_battleOff, s_ctrlOff, s_modeOff, (void*)s_setFn, s_ad->setSlot, s_ad->chainSite, s_ad->modeSite, s_ad->setSite);
}

bool CameraSet(const CamPose& p, std::string& why) {
    Lock l;
    if (!s_key) { why = "dev.camera=0"; return false; }
    if (!s_installed) { why = "camera not installed: " + s_sitesWhy; return false; }
    float target[3], pos[3] = { p.x, p.y, p.z };
    if (!CamTargetFor(p, s_ad->targetDistance, target, why)) return false;
    uintptr_t mode = 0;
    if (!Mode(mode, why)) { LOGW("camera: set refused: %s", why.c_str()); return false; }
    ((SetFn)s_setFn)((void*)mode, target, pos);   // the engine thread (the Lua pump): the mode's own setter
    ++s_sets;
    LOGI("camera: set #%d pos (%.3f, %.3f, %.3f) yaw %.3f pitch %.3f -> target (%.3f, %.3f, %.3f) on mode %p", s_sets, p.x, p.y, p.z, p.yaw, p.pitch,
         target[0], target[1], target[2], (void*)mode);
    return true;
}

} // namespace wsp

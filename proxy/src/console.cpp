// console.cpp - the campaign console (J15; route from empire-remastered rml_mod/src/dev_console.cpp, re-found per game): the
// executor's external-handler slot, which the retail exe reads but never writes, gets a forwarder to a CampaignCLI the proxy
// builds with the exe's own ctor on the live campaign context (read through a pointer chain from a global the exe writes: no
// detour). Then the engine's own `CliExecute(line)` reaches the campaign dictionary, from game Lua or from the `console` ctl verb.
// Decisions are pure (console.h, host-tested); every address is a checked engine_sites row (patch_driver.cpp SiteAddress).
// dev.console off: nothing here reads or writes engine memory, and lines are refused. Threads: the forwarder runs on the engine
// thread (inside CliExecute); install, status and on/off run on the control thread or at the first Direct3DCreate9. State under s_cs.
#include "runtime.h"
#include "dev.h"
#include "console.h"

namespace wsp {
namespace {
CRITICAL_SECTION s_cs;
struct Lock { Lock() { EnterCriticalSection(&s_cs); } ~Lock() { LeaveCriticalSection(&s_cs); } };

bool s_key = false, s_on = false, s_sitesOk = false, s_installed = false;
std::string s_sitesWhy;
uintptr_t s_slot = 0, s_ownerGlobal = 0, s_selVtbl = 0, s_cliVtbl = 0, s_ctor = 0, s_execute = 0;
const ConsoleAdapter* s_ad = nullptr;
// our CampaignCLIs: one per campaign context seen (the engine never holds them; their ctor's name string is never freed)
alignas(16) uint8_t s_cliBuf[8][0x80];
int s_cliNext = 0;
uintptr_t s_cli = 0, s_cliCamp = 0, s_selVtblSeen = 0;
int s_gateOff = -1, s_gateSets = 0;
// the last forward, for the verb's result
long s_seq = 0; FwdResult s_last = FwdResult::None; std::string s_lastName, s_lastWhy; int s_hits = 0, s_forwards = 0, s_refusals = 0;

bool Readable(uintptr_t p, size_t n) {
    if (!p) return false;
    MEMORY_BASIC_INFORMATION mbi{};
    if (!VirtualQuery((const void*)p, &mbi, sizeof mbi) || mbi.State != MEM_COMMIT || (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return false;
    return p + n <= (uintptr_t)mbi.BaseAddress + mbi.RegionSize;
}
bool ReadPtr(uintptr_t p, uintptr_t& out) { if (!Readable(p, 4)) return false; out = *(const uintptr_t*)p; return true; }
uintptr_t Operand(const char* site, int off) { const uintptr_t a = SiteAddress(site); return a ? *(const uint32_t*)(a + off) : 0; }

// The chain: owner = *global; campaign = *(owner + off); campaign->selection must be owner's selection sub-object with its vtable.
bool Chain(uintptr_t& camp, std::string& why) {
    uintptr_t owner = 0, sel = 0, vt = 0;
    if (!ReadPtr(s_ownerGlobal, owner) || !owner) { why = "owner global empty (no campaign loaded)"; return false; }
    if (!ReadPtr(owner + s_ad->ownerCampaignOff, camp) || !camp) { why = "owner has no campaign context"; return false; }
    if (!ReadPtr(camp + s_ad->campaignSelectionOff, sel) || sel != owner + s_ad->ownerSelectionOff) { why = "campaign->selection is not the owner's (stale owner)"; return false; }
    // the selection's vtable: the wiring site stores the BASE class's (s_selVtbl, also what the destructor restores); the live object
    // carries a derived one (run 20261029_j15pc c_console_try1), so require only a vtable inside the exe image, and not the base's
    MEMORY_BASIC_INFORMATION mbi{};
    if (!ReadPtr(sel, vt) || !VirtualQuery((const void*)vt, &mbi, sizeof mbi) || mbi.AllocationBase != (void*)GetModuleHandleW(nullptr)) { why = "selection vtable not in the exe (object torn down)"; return false; }
    if (vt == s_selVtbl) { why = "selection has its base vtable (being destroyed)"; return false; }
    s_selVtblSeen = vt;
    return true;
}

using CtorFn = void*(__thiscall*)(void* self, void** ctx);
using ExecFn = bool(__thiscall*)(void* cli, void* name, void* stream);

// A CLI for this campaign context, built once with the exe's ctor; checked before every use.
bool Cli(uintptr_t camp, std::string& why) {
    if (s_cli && s_cliCamp == camp) {
        uintptr_t vt = 0, ctx = 0;
        if (ReadPtr(s_cli, vt) && vt == s_cliVtbl && ReadPtr(s_cli + s_ad->cliCtxOff, ctx) && ctx == camp) return true;
        why = "our CLI changed"; return false;
    }
    if (s_ad->cliSize > sizeof s_cliBuf[0]) { why = "CLI larger than the buffer"; return false; }
    uint8_t* buf = s_cliBuf[s_cliNext]; s_cliNext = (s_cliNext + 1) % 8;
    memset(buf, 0, sizeof s_cliBuf[0]);
    void* ctx = (void*)camp;
    ((CtorFn)s_ctor)(buf, &ctx);
    uintptr_t vt = *(uintptr_t*)buf, ctxv = *(uintptr_t*)(buf + s_ad->cliCtxOff), slot = 0;
    if (vt != s_cliVtbl || ctxv != camp || !ReadPtr(vt + 4 * s_ad->executeSlot, slot) || slot != s_execute) {
        LOGE("console: built CLI at %p is not as expected (vtable %p want %p, ctx %p want %p, Execute slot %p want %p)", buf, (void*)vt,
             (void*)s_cliVtbl, (void*)ctxv, (void*)camp, (void*)slot, (void*)s_execute);
        why = "built CLI not intact"; return false;
    }
    s_cli = (uintptr_t)buf; s_cliCamp = camp;
    LOGI("console: CampaignCLI built at %p for campaign context %p (vtable %p, Execute %p at slot %d)", buf, (void*)camp, (void*)vt, (void*)s_execute, s_ad->executeSlot);
    return true;
}

std::string NameOf(void* name) {   // ca_string: UTF-16, c_str() is the pointer at +8 (the executor's file stage opens it with CreateFileW)
    uintptr_t p = 0;
    if (!ReadPtr((uintptr_t)name + 8, p) || !Readable(p, 2)) return "?";
    std::string s;
    for (int i = 0; i < 120 && Readable(p + 2 * i, 2); ++i) { const wchar_t c = ((const wchar_t*)p)[i]; if (!c) break; s += c < 0x80 ? (char)c : '?'; }
    return s;
}

// --- the forwarder: an object whose vtable the executor calls (vfunc0 = run, vfunc1 = help)
bool __thiscall FwdRun(void*, void* name, void* stream) {
    const std::string n = NameOf(name);
    ConsoleGate g; g.scene = DevSceneNow();   // before s_cs: the dev lock is never taken inside the console lock
    uintptr_t camp = 0, cli = 0; std::string why;
    {
        Lock l;
        g.keyOn = s_key; g.on = s_on; g.sitesOk = s_sitesOk;
        if (g.keyOn && g.on && g.sitesOk && g.scene == "campaign") {
            g.chainOk = Chain(camp, g.chainWhy);
            if (g.chainOk) g.cliOk = Cli(camp, why);
        }
        cli = s_cli;
        const std::string ref = ForwardRefusal(g);
        if (!ref.empty()) {
            ++s_seq; s_lastName = n; ++s_refusals; s_last = FwdResult::Refused; s_lastWhy = ref + (why.empty() ? "" : " (" + why + ")");
            LOGW("console: refused '%s': %s", n.c_str(), s_lastWhy.c_str());
            return false;   // "not handled": the executor goes on as without a handler
        }
    }
    // Most acting handlers return at once unless the campaign context's gate byte is set. Liam 2026-10-29: set it if it is 0, so it
    // is 1 for the length of this one command and restored right after (nothing else in the engine sees it change). In every live
    // campaign so far it was already set (gate_sets 0, engine_facts *.console.handler_gate), so this is a guard, not the usual path.
    volatile uint8_t* gate = s_gateOff > 0 && Readable(camp + s_gateOff, 1) ? (volatile uint8_t*)(camp + s_gateOff) : nullptr;
    const uint8_t gateOld = gate ? *gate : 0;
    if (gate && !gateOld) *gate = 1;
    const bool hit = ((ExecFn)s_execute)((void*)cli, name, stream);   // engine thread, outside the lock (handlers run engine code)
    if (gate && !gateOld) *gate = gateOld;
    Lock l;
    if (gate && !gateOld) ++s_gateSets;
    ++s_seq; s_lastName = n; ++s_forwards; if (hit) ++s_hits;
    s_last = hit ? FwdResult::Hit : FwdResult::Unknown; s_lastWhy.clear();
    LOGI("console: forwarded '%s' -> %s (campaign context %p, gate byte +0x%x %s)", n.c_str(), hit ? "campaign hit" : "unknown to the campaign dictionary",
         (void*)camp, (unsigned)s_gateOff, !gate ? "not set: unreadable" : gateOld ? "already set" : "set for the call, restored to 0");
    return hit;
}
void __thiscall FwdHelp(void*) { LOGI("console: help asked (the campaign dictionary's help is not printed in retail)"); }
void* s_fwdVtbl[2] = { (void*)&FwdRun, (void*)&FwdHelp };
struct { void** vtbl; } s_fwd = { s_fwdVtbl };

bool SetSlot(bool on, std::string& why) {   // s_cs held
    if (!s_installed) { why = "not installed: " + s_sitesWhy; return false; }
    uintptr_t cur = 0;
    if (!ReadPtr(s_slot, cur)) { why = "slot unreadable"; return false; }
    const SlotClaim c = DecideSlotClaim(cur, (uintptr_t)&s_fwd);
    if (c == SlotClaim::Foreign) { why = "the slot holds a handler that is not ours: left alone"; LOGE("console: slot %p holds %p (not ours): never taken", (void*)s_slot, (void*)cur); return false; }
    if (on && c == SlotClaim::Claim) *(volatile uintptr_t*)s_slot = (uintptr_t)&s_fwd;
    if (!on && c == SlotClaim::Ours) *(volatile uintptr_t*)s_slot = 0;
    s_on = on;
    LOGI("console: %s (slot %p: %s -> %p)", on ? "on" : "off", (void*)s_slot, SlotClaimName(c), (void*)*(volatile uintptr_t*)s_slot);
    return true;
}
} // namespace

void ConsoleInit(bool key, const ConsoleAdapter* ad) {
    InitializeCriticalSection(&s_cs);
    s_key = key; s_ad = ad;
    LOGI("console: dev.console=%d%s", key ? 1 : 0, key && !ad ? " but the adapter has no console: off" : "");
    if (!ad) s_key = false;
}

void ConsoleInstall() {
    Lock l;
    if (!s_key || s_installed || !s_ad) return;
    const Runtime& rt = Rt();
    if (!rt.plan.engineHooks || !rt.plan.engineReads) { s_sitesWhy = "the exe guard's plan allows no engine hooks"; LOGW("console: not installed: %s", s_sitesWhy.c_str()); return; }
    const char* sites[] = { s_ad->slotSite, s_ad->slotCallSite, s_ad->ownerSite, s_ad->wiringSite, s_ad->ctorSite, s_ad->ctorTailSite, s_ad->executeSite, s_ad->gateSite };
    for (const char* s : sites)
        if (!SiteAddress(s)) { s_sitesWhy = std::string("site ") + s + " not accepted by the patch engine" + (rt.sitesWhy.empty() ? "" : ": " + rt.sitesWhy); LOGE("console: not installed: %s", s_sitesWhy.c_str()); return; }
    s_slot = Operand(s_ad->slotSite, s_ad->slotOperand);
    s_ownerGlobal = Operand(s_ad->ownerSite, s_ad->ownerOperand);
    s_selVtbl = Operand(s_ad->wiringSite, s_ad->selectionVtblOperand);
    s_cliVtbl = Operand(s_ad->ctorTailSite, s_ad->cliVtblOperand);
    s_ctor = SiteAddress(s_ad->ctorSite); s_execute = SiteAddress(s_ad->executeSite);
    s_gateOff = *(const uint8_t*)(SiteAddress(s_ad->gateSite) + s_ad->gateOperand);
    if (Operand(s_ad->slotCallSite, 2) != s_slot) { s_sitesWhy = "the slot test and the slot call name different slots"; LOGE("console: not installed: %s", s_sitesWhy.c_str()); return; }
    s_sitesOk = s_installed = true;
    LOGI("console: install: slot %p (%s), owner global %p, selection vtable %p, CLI ctor %p, CLI vtable %p, Execute %p (slot %d), gate byte +0x%x; sites %s %s %s %s %s %s %s %s",
         (void*)s_slot, s_ad->slotSite, (void*)s_ownerGlobal, (void*)s_selVtbl, (void*)s_ctor, (void*)s_cliVtbl, (void*)s_execute, s_ad->executeSlot, (unsigned)s_gateOff,
         sites[0], sites[1], sites[2], sites[3], sites[4], sites[5], sites[6], sites[7]);
    std::string why;
    if (!SetSlot(true, why)) LOGE("console: slot not claimed: %s", why.c_str());
}

bool ConsoleSet(bool on, std::string& why) {
    Lock l;
    if (!s_key) { why = "dev.console=0"; return false; }
    return SetSlot(on, why);
}

ConsolePre ConsolePrecheck(const std::string& name) {
    ConsolePre p;
    Lock l;
    p.keyOn = s_key; p.sitesOk = s_sitesOk; p.sitesWhy = s_sitesWhy; p.on = s_on;
    if (s_key && s_installed) { uintptr_t cur = 0; p.slotOurs = ReadPtr(s_slot, cur) && cur == (uintptr_t)&s_fwd; }
    if (!name.empty()) {   // the executor fopen()s the bare name relative to the working folder (the game folder) before the slot
        wchar_t cwd[MAX_PATH] = {};
        if (GetCurrentDirectoryW(MAX_PATH, cwd)) {
            std::wstring f = cwd; if (!f.empty() && f.back() != L'\\') f += L'\\';
            p.fileExists = GetFileAttributesW((f + WidenUtf8(name)).c_str()) != INVALID_FILE_ATTRIBUTES;
        }
    }
    return p;
}

const ConsoleAdapter* ConsoleAd() { return s_ad; }
long ConsoleSeq() { Lock l; return s_seq; }
bool ConsoleLastSince(long seq, FwdResult& res, std::string& name, std::string& why, int& hits) {
    Lock l;
    if (s_seq == seq) return false;
    res = s_last; name = s_lastName; why = s_lastWhy; hits = s_last == FwdResult::Hit ? 1 : 0;
    return true;
}

std::string ConsoleStatusJson() {
    const std::string scene = DevSceneNow();   // before s_cs (lock order)
    Lock l;
    uintptr_t cur = 0, camp = 0; std::string chainWhy;
    const bool slotRead = s_installed && ReadPtr(s_slot, cur);
    const bool chain = s_installed && Chain(camp, chainWhy);
    char b[900];
    snprintf(b, sizeof b, "\"gate\": {\"key\": %s, \"sites_ok\": %s, \"sites_why\": \"%s\", \"on\": %s, \"scene\": \"%s\"}, \"slot\": {\"address\": \"%p\", "
             "\"value\": \"%p\", \"state\": \"%s\"}, \"campaign\": {\"chain_ok\": %s, \"context\": \"%p\", \"why\": \"%s\"}, \"cli\": \"%p\", "
             "\"forwards\": %d, \"hits\": %d, \"refusals\": %d, \"selection_vtable\": \"%p\", \"selection_base_vtable\": \"%p\", \"gate_offset\": %d, \"gate_sets\": %d",
             s_key ? "true" : "false", s_sitesOk ? "true" : "false", s_sitesWhy.c_str(), s_on ? "true" : "false", scene.c_str(), (void*)s_slot,
             (void*)cur, !slotRead ? "unread" : SlotClaimName(DecideSlotClaim(cur, (uintptr_t)&s_fwd)), chain ? "true" : "false", (void*)camp,
             chainWhy.c_str(), (void*)s_cli, s_forwards, s_hits, s_refusals, (void*)s_selVtblSeen, (void*)s_selVtbl, s_gateOff, s_gateSets);
    return b;
}

} // namespace wsp

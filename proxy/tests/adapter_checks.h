#pragma once
// adapter_checks.h - the console and camera adapter contract (W16, B15), checked against a site table: every rule follows from how
// proxy/src/console.cpp and camera.cpp READ the adapter's sites (which rows, which operands, which values must agree), written against
// the adapter's own fields only. A game's literal numbers, opcodes and command names (what only its exe has) are checked in the game's
// own host tests (layout.py proxy-tests), which call these first. Test side only: proxy/tests is not a DLL input (build_id.py INPUTS).
// Used by test_console.cpp and test_camera.cpp (synthetic tables) and by a game's tests (its generated table: TableLookup(a.sites, a.nSites)).
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <functional>
#include <string>
#include <vector>
#include "patch_engine.h"
#include "console.h"
#include "camera.h"

namespace wsp { namespace adck {

using SiteLookup = std::function<const SiteDef*(const char* id)>;   // site id -> its row, nullptr when the table has none

inline const SiteDef* FindSite(const SiteDef* sites, size_t n, const char* id) {
    for (size_t i = 0; id && i < n; ++i) if (sites[i].id && !strcmp(sites[i].id, id)) return &sites[i];
    return nullptr;
}
inline SiteLookup TableLookup(const SiteDef* sites, size_t n) { return [sites, n](const char* id) { return FindSite(sites, n, id); }; }

// The little-endian dword in a row's stock bytes at `off`, as console.cpp's and camera.cpp's Operand() read it from the checked site.
inline bool StockDword(const SiteDef* s, int off, uint32_t& v) {
    if (!s || off < 0 || off + 4 > (int)s->len) return false;
    v = (uint32_t)s->stock[off] | (uint32_t)s->stock[off + 1] << 8 | (uint32_t)s->stock[off + 2] << 16 | (uint32_t)s->stock[off + 3] << 24;
    return true;
}

// Two numbers of console.cpp the contract depends on (test_console.cpp's source lint keeps them in step): the slot call's operand,
// read as Operand(slotCallSite, 2), and the size of each CampaignCLI buffer the proxy builds (s_cliBuf[8][0x80]).
constexpr int kConsoleSlotCallOperand = 2;
constexpr unsigned kConsoleCliBuf = 0x80;

namespace detail {
inline std::string Hex(uint32_t v) { char b[16]; snprintf(b, sizeof b, "0x%x", v); return b; }
struct Ck {
    const char* feature; const char* key; const SiteLookup& site; std::vector<std::string> p;
    // the named site: in the table, a kHook row, keyed by the feature's config key (the patch engine checks it; the feature reads it)
    const SiteDef* Need(const char* role, const char* id) {
        const std::string r = std::string(feature) + ": " + role + " site";
        if (!id || !*id) { p.push_back(r + " is not named"); return nullptr; }
        const SiteDef* s = site(id);
        if (!s) { p.push_back(r + " " + id + " is not in the site table"); return nullptr; }
        if (s->kind != kHook) p.push_back(r + " " + id + " is not a hook row (kind " + std::to_string(s->kind) + ")");
        if (!s->configKey || strcmp(s->configKey, key)) p.push_back(r + " " + id + " is not keyed by " + key + " (" + (s->configKey ? s->configKey : "always on") + ")");
        return s;
    }
    // an operand the core reads from the site's bytes: inside its stock bytes (a read beyond them reads bytes no row checked)
    bool Inside(const SiteDef* s, int off, int width) {
        if (!s) return false;
        if (off < 0 || off + width > (int)s->len) {
            p.push_back(std::string(feature) + ": " + s->id + " operand at +" + std::to_string(off) + " (" + std::to_string(width) + " bytes) is outside its " +
                        std::to_string(s->len) + " stock bytes");
            return false;
        }
        return true;
    }
    void NonNegative(const char* field, long v) { if (v < 0) p.push_back(std::string(feature) + ": " + field + " " + std::to_string(v) + " is negative"); }
};
} // namespace detail

// Every problem with a console adapter against its sites; empty = the core's reads are well formed (console.cpp ConsoleInstall, Chain, Cli).
inline std::vector<std::string> ConsoleAdapterProblems(const ConsoleAdapter& c, const SiteLookup& site) {
    detail::Ck k{ "console", "dev.console", site, {} };
    const SiteDef* slot = k.Need("slot", c.slotSite);
    const SiteDef* call = k.Need("slot call", c.slotCallSite);
    const SiteDef* owner = k.Need("owner", c.ownerSite);
    const SiteDef* wiring = k.Need("wiring", c.wiringSite);
    k.Need("CLI ctor", c.ctorSite);
    const SiteDef* tail = k.Need("CLI ctor tail", c.ctorTailSite);
    k.Need("Execute", c.executeSite);
    const SiteDef* gate = k.Need("gate", c.gateSite);
    const bool slotIn = k.Inside(slot, c.slotOperand, 4), callIn = k.Inside(call, kConsoleSlotCallOperand, 4);
    uint32_t a = 0, b = 0;
    if (slotIn && callIn && StockDword(slot, c.slotOperand, a) && StockDword(call, kConsoleSlotCallOperand, b) && a != b)   // ConsoleInstall refuses this
        k.p.push_back("console: the slot call reads " + detail::Hex(b) + " (" + c.slotCallSite + " +" + std::to_string(kConsoleSlotCallOperand) + ") but the slot test reads " +
                      detail::Hex(a) + " (" + c.slotSite + " +" + std::to_string(c.slotOperand) + "): one slot");
    k.Inside(owner, c.ownerOperand, 4);            // the owner global
    k.Inside(wiring, c.selectionVtblOperand, 4);   // the selection's base vtable
    k.Inside(tail, c.cliVtblOperand, 4);           // the CLI's vtable
    k.Inside(gate, c.gateOperand, 1);              // the gate byte's offset: one byte
    k.NonNegative("ownerCampaignOff", c.ownerCampaignOff);
    k.NonNegative("ownerSelectionOff", c.ownerSelectionOff);
    k.NonNegative("campaignSelectionOff", c.campaignSelectionOff);
    k.NonNegative("cliCtxOff", c.cliCtxOff);
    k.NonNegative("executeSlot", c.executeSlot);
    if (c.cliCtxOff < 0 || (long)c.cliCtxOff + 4 > (long)c.cliSize)
        k.p.push_back("console: cliCtxOff + 4 (" + std::to_string((long)c.cliCtxOff + 4) + ") is beyond cliSize " + std::to_string(c.cliSize));
    if (c.cliSize > kConsoleCliBuf)
        k.p.push_back("console: cliSize " + detail::Hex(c.cliSize) + " is larger than the proxy's CLI buffer " + detail::Hex(kConsoleCliBuf) + " (console.cpp Cli refuses it)");
    return k.p;
}

// Every problem with a camera adapter against its sites; empty = the core's reads are well formed (camera.cpp CameraInstall, Mode, CameraSet).
inline std::vector<std::string> CameraAdapterProblems(const CameraAdapter& c, const SiteLookup& site) {
    detail::Ck k{ "camera", "dev.camera", site, {} };
    const SiteDef* chain = k.Need("chain", c.chainSite);
    const SiteDef* mode = k.Need("mode", c.modeSite);
    k.Need("set", c.setSite);
    k.Inside(chain, c.globalOperand, 4);           // the battle owner global
    k.Inside(chain, c.battleOffOperand, 4);        // owner -> battle
    k.Inside(chain, c.controllerOffOperand, 4);    // battle -> controller
    k.Inside(mode, c.modeOffOperand, 4);           // controller -> mode
    k.NonNegative("setSlot", c.setSlot);
    if (!std::isfinite(c.targetDistance) || c.targetDistance <= 0)   // CamTargetFor refuses every set otherwise
        k.p.push_back("camera: targetDistance " + std::to_string(c.targetDistance) + " is not a positive finite number");
    return k.p;
}

}} // namespace wsp::adck

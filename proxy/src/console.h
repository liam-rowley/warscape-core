#pragma once
// console.h - the campaign console's pure decisions (J15; port of empire-remastered rml_mod/src/dev_console.{h,cpp}): line parsing,
// the refusal rules of the `console` ctl verb, the claim rule for the executor's external-handler slot, the forwarder's gate, the
// result's path label, and Lua quoting. No Windows headers, no globals: host tests in proxy/tests/test_console.cpp. The driver is
// console.cpp; the game's sites, offsets and command tables come from the adapter (ConsoleAdapter).
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

namespace wsp {

// The game's console layout (proxy/<game>/adapter.cpp). Every address is an engine_sites row checked by the patch engine; offsets
// are the numbers inside those rows' stock bytes (test_console.cpp checks each one against the generated site table).
struct ConsoleAdapter {
    const char* slotSite;   int slotOperand;          // instruction reading the external-handler slot; operand = slot address
    const char* slotCallSite;                         // the executor's slot->vfunc0(&name, &stream) call: the forwarder's contract
    const char* ownerSite;  int ownerOperand;         // instruction reading the global that holds the campaign owner
    int ownerCampaignOff;                             // campaign = *(owner + this)
    const char* wiringSite;                           // the owner ctor: selection sub-object, its vtable, campaign->selection
    int ownerSelectionOff; int selectionVtblOperand; int campaignSelectionOff;
    const char* ctorSite;                             // CampaignCLI ctor: thiscall(void** ctx)
    const char* ctorTailSite; int cliVtblOperand;     // the ctor's final vtable store
    int cliCtxOff; unsigned cliSize;                  // this + cliCtxOff = campaign; object size
    const char* executeSite; int executeSlot;         // CampaignCLI::Execute and its vtable index
    const char* gateSite; int gateOperand;            // a handler's `cmp byte [campaign + off], 0`: the byte most acting handlers need set
    const char* const* noOps;                         // campaign commands that do nothing in retail (refused)
    const char* const* systemNames;                   // the system dictionary (path label "system")
};

inline std::string ConsoleTrim(const std::string& s) {
    size_t a = 0, b = s.size();
    while (a < b && (s[a] == ' ' || s[a] == '\t')) ++a;
    while (b > a && (s[b - 1] == ' ' || s[b - 1] == '\t')) --b;
    return s.substr(a, b - a);
}

struct ConsoleLine { std::string line, name, args, error; };

// One statement only: the executor also splits on ';' and drops '#' comments and parses '"' quotes, so a line with any of them could
// run a second command behind the checks (refused). Control characters and an empty line are refused too.
inline ConsoleLine ParseConsoleLine(const std::string& in) {
    ConsoleLine r; r.line = ConsoleTrim(in);
    if (r.line.empty()) { r.error = "console needs a command line (or status|on|off)"; return r; }
    for (char c : r.line) {
        if ((unsigned char)c < 0x20 || c == 0x7f) { r.error = "control character in the line"; return r; }
        if (c == ';' || c == '#' || c == '"' || c == '\\') { r.error = std::string("'") + c + "' in the line (one plain statement only: the executor splits on ';', drops '#' comments, parses quotes)"; return r; }
    }
    const size_t sp = r.line.find_first_of(" \t");
    r.name = r.line.substr(0, sp);
    r.args = sp == std::string::npos ? "" : ConsoleTrim(r.line.substr(sp + 1));
    return r;
}

inline bool ConsoleInList(const char* const* list, const std::string& name) {
    for (; list && *list; ++list) if (name == *list) return true;
    return false;
}

// Slot claim: write only an empty slot. A slot holding our forwarder is ours already; anything else was written by the engine (or
// another module), and is never taken (brief: chaining to the engine's handler is Liam's decision).
enum class SlotClaim { Claim, Ours, Foreign };
inline SlotClaim DecideSlotClaim(uintptr_t cur, uintptr_t ours) { return cur == 0 ? SlotClaim::Claim : cur == ours ? SlotClaim::Ours : SlotClaim::Foreign; }
inline const char* SlotClaimName(SlotClaim c) { return c == SlotClaim::Claim ? "empty" : c == SlotClaim::Ours ? "ours" : "FOREIGN"; }
// What `on`/`off` write into the slot: only the empty-to-ours claim. `off` leaves the forwarder in place and sets the refuse state: the
// executor tests the slot and then reads it again for the call, so a 0 written between the two from the control thread would be called.
enum class SlotWrite { None, Ours };
inline SlotWrite DecideSlotWrite(bool on, SlotClaim c) { return on && c == SlotClaim::Claim ? SlotWrite::Ours : SlotWrite::None; }
// The verb attributes the forwarder's latest record to its own line only when the record names the line's command: a CliExecute from
// game Lua in the same pump leaves a record of its own.
inline bool RecordIsForLine(bool seen, const std::string& recordName, const std::string& lineName) { return seen && recordName == lineName; }

// What the verb knows before it runs a line. "" = run it.
struct ConsolePre {
    bool keyOn = false, sitesOk = false, on = false, slotOurs = false, fileExists = false;
    std::string sitesWhy, scene;
};
inline std::string ConsoleRefusal(const ConsolePre& p, const ConsoleLine& l, const char* const* noOps) {
    if (!p.keyOn) return "dev.console=0: the console is off (nothing is read or written in engine memory)";
    if (!l.error.empty()) return l.error;
    if (!p.sitesOk) return "console sites not verified: " + (p.sitesWhy.empty() ? std::string("patch engine did not accept them") : p.sitesWhy);
    if (!p.on) return "console is off (console on)";
    if (!p.slotOurs) return "the external-handler slot is not ours (console status)";
    if (p.scene != "campaign") return "scene is " + (p.scene.empty() ? std::string("unknown") : p.scene) + ", not campaign";
    if (p.fileExists) return "a file named '" + l.name + "' is in the game folder: the executor would run it as a console script before the campaign dictionary";
    if (ConsoleInList(noOps, l.name)) return "'" + l.name + "' is a no-op in retail (its handler does nothing: proxy/runs/20261029_j15re/campaign_commands.tsv)";
    return "";
}

// The forwarder's own gate, checked on every call (from the verb or any Lua CliExecute): "" = forward.
struct ConsoleGate { bool keyOn = false, on = false, sitesOk = false, chainOk = false, cliOk = false; std::string scene, chainWhy; };
inline std::string ForwardRefusal(const ConsoleGate& g) {
    if (!g.keyOn || !g.on) return "console off";
    if (!g.sitesOk) return "sites not verified";
    if (g.scene != "campaign") return "scene is " + (g.scene.empty() ? std::string("unknown") : g.scene) + ", not campaign";
    if (!g.chainOk) return "no live campaign context: " + g.chainWhy;
    if (!g.cliOk) return "the campaign CLI's vtable or context is not intact";
    return "";
}

// The ctl result's path: the executor tries system dictionary, tweaks, a script file, then our slot (forwarder: hit, unknown, refused).
enum class FwdResult { None, Hit, Unknown, Refused };
inline const char* ConsolePath(bool systemName, FwdResult f) {
    switch (f) {
    case FwdResult::Hit: return "campaign";
    case FwdResult::Unknown: return "unknown";
    case FwdResult::Refused: return "refused";
    default: return systemName ? "system" : "tweak";   // files are refused before the run, so a line the slot never saw was a tweak
    }
}

// A Lua 5.1 string literal for any byte string (the verb runs `return CliExecute(<literal>)` through the bridge).
inline std::string LuaQuote(const std::string& s) {
    std::string o = "\"";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { o += '\\'; o += (char)c; }
        else if (c < 0x20 || c >= 0x7f) { char b[6]; snprintf(b, sizeof b, "\\%03u", c); o += b; }
        else o += (char)c;
    }
    return o + "\"";
}

} // namespace wsp

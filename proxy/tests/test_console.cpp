// test_console.cpp - host tests for the campaign console (J15): line parsing, the verb's refusals (key off, file name, no-op), the
// slot-claim rule, the forwarder's gate, the path label, Lua quoting; the adapter contract checker (adapter_checks.h, W16) on a synthetic
// site table, one passing and one failing case per rule; and source lints (key off = no engine read or write, the slot written only by the
// claim, never 0; the gate byte set only around one Execute; the chunk deleted after its run; the record matched to the line; no game named
// in core). A game checks its own console numbers in its own proxy/tests (layout.py proxy-tests). Built and run by proxy/tools/build.sh tests.
#include "testkit.h"
#include "console.h"
#include "adapter_checks.h"
#include "adapter.cpp"
#include <set>

using namespace wsp;

static bool Has(const std::vector<std::string>& p, const char* part) {
    for (const std::string& s : p) if (s.find(part) != std::string::npos) return true;
    for (const std::string& s : p) printf("    (problem: %s)\n", s.c_str());
    printf("    no problem names '%s'\n", part);
    return false;
}

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    {   // parsing
        ConsoleLine l = ParseConsoleLine("  teleport_to 10.5  -3 ");
        CHECK(l.error.empty()); CHECK_EQ(l.name, std::string("teleport_to")); CHECK_EQ(l.args, std::string("10.5  -3")); CHECK_EQ(l.line, std::string("teleport_to 10.5  -3"));
        CHECK(ParseConsoleLine("bare_cmd").args.empty());
        CHECK(!ParseConsoleLine("").error.empty());
        CHECK(!ParseConsoleLine("   ").error.empty());
        CHECK(!ParseConsoleLine("teleport_to 1 2; quit").error.empty());   // a second statement behind the checks
        CHECK(!ParseConsoleLine("teleport_to 1 2 # x").error.empty());
        CHECK(!ParseConsoleLine("make_thing \"x\"").error.empty());
        CHECK(!ParseConsoleLine("a\\b").error.empty());
        CHECK(!ParseConsoleLine("a\tb\x01").error.empty());
        CHECK(!ParseConsoleLine("a\tb").error.empty());   // tabs are control characters too
    }
    const char* const noops[] = { "noop_b", "noop_a", nullptr };
    {   // the verb's refusals, in order
        ConsolePre p; ConsoleLine l = ParseConsoleLine("teleport_to 1 2");
        CHECK(ConsoleRefusal(p, l, noops).find("dev.console=0") == 0);                 // key off first, whatever else
        p.keyOn = true;
        CHECK(ConsoleRefusal(p, ParseConsoleLine("x;y"), noops).find("';'") != std::string::npos);
        CHECK(ConsoleRefusal(p, l, noops).find("sites not verified") != std::string::npos);
        p.sitesOk = true;
        CHECK(ConsoleRefusal(p, l, noops).find("console is off") == 0);
        p.on = true;
        CHECK(ConsoleRefusal(p, l, noops).find("slot is not ours") != std::string::npos);
        p.slotOurs = true;
        p.scene = "frontend"; CHECK(ConsoleRefusal(p, l, noops).find("not campaign") != std::string::npos);
        p.scene = "campaign"; CHECK(ConsoleRefusal(p, l, noops).empty());
        p.fileExists = true; CHECK(ConsoleRefusal(p, l, noops).find("file named 'teleport_to'") != std::string::npos);
        p.fileExists = false;
        CHECK(ConsoleRefusal(p, ParseConsoleLine("noop_b x y"), noops).find("no-op in retail") != std::string::npos);
        CHECK(ConsoleRefusal(p, ParseConsoleLine("noop_b_x"), noops).empty());   // whole-name match only
    }
    {   // slot claim: only an empty slot is taken; ours stays ours; anything else is never touched
        CHECK(DecideSlotClaim(0, 0x1000) == SlotClaim::Claim);
        CHECK(DecideSlotClaim(0x1000, 0x1000) == SlotClaim::Ours);
        CHECK(DecideSlotClaim(0x2000, 0x1000) == SlotClaim::Foreign);
        // only the empty-to-ours claim writes the slot; off never writes it (0 between the executor's test and its call would be called)
        CHECK(DecideSlotWrite(true, SlotClaim::Claim) == SlotWrite::Ours);
        CHECK(DecideSlotWrite(true, SlotClaim::Ours) == SlotWrite::None && DecideSlotWrite(true, SlotClaim::Foreign) == SlotWrite::None);
        CHECK(DecideSlotWrite(false, SlotClaim::Ours) == SlotWrite::None && DecideSlotWrite(false, SlotClaim::Claim) == SlotWrite::None);
        CHECK(DecideSlotWrite(false, SlotClaim::Foreign) == SlotWrite::None);
        // a forwarder record counts for the line only when it names the line's command
        CHECK(RecordIsForLine(true, "teleport_to", "teleport_to"));
        CHECK(!RecordIsForLine(true, "declare_war", "teleport_to") && !RecordIsForLine(false, "teleport_to", "teleport_to"));
    }
    {   // the forwarder's gate
        ConsoleGate g; CHECK(ForwardRefusal(g) == "console off");
        g.keyOn = g.on = true; CHECK(ForwardRefusal(g) == "sites not verified");
        g.sitesOk = true; g.scene = "battle"; CHECK(ForwardRefusal(g).find("not campaign") != std::string::npos);
        g.scene = "campaign"; g.chainWhy = "owner global empty"; CHECK(ForwardRefusal(g).find("owner global empty") != std::string::npos);
        g.chainOk = true; CHECK(ForwardRefusal(g).find("vtable") != std::string::npos);   // stale CLI between campaigns
        g.cliOk = true; CHECK(ForwardRefusal(g).empty());
    }
    {   // path labels
        CHECK_EQ(std::string(ConsolePath(true, FwdResult::None)), std::string("system"));
        CHECK_EQ(std::string(ConsolePath(false, FwdResult::None)), std::string("tweak"));
        CHECK_EQ(std::string(ConsolePath(false, FwdResult::Hit)), std::string("campaign"));
        CHECK_EQ(std::string(ConsolePath(false, FwdResult::Unknown)), std::string("unknown"));
        CHECK_EQ(std::string(ConsolePath(true, FwdResult::Refused)), std::string("refused"));
    }
    {   // Lua quoting
        CHECK_EQ(LuaQuote("teleport_to 1 2"), std::string("\"teleport_to 1 2\""));
        CHECK_EQ(LuaQuote("a\"b\\c\n"), std::string("\"a\\\"b\\\\c\\010\""));
    }
    {   // the contract checker on a synthetic console: eight hook rows keyed dev.console, the slot test and the slot call on one slot
        static const char* const ids[] = { "slot", "call", "owner", "wiring", "ctor", "tail", "exec", "gate" };
        std::vector<SiteDef> t(8);
        for (int i = 0; i < 8; ++i) { t[i] = SiteDef{}; t[i].id = ids[i]; t[i].kind = kHook; t[i].len = 24; t[i].configKey = "dev.console"; }
        t[0].stock[2] = 0x78; t[0].stock[3] = 0x56; t[0].stock[4] = 0x34; t[0].stock[5] = 0x12;   // slot test: the slot at +2
        t[1].stock[2] = 0x78; t[1].stock[3] = 0x56; t[1].stock[4] = 0x34; t[1].stock[5] = 0x12;   // slot call: [slot] at +2
        const ConsoleAdapter good = { "slot", 2, "call", "owner", 2, 0x10, "wiring", 0x20, 8, 0x28, "ctor", "tail", 13, 0x28, 0x30, "exec", 5, "gate", 2,
                                      nullptr, nullptr };
        CHECK(adck::ConsoleAdapterProblems(good, adck::TableLookup(t.data(), t.size())).empty());
        auto bad = [&](ConsoleAdapter c, std::vector<SiteDef> tt, const char* part) { CHECK(Has(adck::ConsoleAdapterProblems(c, adck::TableLookup(tt.data(), tt.size())), part)); };
        { ConsoleAdapter c = good; c.ownerSite = "nowhere"; bad(c, t, "nowhere is not in the site table"); }
        { auto tt = t; tt[4].kind = kPatch; bad(good, tt, "ctor is not a hook row"); }
        { auto tt = t; tt[6].configKey = "dev.other"; bad(good, tt, "exec is not keyed by dev.console"); }
        { auto tt = t; tt[7].configKey = nullptr; bad(good, tt, "gate is not keyed by dev.console"); }
        { ConsoleAdapter c = good; c.slotOperand = 21; bad(c, t, "slot operand at +21"); }
        { auto tt = t; tt[1].stock[5] = 0x13; bad(good, tt, "the slot call reads"); }
        { auto tt = t; tt[1].len = 5; bad(good, tt, "call operand at +2"); }
        { ConsoleAdapter c = good; c.ownerOperand = -1; bad(c, t, "owner operand at +-1"); }
        { ConsoleAdapter c = good; c.selectionVtblOperand = 24; bad(c, t, "wiring operand at +24"); }
        { ConsoleAdapter c = good; c.cliVtblOperand = 22; bad(c, t, "tail operand at +22"); }
        { ConsoleAdapter c = good; c.gateOperand = 24; bad(c, t, "gate operand at +24"); }
        { ConsoleAdapter c = good; c.cliCtxOff = 0x2d; bad(c, t, "cliCtxOff + 4"); }
        { ConsoleAdapter c = good; c.cliSize = 0x84; c.cliCtxOff = 0x28; bad(c, t, "cliSize 0x84"); }
        { ConsoleAdapter c = good; c.executeSlot = -1; bad(c, t, "executeSlot"); }
        { ConsoleAdapter c = good; c.ownerCampaignOff = -4; bad(c, t, "ownerCampaignOff"); }
        { ConsoleAdapter c = good; c.slotCallSite = nullptr; bad(c, t, "slot call site is not named"); }
    }
    {   // source lints
        const std::string cc = tk::ReadFile("core/console.cpp"), ch = tk::ReadFile("core/console.h");
        CHECK(!cc.empty() && !ch.empty());
        // key off: ConsoleInstall returns before any site address or engine read; the slot is written only in SetSlot after the claim rule
        const size_t inst = cc.find("void ConsoleInstall()"), keyRet = cc.find("if (!s_key || s_installed || !s_ad) return;", inst),
                     plan = cc.find("rt.plan.engineHooks", inst), firstSite = cc.find("SiteAddress(", inst);
        CHECK(inst != std::string::npos && keyRet < plan && plan < firstSite);
        size_t writes = 0; for (size_t k = 0; (k = cc.find("*(volatile uintptr_t*)s_slot = ", k)) != std::string::npos; ++k) ++writes;
        CHECK(writes == 1);                                              // the claim only: off leaves the forwarder in place
        CHECK(cc.find("*(volatile uintptr_t*)s_slot = 0") == std::string::npos);
        const size_t setSlot = cc.find("bool SetSlot("), claim = cc.find("DecideSlotClaim(cur", setSlot), w1 = cc.find("*(volatile uintptr_t*)s_slot = ", setSlot);
        CHECK(setSlot < claim && claim < w1 && cc.find("*(volatile uintptr_t*)s_slot = ") == w1);
        CHECK(cc.find("Foreign) {") != std::string::npos);
        CHECK(cc.find("VirtualProtect") == std::string::npos);           // the slot is in a writable section: no protection change
        // the gate byte is set only around one Execute call and restored right after it
        {
            const size_t set = cc.find("if (gate && !gateOld) *gate = 1;"), call = cc.find("((ExecFn)s_execute)(", set), back = cc.find("if (gate && !gateOld) *gate = gateOld;", call);
            CHECK(set != std::string::npos && call != std::string::npos && back != std::string::npos && back - call < 200);
        }
        // adapter_checks.h mirrors two numbers of console.cpp: the slot call's operand and the CLI buffer's size
        CHECK(cc.find("Operand(s_ad->slotCallSite, 2)") != std::string::npos && adck::kConsoleSlotCallOperand == 2);
        CHECK(cc.find("s_cliBuf[8][0x80]") != std::string::npos && adck::kConsoleCliBuf == 0x80);
        CHECK(cc.find("ConsoleSet(") != std::string::npos && cc.find("if (!s_key) { why = \"dev.console=0\"") != std::string::npos);
        // every forwarded or refused line is logged
        CHECK(cc.find("LOGI(\"console: forwarded") != std::string::npos && cc.find("LOGW(\"console: refused") != std::string::npos);
        // the dev side starts the console only after its own plan gate
        const std::string dv = tk::ReadFile("core/dev.cpp");
        CHECK(dv.find("if (!rt.plan.engineHooks || !rt.plan.d3dHooks)") < dv.find("ConsoleInit(k.console"));
        // the verb deletes its chunk as soon as the run returns, before any result path, and checks the record's name against the line
        {
            const size_t verb = dv.find("Outcome Console("), run = dv.find("RunLua(id, rel,", verb), del = dv.find("DeleteFileW(", run),
                         nextRet = dv.find("return o;", run), match = dv.find("RecordIsForLine(", run);
            CHECK(verb != std::string::npos && run != std::string::npos && del != std::string::npos && del < nextRet && del - run < 200);
            CHECK(match != std::string::npos && match < nextRet);
        }
        for (const char* f : { "console.cpp", "console.h" }) {
            std::string s = tk::ReadFile(std::string("core/") + f);
            for (size_t k; (k = s.find("empire-remastered")) != std::string::npos;) s.erase(k, 17);
            const bool named = s.find("apoleon") != std::string::npos || s.find("mpire") != std::string::npos;
            if (named) { printf("    %s names a game\n", f); CHECK(!named); }
        }
    }
    return tk::Done("test_console");
}

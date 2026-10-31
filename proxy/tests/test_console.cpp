// test_console.cpp - host tests for the campaign console (J15): line parsing, the verb's refusals (key off, file name, no-op), the
// slot-claim rule, the forwarder's gate, the path label, Lua quoting; the adapter's offsets against the bytes of its engine_sites
// rows; and source lints (key off = no engine read or write, the slot written only by the claim, never 0; the record matched to the
// line; no game named in core).
// Built and run by proxy/tools/build.sh tests.
#include "testkit.h"
#include "console.h"
#include "adapter.cpp"
#include <set>

using namespace wsp;

static const SiteDef* Site(const char* id) {
    for (size_t i = 0; i < gen::kSiteCount; ++i) if (!strcmp(gen::kSites[i].id, id)) return &gen::kSites[i];
    return nullptr;
}
static uint32_t StockDword(const char* id, int off) {
    const SiteDef* s = Site(id);
    if (!s || off + 4 > s->len) return 0xffffffffu;
    return (uint32_t)s->stock[off] | (uint32_t)s->stock[off + 1] << 8 | (uint32_t)s->stock[off + 2] << 16 | (uint32_t)s->stock[off + 3] << 24;
}

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    {   // parsing
        ConsoleLine l = ParseConsoleLine("  teleport_to 10.5  -3 ");
        CHECK(l.error.empty()); CHECK_EQ(l.name, std::string("teleport_to")); CHECK_EQ(l.args, std::string("10.5  -3")); CHECK_EQ(l.line, std::string("teleport_to 10.5  -3"));
        CHECK(ParseConsoleLine("here_kitty_kitty").args.empty());
        CHECK(!ParseConsoleLine("").error.empty());
        CHECK(!ParseConsoleLine("   ").error.empty());
        CHECK(!ParseConsoleLine("teleport_to 1 2; quit").error.empty());   // a second statement behind the checks
        CHECK(!ParseConsoleLine("teleport_to 1 2 # x").error.empty());
        CHECK(!ParseConsoleLine("create_army \"x\"").error.empty());
        CHECK(!ParseConsoleLine("a\\b").error.empty());
        CHECK(!ParseConsoleLine("a\tb\x01").error.empty());
        CHECK(!ParseConsoleLine("a\tb").error.empty());   // tabs are control characters too
    }
    const char* const noops[] = { "give_trait", "all_end_turn", nullptr };
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
        CHECK(ConsoleRefusal(p, ParseConsoleLine("give_trait x y"), noops).find("no-op in retail") != std::string::npos);
        CHECK(ConsoleRefusal(p, ParseConsoleLine("give_trait_x"), noops).empty());   // whole-name match only
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
    if (Adapter().console) {   // the adapter (when it has a console): every site exists, every offset is the number in its row's stock bytes
        const ConsoleAdapter& c = *Adapter().console;
        for (const char* id : { c.slotSite, c.slotCallSite, c.ownerSite, c.wiringSite, c.ctorSite, c.ctorTailSite, c.executeSite, c.gateSite }) {
            const SiteDef* s = Site(id);
            if (!s) printf("    site %s missing\n", id);
            CHECK(s && s->kind == kHook && s->configKey && !strcmp(s->configKey, "dev.console"));
        }
        const uint32_t slot = StockDword(c.slotSite, c.slotOperand);
        CHECK(Site(c.slotSite)->stock[0] == 0x83 && Site(c.slotSite)->stock[1] == 0x3d);              // cmp dword [imm32], imm8
        CHECK(StockDword(c.slotCallSite, 2) == slot);                                                // the call reads the same slot
        CHECK(Site(c.ownerSite)->stock[0] == 0x8b && Site(c.ownerSite)->stock[1] == 0x0d);            // mov ecx, [imm32]
        CHECK(StockDword(c.ownerSite, 13) == (uint32_t)c.ownerCampaignOff);                          // mov ecx, [ecx + 0x9fc]
        CHECK(StockDword(c.wiringSite, 2) == (uint32_t)c.ownerSelectionOff);                         // lea ecx, [ebx + 0xf4]
        CHECK(Site(c.wiringSite)->stock[6] == 0xc7 && Site(c.wiringSite)->stock[7] == 0x01);          // mov [ecx], imm32
        CHECK(StockDword(c.wiringSite, 12 + 2) == (uint32_t)c.ownerCampaignOff);                     // lea edi, [ebx + 0x9fc]
        CHECK(Site(c.wiringSite)->stock[30] == (uint8_t)c.campaignSelectionOff);                     // mov [eax + 0x28], ecx
        CHECK(Site(c.ctorTailSite)->stock[8] == (uint8_t)c.cliCtxOff);                               // mov [esi + 0x28], eax
        CHECK(Site(c.ctorTailSite)->stock[11] == 0xc7 && Site(c.ctorTailSite)->stock[12] == 0x06);    // mov [esi], imm32
        CHECK(Site(c.ctorTailSite)->stock[21] == 0xc2 && Site(c.ctorTailSite)->stock[22] == 0x04);    // ret 4: thiscall(void** ctx)
        CHECK(c.cliCtxOff + 4 <= (int)c.cliSize);
        CHECK(Site(c.gateSite)->stock[0] == 0x80 && Site(c.gateSite)->stock[c.gateOperand] == 0x54 && Site(c.gateSite)->stock[3] == 0x00);   // cmp byte [r + 0x54], 0
        // the gate byte is set only around one Execute call and restored right after it
        {
            const std::string cc = tk::ReadFile("core/console.cpp");
            const size_t set = cc.find("if (gate && !gateOld) *gate = 1;"), call = cc.find("((ExecFn)s_execute)(", set), back = cc.find("if (gate && !gateOld) *gate = gateOld;", call);
            CHECK(set != std::string::npos && call != std::string::npos && back != std::string::npos && back - call < 200);
        }
        // the no-op table: refuses what retail compiled out, never a command that acts
        CHECK(ConsoleInList(c.noOps, "all_end_turn") && ConsoleInList(c.noOps, "give_trait") && ConsoleInList(c.noOps, "selected_cqi"));
        CHECK(!ConsoleInList(c.noOps, "teleport_to") && !ConsoleInList(c.noOps, "transport_to_region") && !ConsoleInList(c.noOps, "create_army"));
        CHECK(ConsoleInList(c.systemNames, "here_kitty_kitty") && ConsoleInList(c.systemNames, "quit") && !ConsoleInList(c.systemNames, "teleport_to"));
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
        CHECK(cc.find("ConsoleSet(") != std::string::npos && cc.find("if (!s_key) { why = \"dev.console=0\"") != std::string::npos);
        // every forwarded or refused line is logged
        CHECK(cc.find("LOGI(\"console: forwarded") != std::string::npos && cc.find("LOGW(\"console: refused") != std::string::npos);
        // the dev side starts the console only after its own plan gate
        const std::string dv = tk::ReadFile("core/dev.cpp");
        CHECK(dv.find("if (!rt.plan.engineHooks || !rt.plan.d3dHooks)") < dv.find("ConsoleInit(k.console"));
        // the verb checks the record's name against the line before any result path
        {
            const size_t verb = dv.find("Outcome Console("), run = dv.find("RunLua(id, rel,", verb),
                         nextRet = dv.find("return o;", run), match = dv.find("RecordIsForLine(", run);
            CHECK(verb != std::string::npos && run != std::string::npos && match != std::string::npos && match < nextRet);
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

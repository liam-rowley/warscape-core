// test_camera.cpp - host tests for the battle camera setter (J43): the pose -> target conversion against campose.py's conventions,
// its refusals; the adapter contract checker (adapter_checks.h, W16) on a synthetic site table, one passing and one failing case per
// rule; and source lints (key off = no engine read, the setter called only after the chain and vtable slot checks, no game named in
// core). A game checks its own camera numbers in its own proxy/tests (layout.py proxy-tests). Built and run by proxy/tools/build.sh tests.
#include "testkit.h"
#include "camera.h"
#include "adapter_checks.h"
#include "adapter.cpp"

using namespace wsp;

static bool Has(const std::vector<std::string>& p, const char* part) {
    for (const std::string& s : p) if (s.find(part) != std::string::npos) return true;
    for (const std::string& s : p) printf("    (problem: %s)\n", s.c_str());
    printf("    no problem names '%s'\n", part);
    return false;
}
static bool Near(float a, float b, float t = 1e-3f) { return std::fabs(a - b) <= t; }

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    {   // the target: 100 m along forward = (sin yaw cos pitch, sin pitch, cos yaw cos pitch)
        float t[3]; std::string why;
        CamPose p; p.x = 10; p.y = 50; p.z = 20; p.yaw = 180; p.pitch = -25;   // the land_small default: looks along -z, down 25 degrees
        CHECK(CamTargetFor(p, 100, t, why));
        CHECK(Near(t[0], 10) && Near(t[1], 50 - 42.2618f) && Near(t[2], 20 - 90.6308f));
        p.yaw = 90; p.pitch = 0;                                                // along +x (the run's yaw 90 write)
        CHECK(CamTargetFor(p, 100, t, why) && Near(t[0], 110) && Near(t[1], 50) && Near(t[2], 20));
        p.yaw = -90; p.pitch = 30;
        CHECK(CamTargetFor(p, 10, t, why) && Near(t[0], 10 - 8.66025f) && Near(t[1], 55) && Near(t[2], 20));
    }
    {   // refusals
        float t[3]; std::string why; CamPose p;
        p.pitch = 89; CHECK(!CamTargetFor(p, 100, t, why) && why.find("pitch") != std::string::npos);
        p.pitch = -89.5f; CHECK(!CamTargetFor(p, 100, t, why));
        p.pitch = 0; p.x = NAN; CHECK(!CamTargetFor(p, 100, t, why) && why.find("finite") != std::string::npos);
        p.x = 0; p.yaw = INFINITY; CHECK(!CamTargetFor(p, 100, t, why));
        p.yaw = 0; CHECK(!CamTargetFor(p, 0, t, why) && why.find("distance") != std::string::npos);
        CHECK(CamTargetFor(p, 1, t, why));
    }
    {   // the contract checker on a synthetic camera: three hook rows keyed dev.camera
        static const char* const ids[] = { "chain", "mode", "set" };
        std::vector<SiteDef> t(3);
        for (int i = 0; i < 3; ++i) { t[i] = SiteDef{}; t[i].id = ids[i]; t[i].kind = kHook; t[i].len = 20; t[i].configKey = "dev.camera"; }
        const CameraAdapter good = { "chain", 1, 10, 16, "mode", 2, "set", 47, 100.0f };
        CHECK(adck::CameraAdapterProblems(good, adck::TableLookup(t.data(), t.size())).empty());
        auto bad = [&](CameraAdapter c, std::vector<SiteDef> tt, const char* part) { CHECK(Has(adck::CameraAdapterProblems(c, adck::TableLookup(tt.data(), tt.size())), part)); };
        { CameraAdapter c = good; c.setSite = "nowhere"; bad(c, t, "nowhere is not in the site table"); }
        { auto tt = t; tt[1].kind = kPatch; bad(good, tt, "mode is not a hook row"); }
        { auto tt = t; tt[0].configKey = "dev.console"; bad(good, tt, "chain is not keyed by dev.camera"); }
        { CameraAdapter c = good; c.globalOperand = 17; bad(c, t, "chain operand at +17"); }
        { CameraAdapter c = good; c.battleOffOperand = -2; bad(c, t, "chain operand at +-2"); }
        { CameraAdapter c = good; c.controllerOffOperand = 20; bad(c, t, "chain operand at +20"); }
        { auto tt = t; tt[1].len = 5; bad(good, tt, "mode operand at +2"); }
        { CameraAdapter c = good; c.setSlot = -1; bad(c, t, "setSlot"); }
        { CameraAdapter c = good; c.targetDistance = 0; bad(c, t, "targetDistance"); }
        { CameraAdapter c = good; c.targetDistance = NAN; bad(c, t, "targetDistance"); }
        { CameraAdapter c = good; c.chainSite = nullptr; bad(c, t, "chain site is not named"); }
    }
    {   // source lints
        const std::string cc = tk::ReadFile("core/camera.cpp"), ch = tk::ReadFile("core/camera.h");
        CHECK(!cc.empty() && !ch.empty());
        // key off: CameraInstall returns before any site address; CameraSet refuses before any engine read
        const size_t inst = cc.find("void CameraInstall()"), keyRet = cc.find("if (!s_key || s_installed) return;", inst),
                     plan = cc.find("rt.plan.engineHooks", inst), firstSite = cc.find("SiteAddress(", inst);
        CHECK(inst != std::string::npos && keyRet < plan && plan < firstSite);
        const size_t set = cc.find("bool CameraSet("), key = cc.find("if (!s_key)", set), mode = cc.find("if (!Mode(mode, why))", set),
                     call = cc.find("((SetFn)s_setFn)(", set);
        CHECK(set != std::string::npos && key < mode && mode < call && call != std::string::npos);
        size_t calls = 0; for (size_t k = 0; (k = cc.find("((SetFn)", k)) != std::string::npos; ++k) ++calls;
        CHECK(calls == 1);
        // the mode's slot is compared with the checked site before the call
        CHECK(cc.find("slot != s_setFn") != std::string::npos);
        for (const char* g : { "apoleon", "mpire" }) CHECK(cc.find(g) == std::string::npos && ch.find(g) == std::string::npos);
    }
    return tk::Done("test_camera");
}

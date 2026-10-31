// test_camera.cpp - host tests for the battle camera setter (J43): the pose -> target conversion against campose.py's conventions,
// its refusals; the adapter's offsets against the bytes of its engine_sites rows; and source lints (key off = no engine read, the
// setter called only after the chain and vtable slot checks, no game named in core). Built and run by proxy/tools/build.sh tests.
#include "testkit.h"
#include "camera.h"
#include "adapter.cpp"

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
    if (Adapter().camera) {   // the adapter (when it has a camera setter): every site exists, every offset is the number in its row's stock bytes
        const CameraAdapter& c = *Adapter().camera;
        for (const char* id : { c.chainSite, c.modeSite, c.setSite }) {
            const SiteDef* s = Site(id);
            if (!s) printf("    site %s missing\n", id);
            CHECK(s && s->kind == kHook && s->configKey && !strcmp(s->configKey, "dev.camera"));
        }
        CHECK(Site(c.chainSite)->stock[0] == 0xa1);                                                   // mov eax, [imm32]: the owner global
        CHECK(c.globalOperand == 1);
        CHECK(Site(c.chainSite)->stock[8] == 0x8b && Site(c.chainSite)->stock[9] == 0x80);            // mov eax, [eax + imm32]
        CHECK(StockDword(c.chainSite, c.battleOffOperand) == 0xf8);
        CHECK(Site(c.chainSite)->stock[14] == 0x8b && Site(c.chainSite)->stock[15] == 0x80);          // mov eax, [eax + imm32]
        CHECK(StockDword(c.chainSite, c.controllerOffOperand) == 0x281b8);
        CHECK(Site(c.modeSite)->stock[0] == 0x8b && Site(c.modeSite)->stock[1] == 0x8e);              // mov ecx, [esi + imm32]
        CHECK(StockDword(c.modeSite, c.modeOffOperand) == 0x800);
        CHECK(StockDword(c.modeSite, 18) == 0xc0);                                                    // ... call [eax + 0xc0]: a mode method
        CHECK(c.setSlot * 4 == 0xbc);
        const SiteDef* s = Site(c.setSite);
        CHECK(s->stock[0] == 0x83 && s->stock[1] == 0xec && s->stock[2] == 0x08);                     // sub esp, 8: the function entry
        CHECK(s->anchorLen == 4 && s->anchor[0] == 0xcc && s->anchor[3] == 0xcc);                      // int3 padding before it
        CHECK(c.targetDistance > 0);
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

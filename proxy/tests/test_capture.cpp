// test_capture.cpp - host tests for the frame capture (J8): the shader hash convention (canonical FNV-1a-64 to the walked
// end token, a CTAB holding 0x0000FFFF, shader model 1 operands and def literals), the capture name and frame rules, the ctl grammar;
// and source lints (key off = nothing hooked, every hook forwards, no game named in core). Built and run by proxy/tools/build.sh tests.
// The two hash vectors are shared with the game repo's catalogue tool (its tests check the same bytes give the same hex).
#include "testkit.h"
#include "capture.h"
#include "devcore.h"

using namespace wsp;

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    {   // canonical FNV-1a-64 (offset basis 14695981039346656037, not the dropped-digit 1469598103934665603)
        CHECK_EQ(Hex64(Fnv1a64("", 0)), std::string("cbf29ce484222325"));
        CHECK_EQ(Hex64(Fnv1a64("a", 1)), std::string("af63dc4c8601ec8c"));
    }
    {   // vs_3_0 whose CTAB comment holds 0x0000FFFF: the walk skips the comment and ends at the real end token, junk after it ignored
        const uint32_t t[] = { 0xFFFE0300, 0x0003FFFE, 0x42415443, 0x0000FFFF, 0x12345678, 0x02000001, 0x800F0000, 0x90E40000, 0x0000FFFF, 0xDEADBEEF, 0x0000FFFF };
        CHECK_EQ(ShaderLength(t, sizeof t), (size_t)36);
        size_t len = 0; bool ok = false;
        CHECK_EQ(Hex64(ShaderHash(t, sizeof t, len, ok)), std::string("76b2746673a2c8ef"));
        CHECK(ok && len == 36);
        CHECK(Hex64(ShaderHash(t, 16, len, ok)) != "76b2746673a2c8ef" && !ok);   // a cut at the first 0x0000FFFF (16 bytes) is not the shader
    }
    {   // vs_1_1: no length field; operands have bit 31 set; def's literals (1.0 = 0x3F800000 has bit 31 clear) are skipped by count
        const uint32_t t[] = { 0xFFFE0101, 0x00000051, 0xA00F0000, 0x3F800000, 0xBF800000, 0x00000000, 0x40000000, 0x00000001, 0x800F0000, 0x90E40000, 0x0000FFFF };
        size_t len = 0; bool ok = false;
        CHECK_EQ(Hex64(ShaderHash(t, sizeof t, len, ok)), std::string("b0a8b038ffe706ee"));
        CHECK(ok && len == 44);
    }
    {   // not a shader, a bad model, no end token
        const uint32_t notShader[] = { 0x12345678, 0x0000FFFF };
        const uint32_t sm4[] = { 0xFFFF0400, 0x0000FFFF };
        const uint32_t noEnd[] = { 0xFFFF0300, 0x02000001, 0x800F0000, 0x90E40000 };
        const uint32_t longComment[] = { 0xFFFF0200, 0x7FFFFFFE, 0x0000FFFF };
        CHECK_EQ(ShaderLength(notShader, sizeof notShader), (size_t)0);
        CHECK_EQ(ShaderLength(sm4, sizeof sm4), (size_t)0);
        CHECK_EQ(ShaderLength(noEnd, sizeof noEnd), (size_t)0);
        CHECK_EQ(ShaderLength(longComment, sizeof longComment), (size_t)0);   // a comment longer than the buffer: no end token
        CHECK_EQ(ShaderLength(noEnd, 4), (size_t)0);
    }
    {   // capture <name> [frames]
        CHECK(ValidCaptureName("land_small") && ValidCaptureName("a.b-c_1") && !ValidCaptureName(".x") && !ValidCaptureName("a b") && !ValidCaptureName("a\\b"));
        CHECK(!ValidCaptureName(std::string(49, 'a')) && ValidCaptureName(std::string(48, 'a')));
        CaptureArgs a = ParseCaptureArgs("land_small");
        CHECK(a.error.empty() && a.name == "land_small" && a.frames == 1);
        a = ParseCaptureArgs("x 8"); CHECK(a.error.empty() && a.frames == 8);
        CHECK(!ParseCaptureArgs("x 9").error.empty() && !ParseCaptureArgs("x 0").error.empty() && !ParseCaptureArgs("x two").error.empty());
        CHECK(!ParseCaptureArgs("").error.empty() && !ParseCaptureArgs("../x").error.empty());
        CtlRequest r = ParseCtl("capture land_small 2");
        CHECK(r.error.empty() && r.verb == "capture" && r.arg == "land_small 2" && r.timeoutS == 40);
        CHECK(!ParseCtl("capture").error.empty() && !ParseCtl("capture a 99").error.empty());
        CHECK(std::string(CtlVerbs()).find("capture <name> [frames]") != std::string::npos);
    }
    {   // floats are written so they read back exactly
        std::string o; AppendFloat(o, 0.1f); AppendFloat(o, -1.0f / 3.0f);
        float a = 0, b = 0; CHECK(sscanf(o.c_str(), " %f %f", &a, &b) == 2 && a == 0.1f && b == -1.0f / 3.0f);
    }
    {   // source lints
        const std::string cap = tk::ReadFile("core/capture.cpp"), dev = tk::ReadFile("core/dev.cpp");
        CHECK(cap.find("if (!Dk().capture || !dev) return;") != std::string::npos);            // key off: CaptureInstall hooks nothing
        CHECK(dev.find("if (Dk().capture) CapturePresent(dev);") != std::string::npos);          // key off: Present does nothing more
        // every hook forwards to its original on the idle path and once more after recording
        size_t hooks = 0, pos = 0;
        while ((pos = cap.find("HRESULT WINAPI hk_", pos)) != std::string::npos) {
            const size_t name0 = pos + 18, name1 = cap.find('(', name0);
            const std::string name = cap.substr(name0, name1 - name0);
            const size_t end = cap.find("\n}", pos), line = cap.find('\n', pos);
            const std::string body = cap.substr(pos, (end != std::string::npos && end < cap.find("HRESULT WINAPI hk_", pos + 1) ? end : line) - pos);
            size_t calls = 0, q = 0; while ((q = body.find("o_" + name + "(", q)) != std::string::npos) { ++calls; ++q; }
            if (calls < 2) printf("  hook %s forwards %zu times\n", name.c_str(), calls);
            CHECK(calls >= 2);
            ++hooks; pos = name1;
        }
        CHECK(hooks >= 30);
        CHECK(cap.find("Adapter()") == std::string::npos);   // nothing game-specific: the capture reads no adapter field
    }
    return tk::Done("test_capture");
}

// test_capture.cpp - host tests for the frame capture (J8): the shader hash convention (canonical FNV-1a-64 to the walked
// end token, a CTAB holding 0x0000FFFF, shader model 1 operands and def literals), the capture name and frame rules, the ctl grammar;
// and source lints (key off = nothing hooked, every hook forwards, no game named in core). Built and run by proxy/tools/build.sh tests.
// The two hash vectors are shared with the game repo's catalogue tool (its tests check the same bytes give the same hex).
#include "testkit.h"
#include "capture.h"
#include "devcore.h"
#include <atomic>
#include <random>
#include <thread>

using namespace wsp;

// The capture's state word on the host: std::atomic<long> with InterlockedCompareExchange's contract (Cas returns the value it found).
struct TestCell {
    std::atomic<long> v{kCapIdle};
    long Load() const { return v.load(); }
    long Cas(long expected, long desired) { long e = expected; v.compare_exchange_strong(e, desired); return e; }
};
// A render thread that read the state before the ctl thread changed it: Load gives the stale value, the CAS sees the real one.
struct StaleCell : TestCell { long stale = kCapArmed; long Load() const { return stale; } };

// W19 (B32): a "render" thread stepping Presents and a "ctl" thread arming and timing out at random, seeded. Returns the number of
// invariant breaks; the outcome counts say every path was taken.
struct StressOut { int errors = 0, rounds = 0, done = 0, nothing = 0, abandoned = 0, refused = 0, lateFinish = 0, closedAbandoned = 0; long finalState = -1; };
static StressOut Stress(unsigned seed, int rounds) {
    TestCell c;
    std::atomic<int> errors{0}, waiting{0}, ctlFrames{1}, closedAbandoned{0}, lateFinish{0};
    std::atomic<long> ctlId{0}, doneId{0};
    std::atomic<bool> stop{false};
    std::thread render([&] {
        std::mt19937 rng(seed * 2 + 1);
        bool open = false; int frame = 0, frames = 0; long id = 0, idle = 0;
        while (!(stop.load() && c.Load() == kCapIdle && !open) && idle < 100000) {
            if (stop.load()) ++idle;
            switch (CapOnPresent(c, frame, frames)) {
            case CapStep::start:   // a recording starts only with a waiter and never over another
                if (open || waiting.load() != 1) ++errors;
                open = true; frame = 0; frames = ctlFrames.load(); id = ctlId.load();
                break;
            case CapStep::next_frame: if (!open) ++errors; ++frame; break;
            case CapStep::finish:
                if (!open) ++errors;
                open = false; doneId.store(id);
                if (!CapFinish(c)) ++lateFinish;   // the ctl abandoned it meanwhile: the render side closed and left Idle
                break;
            case CapStep::close_abandoned:
                if (!open) ++errors;
                open = false; ++closedAbandoned;
                if (!CapClosed(c)) ++errors;
                break;
            case CapStep::none: break;
            }
            const unsigned r = rng() % 16;
            for (unsigned i = 0, n = r == 0 ? 200 : r; i < n; ++i) std::this_thread::yield();
        }
        if (open || c.Load() != kCapIdle) ++errors;   // a state no one leaves, or a file left open
    });
    StressOut o;
    std::mt19937 rng(seed);
    auto waitDone = [&](unsigned polls) { for (unsigned i = 0; i < polls; ++i) { if (c.Load() == kCapDone) return true; std::this_thread::yield(); } return c.Load() == kCapDone; };
    for (int round = 1; round <= rounds; ++round) {
        if (c.Load() != kCapIdle) { ++o.refused; std::this_thread::yield(); continue; }   // the ctl's early refusal: it writes nothing shared unless Idle
        ctlFrames.store(1 + (int)(rng() % 3)); ctlId.store(round);
        waiting.store(1);
        if (CapArmFromCtl(c) != CapArm::ok) { ++errors; waiting.store(0); continue; }
        ++o.rounds;
        CapEnd e = waitDone(rng() % 4 == 0 ? 0 : rng() % 24) ? CapEnd::done : CapOnTimeout(c, false);
        if (e == CapEnd::wait_more) e = waitDone(rng() % 24) ? CapEnd::done : CapOnTimeout(c, true);
        if (e == CapEnd::done) {
            if (doneId.load() != round) ++errors;   // the result read is this capture's
            waiting.store(0);
            if (!CapRelease(c)) ++errors;
            ++o.done;
        } else if (e == CapEnd::nothing) { waiting.store(0); ++o.nothing; }
        else if (e == CapEnd::abandoned) { waiting.store(0); ++o.abandoned; }
        else ++errors;
    }
    stop.store(true);
    render.join();
    o.errors = errors.load(); o.lateFinish = lateFinish.load(); o.closedAbandoned = closedAbandoned.load(); o.finalState = c.Load();
    return o;
}

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    {   // W19 (B32): every transition of the capture state machine, one thread
        TestCell c;
        CHECK(CapOnPresent(c, 0, 1) == CapStep::none && c.Load() == kCapIdle);           // Idle: a Present does nothing
        CHECK(CapArmFromCtl(c) == CapArm::ok && c.Load() == kCapArmed);                  // ctl: Idle -> Armed
        CHECK(CapArmFromCtl(c) == CapArm::running && c.Load() == kCapArmed);
        CHECK(CapOnPresent(c, 0, 2) == CapStep::start && c.Load() == kCapRecording);     // render: Armed -> Recording first
        CHECK(CapArmFromCtl(c) == CapArm::running);
        CHECK(CapOnPresent(c, 0, 2) == CapStep::next_frame && c.Load() == kCapRecording);
        CHECK(CapOnPresent(c, 1, 2) == CapStep::finish && c.Load() == kCapRecording);    // the file closes before the state moves
        CHECK(CapFinish(c) && c.Load() == kCapDone);                                     // render: Recording -> Done
        CHECK(CapOnPresent(c, 0, 1) == CapStep::none && CapArmFromCtl(c) == CapArm::running && c.Load() == kCapDone);
        CHECK(CapRelease(c) && c.Load() == kCapIdle);                                    // ctl, after reading the result: Done -> Idle
        CHECK(!CapRelease(c) && c.Load() == kCapIdle);
    }
    {   // the first wait times out with nobody presenting: Armed -> Idle, nothing recorded, and a later Present does nothing
        TestCell c; CapArmFromCtl(c);
        CHECK(CapOnTimeout(c, false) == CapEnd::nothing && c.Load() == kCapIdle);
        CHECK(CapOnPresent(c, 0, 1) == CapStep::none && c.Load() == kCapIdle);
    }
    {   // race 1: the render side read Armed, then the ctl withdrew (Armed -> Idle) before its CAS: it does nothing at all
        StaleCell c; c.v.store(kCapIdle);
        CHECK(CapOnPresent(c, 0, 1) == CapStep::none && c.v.load() == kCapIdle);
    }
    {   // the first timeout lost to the render thread: wait the second; the second times out: Recording -> Abandoned, closed at the next Present
        TestCell c; CapArmFromCtl(c); CapOnPresent(c, 0, 3);
        CHECK(CapOnTimeout(c, false) == CapEnd::wait_more && c.Load() == kCapRecording);
        CHECK(CapOnTimeout(c, true) == CapEnd::abandoned && c.Load() == kCapAbandoned);
        CHECK(CapArmFromCtl(c) == CapArm::closing && c.Load() == kCapAbandoned);         // refused until the render thread closed it
        CHECK(CapOnPresent(c, 0, 3) == CapStep::close_abandoned && c.Load() == kCapAbandoned);
        CHECK(CapClosed(c) && c.Load() == kCapIdle);                                     // render: Abandoned -> Idle, nobody waits
        CHECK(CapArmFromCtl(c) == CapArm::ok);
    }
    {   // race 2, Done against Abandoned: the render finished just before the ctl's timeout: reported normally
        TestCell c; CapArmFromCtl(c); CapOnPresent(c, 0, 1);
        CHECK(CapOnPresent(c, 0, 1) == CapStep::finish && CapFinish(c));
        CHECK(CapOnTimeout(c, false) == CapEnd::done && c.Load() == kCapDone);
        CHECK(CapOnTimeout(c, true) == CapEnd::done && c.Load() == kCapDone);
        CHECK(CapRelease(c) && c.Load() == kCapIdle);
    }
    {   // ... and the other order: the ctl abandoned just before the render's Recording -> Done: the render closes and leaves Idle
        TestCell c; CapArmFromCtl(c); CapOnPresent(c, 0, 1);
        CHECK(CapOnPresent(c, 0, 1) == CapStep::finish);
        CHECK(CapOnTimeout(c, true) == CapEnd::abandoned);
        CHECK(!CapFinish(c) && c.Load() == kCapIdle);
        CHECK(CapArmFromCtl(c) == CapArm::ok);
    }
    {   // the refusals and the state names the results carry
        CHECK_EQ(std::string(CapRefusal(CapArm::running)), std::string("a capture is running"));
        CHECK_EQ(std::string(CapRefusal(CapArm::closing)), std::string("the previous capture is still closing: it ends at the next Present"));
        CHECK_EQ(std::string(CapStateName(kCapAbandoned)), std::string("abandoned"));
        CHECK_EQ(std::string(CapStateName(kCapIdle)), std::string("idle"));
    }
    {   // two threads, seeded: never a state no one leaves, never a recording without a waiter, never two at once, every path taken
        int errors = 0, rounds = 0, done = 0, nothing = 0, abandoned = 0;
        for (unsigned seed = 1; seed <= 4; ++seed) {
            const StressOut o = Stress(seed, 1500);
            if (o.errors || o.finalState != kCapIdle) printf("  stress seed %u: %d errors, final state %ld\n", seed, o.errors, o.finalState);
            errors += o.errors + (o.finalState != kCapIdle); rounds += o.rounds; done += o.done; nothing += o.nothing; abandoned += o.abandoned;
        }
        printf("  stress: %d captures, %d done, %d nothing recorded, %d abandoned\n", rounds, done, nothing, abandoned);
        CHECK_EQ(errors, 0);
        CHECK(done > 0 && nothing > 0 && abandoned > 0);
    }
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

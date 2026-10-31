// Host test: the crash handlers' stack policy (core/crashpolicy.h) and a lint that crash.cpp asks it before doing any work.
// Regression for the 4K resolution-change crash (proxy/runs/20261029_4kcrash): a stack overflow must never be logged or dumped on
// the overflowed thread.
#include "testkit.h"
#include "crashpolicy.h"

using wsp::CrashAction;
using wsp::CrashHandlerAction;

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    const uintptr_t low = 0x01871000;   // the 4K crash's main-thread stack reservation (the first consumer's WER dump, 2026-10-29)
    const uintptr_t AV = 0xC0000005u;
    // stack overflow: always deferred, whatever the stack and the mode
    CHECK(CrashHandlerAction(wsp::kStatusStackOverflow, low + 0x100000, low, true) == CrashAction::Defer);
    CHECK(CrashHandlerAction(wsp::kStatusStackOverflow, low + 0x100000, low, false) == CrashAction::Defer);
    // the dump's real numbers: ESP 4 bytes below the limit (already past it) and a few KB above it
    CHECK(CrashHandlerAction(AV, low - 4, low, true) == CrashAction::Defer);
    CHECK(CrashHandlerAction(AV, low + 0x2000, low, false) == CrashAction::Defer);
    CHECK(CrashHandlerAction(AV, low + wsp::kCrashLogStackNeed - 1, low, false) == CrashAction::Defer);
    // enough to log, not to dump
    CHECK(CrashHandlerAction(AV, low + wsp::kCrashLogStackNeed, low, false) == CrashAction::LogOnly);
    CHECK(CrashHandlerAction(AV, low + wsp::kCrashLogStackNeed, low, true) == CrashAction::LogOnly);
    CHECK(CrashHandlerAction(AV, low + wsp::kCrashDumpStackNeed - 1, low, true) == CrashAction::LogOnly);
    // plenty of stack
    CHECK(CrashHandlerAction(AV, low + wsp::kCrashDumpStackNeed, low, true) == CrashAction::LogAndDump);
    CHECK(CrashHandlerAction(AV, low + wsp::kCrashDumpStackNeed, low, false) == CrashAction::LogOnly);
    // unknown limits: the safe side
    CHECK(CrashHandlerAction(AV, low + 0x100000, 0, true) == CrashAction::Defer);

    // lint: both handlers decide through the policy before any log call, and the deferral path stays call-free
    const std::string src = tk::ReadFile("core/crash.cpp");
    CHECK(!src.empty());
    for (const char* h : {"LONG WINAPI TopLevel(", "LONG WINAPI Vectored("}) {
        const size_t at = src.find(h);
        CHECK(at != std::string::npos);
        if (at == std::string::npos) continue;
        const size_t pol = src.find("CrashHandlerAction(", at), log = src.find("LOG", at);
        CHECK(pol != std::string::npos && log != std::string::npos && pol < log);
    }
    const size_t d0 = src.find("void Defer("), d1 = src.find("\n}", d0);
    CHECK(d0 != std::string::npos && d1 != std::string::npos);
    if (d0 != std::string::npos && d1 != std::string::npos) {
        const std::string body = src.substr(d0, d1 - d0);
        CHECK(body.find("LOG") == std::string::npos && body.find("printf") == std::string::npos && body.find("std::") == std::string::npos);
    }
    return tk::Done("test_crash");
}

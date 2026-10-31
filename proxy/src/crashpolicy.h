// crashpolicy.h - what the in-process crash handlers may do on the faulting thread (pure logic, host-tested in tests/test_crash.cpp).
// Learning (J3, 2026-10-29, two WER dumps from the first consumer, its run 20261029_4kcrash): at 4K the main thread's 1 MB stack
// overflowed (STATUS_STACK_OVERFLOW first-chance); the vectored handler then formatted a log line (~5 KB of stack: LogWrite's buffers
// and vsnprintf) on the exhausted stack and took an access violation inside d3d9.dll, so the proxy turned the overflow into a crash
// of its own and hid the real culprit. Rule: on a stack overflow, or with too little stack left, the handler only records the event
// in static memory; it is logged later from a thread with stack (detach, the next top-level filter call, CrashFlushPending).
#pragma once
#include <cstddef>
#include <cstdint>

namespace wsp {

constexpr uint32_t kStatusStackOverflow = 0xC00000FDu;
constexpr size_t kCrashLogStackNeed = 32 * 1024;    // a log line: LogWrite (~4.3 KB) + Where + vsnprintf, with margin
constexpr size_t kCrashDumpStackNeed = 128 * 1024;  // MiniDumpWriteDump in-process: dbghelp walks modules and memory lists

enum class CrashAction { Defer, LogOnly, LogAndDump };

// code: the exception code; sp: the stack pointer in the handler; stackLow: the lowest address of the thread's stack RESERVATION
// (TEB DeallocationStack / GetCurrentThreadStackLimits low), 0 when unknown; wantDump: the mode asks for a dump of this exception.
inline CrashAction CrashHandlerAction(uint32_t code, uintptr_t sp, uintptr_t stackLow, bool wantDump) {
    if (code == kStatusStackOverflow) return CrashAction::Defer;   // never run more code than needed on an overflowed stack
    if (stackLow == 0 || sp <= stackLow) return CrashAction::Defer; // unknown limits or nonsense: the safe side
    const size_t left = (size_t)(sp - stackLow);
    if (left < kCrashLogStackNeed) return CrashAction::Defer;
    if (wantDump && left >= kCrashDumpStackNeed) return CrashAction::LogAndDump;
    return CrashAction::LogOnly;
}

} // namespace wsp

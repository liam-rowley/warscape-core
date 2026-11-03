#pragma once
// Frame capture, pure core (no Windows headers; host tests in proxy/tests/test_capture.cpp). Driver: capture.cpp (J8).
//   - the shader hash convention, fixed once: canonical FNV-1a-64 over the whole bytecode up to and including the real end token,
//     found by walking the instruction stream (ShaderLength), never by the first 0x0000FFFF DWORD: a D3DX CTAB comment can hold that
//     DWORD (an older proxy's trap: a dropped digit in the basis and a cut inside the CTAB gave ~50 % "unknown" shaders)
//   - the capture name rule and the `capture` record line format (one call per line, documented in the game repo's proxy README)
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>

namespace wsp {

const uint64_t kFnvBasis = 14695981039346656037ULL, kFnvPrime = 1099511628211ULL;   // canonical FNV-1a-64
inline uint64_t Fnv1a64(const void* data, size_t n, uint64_t h = kFnvBasis) {
    const auto* p = static_cast<const uint8_t*>(data);
    for (size_t i = 0; i < n; ++i) { h ^= p[i]; h *= kFnvPrime; }
    return h;
}

// The bytecode's length in bytes, the end token (0x0000FFFF) included, found by walking the token stream; 0 = not a shader model 1-3
// stream or no end token within maxBytes. Rules (d3d9types.h D3DSI_*): token 0 is the version (0xFFFE____ vertex, 0xFFFF____ pixel);
// a comment (opcode 0xFFFE) is followed by bits 16-30 DWORDs, whatever they hold (a CTAB may hold 0x0000FFFF); shader model 2 and up
// give an instruction's operand count in bits 24-27; shader model 1 does not, so its operands are the following tokens with bit 31 set,
// except def (opcode 0x51: four raw floats, which may have bit 31 clear or set) after its register token.
inline size_t ShaderLength(const uint32_t* t, size_t maxBytes) {
    const size_t n = maxBytes / 4;
    if (n < 2) return 0;
    const uint32_t ver = t[0];
    if ((ver & 0xFFFE0000u) != 0xFFFE0000u) return 0;   // 0xFFFE (vs) or 0xFFFF (ps)
    const unsigned major = (ver >> 8) & 0xFF;
    if (major < 1 || major > 3) return 0;
    size_t i = 1;
    while (i < n) {
        const uint32_t tok = t[i];
        if (tok == 0x0000FFFFu) return (i + 1) * 4;
        const uint32_t op = tok & 0xFFFF;
        if (op == 0xFFFE) { i += 1 + ((tok >> 16) & 0x7FFF); continue; }   // comment
        if (major >= 2) { i += 1 + ((tok >> 24) & 0x0F); continue; }
        if (op == 0x51) { i += 6; continue; }                             // def c#, f, f, f, f
        ++i;
        while (i < n && (t[i] & 0x80000000u)) ++i;
    }
    return 0;
}

inline std::string Hex64(uint64_t h) { char b[20]; snprintf(b, sizeof b, "%016llx", (unsigned long long)h); return b; }

// The hash of a shader as the catalogue names it; ok=false (hash of maxBytes, for the record) when the walk finds no end token.
inline uint64_t ShaderHash(const void* code, size_t maxBytes, size_t& len, bool& ok) {
    len = ShaderLength(static_cast<const uint32_t*>(code), maxBytes);
    ok = len != 0;
    return Fnv1a64(code, ok ? len : maxBytes);
}

// `capture <name> [frames]`: a name is 1-48 of A-Za-z0-9._- not starting with . (it is a folder name); frames 1..kCaptureMaxFrames.
const int kCaptureMaxFrames = 8;
inline bool ValidCaptureName(const std::string& s) {
    if (s.empty() || s.size() > 48 || s[0] == '.') return false;
    for (char c : s) if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-')) return false;
    return true;
}
struct CaptureArgs { std::string name, error; int frames = 1; };
inline CaptureArgs ParseCaptureArgs(const std::string& arg) {
    CaptureArgs a;
    const size_t sp = arg.find(' ');
    a.name = arg.substr(0, sp);
    std::string rest = sp == std::string::npos ? "" : arg.substr(sp + 1);
    while (!rest.empty() && rest[0] == ' ') rest.erase(0, 1);
    while (!rest.empty() && rest.back() == ' ') rest.pop_back();
    if (!ValidCaptureName(a.name)) { a.error = "capture needs a name (1-48 of A-Za-z0-9._-, not starting with .)"; return a; }
    if (!rest.empty()) {
        bool digits = rest.size() <= 2;
        for (char c : rest) if (c < '0' || c > '9') digits = false;
        a.frames = digits ? atoi(rest.c_str()) : 0;
        if (a.frames < 1 || a.frames > kCaptureMaxFrames) { a.error = "capture: frames must be 1 to " + std::to_string(kCaptureMaxFrames); return a; }
    }
    return a;
}

// ---- the capture state machine (W19, B32): one word, every transition a compare-and-swap, no lock ---------------------------------
// Threads: the ctl thread arms and waits; the render thread (the one whose Present takes the arm) records. A Cell gives Load() and
// Cas(expected, desired) -> the value it found (InterlockedCompareExchange's contract): capture.cpp wraps a volatile LONG, the host
// test a std::atomic<long>. Who moves what:
//   ctl     Idle -> Armed (arm)                Armed -> Idle (first wait timed out)   Recording -> Abandoned (second wait timed out)
//           Done -> Idle (result read)
//   render  Armed -> Recording (at a Present, before the file opens)   Recording -> Done (file closed)   Abandoned -> Idle (file closed)
// Only the ctl leaves Idle and Done; only the render thread leaves Recording for Done and Abandoned for Idle.
enum : long { kCapIdle = 0, kCapArmed = 1, kCapRecording = 2, kCapDone = 3, kCapAbandoned = 4 };
inline const char* CapStateName(long s) {
    return s == kCapIdle ? "idle" : s == kCapArmed ? "armed" : s == kCapRecording ? "recording" : s == kCapDone ? "done" : s == kCapAbandoned ? "abandoned" : "?";
}

enum class CapArm { ok, running, closing };
template <class Cell> CapArm CapArmFromCtl(Cell& c) {   // ctl: Idle -> Armed
    const long was = c.Cas(kCapIdle, kCapArmed);
    return was == kCapIdle ? CapArm::ok : was == kCapAbandoned ? CapArm::closing : CapArm::running;
}
inline const char* CapRefusal(CapArm a) {
    return a == CapArm::closing ? "the previous capture is still closing: it ends at the next Present" : a == CapArm::running ? "a capture is running" : "";
}

// render, at a Present (before the real one); `frame` is the 0-based frame just presented, `frames` the capture's count.
//   start: Armed -> Recording is done; now open frame.txt, write the header and the STATE block, then set s_rec. A failed CAS (the
//          ctl withdrew after this thread read Armed) gives none: nothing at all happens.
//   next_frame / finish: the recording thread's own decision (no transition); finish: write PRESENT, clear s_rec, close, CapFinish.
//   close_abandoned: write ABANDONED, clear s_rec, close, CapClosed.
enum class CapStep { none, start, next_frame, finish, close_abandoned };
template <class Cell> CapStep CapOnPresent(Cell& c, int frame, int frames) {
    const long st = c.Load();
    if (st == kCapArmed) return c.Cas(kCapArmed, kCapRecording) == kCapArmed ? CapStep::start : CapStep::none;
    if (st == kCapRecording) return frame + 1 < frames ? CapStep::next_frame : CapStep::finish;
    if (st == kCapAbandoned) return CapStep::close_abandoned;
    return CapStep::none;
}
// render, the file closed (the last frame, or a failed open): Recording -> Done, then the event. False when the ctl abandoned it first:
// then Abandoned -> Idle here (nobody waits, no event).
template <class Cell> bool CapFinish(Cell& c) {
    if (c.Cas(kCapRecording, kCapDone) == kCapRecording) return true;
    c.Cas(kCapAbandoned, kCapIdle);
    return false;
}
template <class Cell> bool CapClosed(Cell& c) { return c.Cas(kCapAbandoned, kCapIdle) == kCapAbandoned; }   // render: Abandoned -> Idle

// ctl, a wait timed out. first: Armed -> Idle (nothing recorded); lost to the render thread: Recording -> wait_more, Done -> done.
// second: Recording -> Abandoned (failed; read none of the render thread's counters); lost: Done -> done (finished just in time).
enum class CapEnd { done, nothing, wait_more, abandoned };
template <class Cell> CapEnd CapOnTimeout(Cell& c, bool second) {
    if (!second) {
        const long was = c.Cas(kCapArmed, kCapIdle);
        return was == kCapArmed ? CapEnd::nothing : was == kCapDone ? CapEnd::done : CapEnd::wait_more;
    }
    const long was = c.Cas(kCapRecording, kCapAbandoned);
    return was == kCapDone ? CapEnd::done : CapEnd::abandoned;   // Recording (or, never by these rules, anything else: not Done, so not read)
}
template <class Cell> bool CapRelease(Cell& c) { return c.Cas(kCapDone, kCapIdle) == kCapDone; }   // ctl, the result read: Done -> Idle

// A float as the record writes it: shortest text that reads back to the same float (%.9g), so the values are exact.
inline void AppendFloat(std::string& o, float f) { char b[24]; snprintf(b, sizeof b, " %.9g", (double)f); o += b; }
inline void AppendU(std::string& o, unsigned long long v) { char b[24]; snprintf(b, sizeof b, " %llu", v); o += b; }
inline void AppendI(std::string& o, long long v) { char b[24]; snprintf(b, sizeof b, " %lld", v); o += b; }
inline void AppendX(std::string& o, unsigned long long v) { char b[24]; snprintf(b, sizeof b, " %llx", v); o += b; }

} // namespace wsp

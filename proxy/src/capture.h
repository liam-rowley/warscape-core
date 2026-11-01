#pragma once
// Frame capture, pure core (no Windows headers; host tests in proxy/tests/test_capture.cpp). Driver: capture.cpp (J8).
//   - the shader hash convention, fixed once: canonical FNV-1a-64 over the whole bytecode up to and including the real end token,
//     found by walking the instruction stream (ShaderLength), never by the first 0x0000FFFF DWORD: a D3DX CTAB comment can hold that
//     DWORD (empire-remastered's trap: a dropped digit in the basis and a cut inside the CTAB gave ~50 % "unknown" shaders)
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

// A float as the record writes it: shortest text that reads back to the same float (%.9g), so the values are exact.
inline void AppendFloat(std::string& o, float f) { char b[24]; snprintf(b, sizeof b, " %.9g", (double)f); o += b; }
inline void AppendU(std::string& o, unsigned long long v) { char b[24]; snprintf(b, sizeof b, " %llu", v); o += b; }
inline void AppendI(std::string& o, long long v) { char b[24]; snprintf(b, sizeof b, " %lld", v); o += b; }
inline void AppendX(std::string& o, unsigned long long v) { char b[24]; snprintf(b, sizeof b, " %llx", v); o += b; }

} // namespace wsp

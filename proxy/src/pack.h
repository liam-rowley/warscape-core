#pragma once
// Warscape PFH0 pack index: pure core (host tests in proxy/tests/test_dev.cpp). Used to name the movie behind a Bink file handle
// (the engine hands Bink a pack handle positioned at the entry) and to read a vanilla script entry for a Lua wrapper.
// Layout (little endian): "PFH0", type (4 = movie pack, auto-loaded), 0, size of the pack-name list, entry count, index size;
// the pack-name list; the index (u32 size + NUL-terminated path per entry); the data, in index order. Same reader as
// proxy/tools/pack_list.py.
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace wsp {

struct PackEntry { uint64_t offset; uint32_t size; std::string path; };   // path lower case, '\' separators
struct PackIndex { uint32_t type = 0; std::vector<PackEntry> entries; std::string error; };

inline uint32_t Le32(const unsigned char* p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }

// hdr = the first 24 bytes; returns the number of bytes of the name list + index that follow the header (0 = not a pack).
inline uint64_t PackIndexBytes(const unsigned char* hdr, size_t n, uint32_t* type = nullptr) {
    if (n < 24 || memcmp(hdr, "PFH0", 4) != 0) return 0;
    if (type) *type = Le32(hdr + 4);
    return (uint64_t)Le32(hdr + 12) + Le32(hdr + 20);
}

// buf = header + name list + index (at least 24 + PackIndexBytes).
inline PackIndex ParsePackIndex(const unsigned char* buf, size_t n) {
    PackIndex px;
    if (n < 24 || memcmp(buf, "PFH0", 4) != 0) { px.error = "not a PFH0 pack"; return px; }
    px.type = Le32(buf + 4);
    const uint32_t names = Le32(buf + 12), count = Le32(buf + 16), isize = Le32(buf + 20);
    if ((uint64_t)24 + names + isize > n) { px.error = "index truncated"; return px; }
    const unsigned char* idx = buf + 24 + names;
    uint64_t off = 24ull + names + isize; size_t pos = 0;
    for (uint32_t i = 0; i < count; ++i) {
        if (pos + 5 > isize) { px.error = "index ends early"; return px; }
        const uint32_t sz = Le32(idx + pos); pos += 4;
        size_t len = 0; while (pos + len < isize && idx[pos + len]) ++len;
        if (pos + len >= isize) { px.error = "unterminated entry name"; return px; }
        std::string name((const char*)idx + pos, len); pos += len + 1;
        for (char& c : name) { if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a'); if (c == '/') c = '\\'; }
        px.entries.push_back({ off, sz, name });
        off += sz;
    }
    return px;
}

inline const PackEntry* PackFind(const PackIndex& px, const std::string& lowerPath) {
    for (const auto& e : px.entries) if (e.path == lowerPath) return &e;
    return nullptr;
}
inline const PackEntry* PackAt(const PackIndex& px, uint64_t pos) {
    for (const auto& e : px.entries) if (pos >= e.offset && pos < e.offset + e.size) return &e;
    return nullptr;
}

} // namespace wsp

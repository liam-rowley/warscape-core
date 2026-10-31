#pragma once
// PE32 reading for the proxy core: headers, sections, file-offset/RVA mapping, base relocations. Pure: no Windows headers, no
// globals, host-testable with g++ (proxy/tests). Ported from empire-remastered rml_mod/src/exe_patches.h (ParsePe, ImageView,
// RelocsInRange), game-agnostic. The same ImageView reads a MAPPED module (in process; RVA-addressed) or a FILE (tools, tests).
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

namespace wsp {

struct Section { char name[9]; uint32_t rva, vsize, rawOff, rawSize, characteristics; };
struct PeInfo {
    bool ok = false; std::string error;
    uint16_t machine = 0, characteristics = 0, dllCharacteristics = 0, nSections = 0;
    uint32_t timeDateStamp = 0, sizeOfImage = 0, sizeOfHeaders = 0, checkSum = 0, entryRva = 0, preferredBase = 0;
    uint32_t relocRva = 0, relocSize = 0, iatRva = 0, iatSize = 0;
    std::vector<Section> sections;
};
constexpr uint32_t kScnExecute = 0x20000000u;      // IMAGE_SCN_MEM_EXECUTE
constexpr uint16_t kMachineI386 = 0x014C;

inline uint16_t Rd16(const uint8_t* p) { return (uint16_t)(p[0] | (p[1] << 8)); }
inline uint32_t Rd32(const uint8_t* p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }
inline void Wr32(uint8_t* p, uint32_t v) { for (int i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8 * i)); }

// Parses the PE32 headers at p (n readable bytes): a mapped image's first page or the start of the file (same layout).
inline PeInfo ParsePe(const uint8_t* p, size_t n) {
    PeInfo pe;
    auto fail = [&](const char* e) { pe.ok = false; pe.error = e; return pe; };
    if (!p || n < 0x40 || p[0] != 'M' || p[1] != 'Z') return fail("no MZ header");
    const uint32_t lfanew = Rd32(p + 0x3C);
    if (lfanew > n || n - lfanew < 24 + 96) return fail("e_lfanew out of range");
    const uint8_t* nt = p + lfanew;
    if (memcmp(nt, "PE\0\0", 4) != 0) return fail("no PE signature");
    pe.machine = Rd16(nt + 4); pe.nSections = Rd16(nt + 6); pe.timeDateStamp = Rd32(nt + 8);
    const uint16_t optSize = Rd16(nt + 20);
    pe.characteristics = Rd16(nt + 22);
    const uint8_t* opt = nt + 24;
    if (Rd16(opt) != 0x10B) return fail("not a PE32 (32-bit) optional header");
    if (optSize < 96 || (size_t)(opt - p) + optSize > n) return fail("optional header truncated");
    pe.entryRva = Rd32(opt + 16); pe.preferredBase = Rd32(opt + 28); pe.sizeOfImage = Rd32(opt + 56);
    pe.sizeOfHeaders = Rd32(opt + 60); pe.checkSum = Rd32(opt + 64); pe.dllCharacteristics = Rd16(opt + 70);
    const uint32_t nDirs = Rd32(opt + 92);
    if (nDirs > 5 && optSize >= 96 + 6 * 8) { pe.relocRva = Rd32(opt + 96 + 5 * 8); pe.relocSize = Rd32(opt + 96 + 5 * 8 + 4); }
    if (nDirs > 12 && optSize >= 96 + 13 * 8) { pe.iatRva = Rd32(opt + 96 + 12 * 8); pe.iatSize = Rd32(opt + 96 + 12 * 8 + 4); }
    const uint8_t* sh = opt + optSize;
    if (pe.nSections == 0 || pe.nSections > 96 || (size_t)(sh - p) + (size_t)pe.nSections * 40 > n) return fail("section table truncated");
    for (unsigned i = 0; i < pe.nSections; ++i, sh += 40) {
        Section s{}; memcpy(s.name, sh, 8); s.name[8] = 0;
        s.vsize = Rd32(sh + 8); s.rva = Rd32(sh + 12); s.rawSize = Rd32(sh + 16); s.rawOff = Rd32(sh + 20); s.characteristics = Rd32(sh + 36);
        pe.sections.push_back(s);
    }
    pe.ok = true;
    return pe;
}

// Bytes of a section that are the FILE's bytes in memory: the first min(rawSize, VirtualSize) (VirtualSize 0 = rawSize).
inline uint32_t FileBackedSize(const Section& s) { return s.vsize && s.vsize < s.rawSize ? s.vsize : s.rawSize; }

// RVA -> index of the section whose file-backed bytes hold [rva, rva+len), or -1.
inline int SectionOfRva(const PeInfo& pe, uint32_t rva, uint32_t len) {
    for (size_t i = 0; i < pe.sections.size(); ++i) {
        const Section& s = pe.sections[i];
        if (rva >= s.rva && (uint64_t)rva - s.rva + len <= FileBackedSize(s)) return (int)i;
    }
    return -1;
}

// The image a check reads: the MAPPED module (data = module base, RVA-addressed) or the FILE (data = file bytes; RVAs go
// through the section table). `readable` guards in-process reads (VirtualQuery: a page may be reserved or no-access).
struct ImageView {
    const uint8_t* data = nullptr; size_t size = 0; const PeInfo* pe = nullptr; bool file = false;
    bool (*readable)(const void* p, size_t n) = nullptr;
    const uint8_t* At(uint32_t rva, uint32_t len) const {
        if (!data || !pe) return nullptr;
        if (!file) {
            if ((uint64_t)rva + len > size) return nullptr;
            return !readable || readable(data + rva, len) ? data + rva : nullptr;
        }
        const int s = SectionOfRva(*pe, rva, len);
        if (s < 0) return (uint64_t)rva + len <= pe->sizeOfHeaders && (uint64_t)rva + len <= size ? data + rva : nullptr;
        const uint64_t off = (uint64_t)pe->sections[s].rawOff + (rva - pe->sections[s].rva);
        return off + len <= size ? data + off : nullptr;
    }
};

// RVAs of every base-relocated dword (HIGHLOW; any other non-padding type is treated as 4 bytes too) that intersects [lo, hi).
inline void RelocsInRange(const ImageView& v, uint32_t lo, uint32_t hi, std::vector<uint32_t>& out) {
    const PeInfo& pe = *v.pe;
    if (!pe.relocRva || pe.relocSize < 8) return;
    uint32_t pos = 0;
    while (pos + 8 <= pe.relocSize) {
        const uint8_t* b = v.At(pe.relocRva + pos, 8);
        if (!b) return;
        const uint32_t page = Rd32(b), bsize = Rd32(b + 4);
        if (bsize < 8 || pos + bsize > pe.relocSize) return;
        if ((uint64_t)page + 0x1000 + 4 > lo && page < hi) {
            const uint8_t* e = v.At(pe.relocRva + pos + 8, bsize - 8);
            if (!e) return;
            for (uint32_t k = 0; k + 2 <= bsize - 8; k += 2) {
                const uint16_t w = Rd16(e + k);
                if ((w >> 12) == 0) continue;   // IMAGE_REL_BASED_ABSOLUTE = padding
                const uint32_t r = page + (w & 0xFFF);
                if ((uint64_t)r + 4 > lo && r < hi) out.push_back(r);
            }
        }
        pos += bsize;
    }
}

// Load delta for ReadUnrelocated: actual base - the FILE's OptionalHeader.ImageBase. Never take the preferred base from the
// mapped header: the loader rewrites it to the actual base, so the delta would always be 0 (PC 2026-10-28,
// proxy/runs/20261028_pctest). fileImageBase 0 (the file header was not read) = no delta: the caller must not patch.
inline bool LoadDelta(uintptr_t actualBase, uint32_t fileImageBase, uint32_t& delta) {
    if (!fileImageBase || (fileImageBase & 0xFFFF)) return false;   // PE image bases are 64 KiB aligned
    delta = (uint32_t)actualBase - fileImageBase;
    return true;
}

// Reads [rva, rva+len) as the FILE holds it: every relocated dword that overlaps the range has the load delta (actual base -
// preferred base) taken off, so a static address compares equal at any ASLR base. delta 0 for a file view. false = unreadable.
inline bool ReadUnrelocated(const ImageView& v, uint32_t rva, uint32_t len, uint32_t delta, uint8_t* out) {
    std::vector<uint32_t> rel;
    RelocsInRange(v, rva, rva + len, rel);
    uint32_t lo = rva, hi = rva + len;
    for (uint32_t r : rel) { if (r < lo) lo = r; if (r + 4 > hi) hi = r + 4; }
    const uint8_t* p = v.At(lo, hi - lo);
    if (!p) return false;
    std::vector<uint8_t> w(p, p + (hi - lo));
    if (delta) for (uint32_t r : rel) Wr32(&w[r - lo], Rd32(&w[r - lo]) - delta);
    memcpy(out, &w[rva - lo], len);
    return true;
}

} // namespace wsp

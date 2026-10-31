#pragma once
// Host-test kit: a tiny check framework and a synthetic PE32 image builder (file layout and mapped layout, a .reloc table,
// rebasing for ASLR). No Windows headers. Used by every proxy/tests/test_*.cpp (built and run by proxy/tools/build.sh tests).
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include "pe.h"

namespace tk {

inline int g_fail = 0, g_pass = 0;
// Where the tests read sources from (build.sh passes all three): the core sources, the game's proxy adapter, these tests. A path in
// ReadFile starts with core/, adapter/ or tests/ and is resolved against them, so the tests name no checkout layout and no game.
inline std::string g_src = ".", g_adapter = ".", g_tests = ".";
#define CHECK(c) do { if (c) ++tk::g_pass; else { ++tk::g_fail; printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)
#define CHECK_EQ(a, b) do { auto _a = (a); auto _b = (b); if (_a == _b) ++tk::g_pass; else { ++tk::g_fail; \
    std::ostringstream _s; _s << _a << " != " << _b; printf("  FAIL %s:%d: %s == %s (%s)\n", __FILE__, __LINE__, #a, #b, _s.str().c_str()); } } while (0)
inline void Args(int argc, char** argv) {
    for (int i = 1; i + 1 < argc; ++i) {
        if (!strcmp(argv[i], "--src")) g_src = argv[i + 1];
        else if (!strcmp(argv[i], "--adapter")) g_adapter = argv[i + 1];
        else if (!strcmp(argv[i], "--tests")) g_tests = argv[i + 1];
    }
}
inline int Done(const char* name) { printf("%s: %d passed, %d failed\n", name, g_pass, g_fail); return g_fail ? 1 : 0; }
inline std::string Resolve(const std::string& rel) {
    for (auto [pre, dir] : { std::pair<const char*, std::string*>{ "core/", &g_src }, { "adapter/", &g_adapter }, { "tests/", &g_tests } })
        if (rel.rfind(pre, 0) == 0) return *dir + "/" + rel.substr(strlen(pre));
    return rel;
}
inline std::string ReadFile(const std::string& rel) { std::ifstream f(Resolve(rel), std::ios::binary); std::stringstream s; s << f.rdbuf(); return s.str(); }
// A string field of a flat JSON object (identity.json): enough for the adapter's names, not a JSON parser.
inline std::string JsonField(const std::string& j, const std::string& key) {
    const size_t k = j.find("\"" + key + "\""); if (k == std::string::npos) return "";
    const size_t a = j.find('"', j.find(':', k) + 1); const size_t b = j.find('"', a + 1);
    return a == std::string::npos || b == std::string::npos ? "" : j.substr(a + 1, b - a - 1);
}
// The adapter's shipped config file (identity.json config_file), generated from the config_keys registry.
inline std::string AdapterIni() { return ReadFile("adapter/" + JsonField(ReadFile("adapter/identity.json"), "config_file")); }

struct SecSpec { const char* name; uint32_t rva, vsize, rawSize, characteristics; };

// A PE32 image: headers in the first 0x400 bytes, sections laid out at file offsets that differ from their RVAs (as real exes do).
struct Image {
    std::vector<uint8_t> file;      // file layout
    std::vector<SecSpec> secs;
    std::vector<uint32_t> rawOff;
    uint32_t sizeOfImage = 0, preferredBase = 0x400000, tds = 0x645e917f;
    uint16_t machine = 0x14C;
    std::vector<uint32_t> relocs;   // RVAs of HIGHLOW dwords
    uint32_t relocRva = 0, relocSize = 0;

    static Image Make(std::vector<SecSpec> s, uint32_t sizeOfImage) {
        Image im; im.secs = s; im.sizeOfImage = sizeOfImage;
        uint32_t off = 0x400;
        for (auto& x : s) { im.rawOff.push_back(off); off += x.rawSize; }
        im.file.assign(off, 0);
        im.WriteHeaders();
        return im;
    }
    int SecOf(uint32_t rva) const { for (size_t i = 0; i < secs.size(); ++i) if (rva >= secs[i].rva && rva < secs[i].rva + secs[i].rawSize) return (int)i; return -1; }
    uint8_t* F(uint32_t rva) { const int s = SecOf(rva); return s < 0 ? nullptr : &file[rawOff[s] + (rva - secs[s].rva)]; }
    void Put(uint32_t rva, std::vector<uint8_t> b) { memcpy(F(rva), b.data(), b.size()); }
    void Put32(uint32_t rva, uint32_t v) { wsp::Wr32(F(rva), v); }
    // Adds a .reloc block list for `relocs`, written into the section named ".reloc" (must exist).
    void BuildRelocs() {
        std::vector<uint8_t> t;
        std::vector<uint32_t> r = relocs;
        std::sort(r.begin(), r.end());
        size_t i = 0;
        while (i < r.size()) {
            const uint32_t page = r[i] & ~0xFFFu;
            std::vector<uint16_t> e;
            while (i < r.size() && (r[i] & ~0xFFFu) == page) e.push_back((uint16_t)(0x3000 | (r[i++] & 0xFFF)));
            if (e.size() % 2) e.push_back(0);
            const uint32_t sz = 8 + 2 * (uint32_t)e.size();
            uint8_t h[8]; wsp::Wr32(h, page); wsp::Wr32(h + 4, sz);
            t.insert(t.end(), h, h + 8);
            for (uint16_t w : e) { t.push_back((uint8_t)w); t.push_back((uint8_t)(w >> 8)); }
        }
        for (size_t k = 0; k < secs.size(); ++k) if (!strcmp(secs[k].name, ".reloc")) { relocRva = secs[k].rva; memcpy(&file[rawOff[k]], t.data(), t.size()); }
        relocSize = (uint32_t)t.size();
        WriteHeaders();
    }
    void WriteHeaders() {
        uint8_t* p = file.data();
        memset(p, 0, 0x400);
        p[0] = 'M'; p[1] = 'Z'; wsp::Wr32(p + 0x3C, 0x80);
        uint8_t* nt = p + 0x80; memcpy(nt, "PE\0\0", 4);
        nt[4] = (uint8_t)machine; nt[5] = (uint8_t)(machine >> 8);
        nt[6] = (uint8_t)secs.size(); wsp::Wr32(nt + 8, tds);
        nt[20] = 0xE0; nt[22] = 0x22;   // SizeOfOptionalHeader 224; EXECUTABLE | LARGE_ADDRESS_AWARE
        uint8_t* opt = nt + 24; opt[0] = 0x0B; opt[1] = 0x01;
        wsp::Wr32(opt + 16, secs.empty() ? 0 : secs[0].rva);
        wsp::Wr32(opt + 28, preferredBase); wsp::Wr32(opt + 56, sizeOfImage); wsp::Wr32(opt + 60, 0x400);
        opt[70] = 0x40; opt[71] = 0x01;   // DYNAMIC_BASE | NX_COMPAT
        wsp::Wr32(opt + 92, 16);
        wsp::Wr32(opt + 96 + 5 * 8, relocRva); wsp::Wr32(opt + 96 + 5 * 8 + 4, relocSize);
        uint8_t* sh = opt + 224;
        for (size_t i = 0; i < secs.size(); ++i, sh += 40) {
            memcpy(sh, secs[i].name, strlen(secs[i].name));
            wsp::Wr32(sh + 8, secs[i].vsize); wsp::Wr32(sh + 12, secs[i].rva); wsp::Wr32(sh + 16, secs[i].rawSize);
            wsp::Wr32(sh + 20, rawOff[i]); wsp::Wr32(sh + 36, secs[i].characteristics);
        }
    }
    // The mapped image the loader would produce at `base` (relocations applied).
    std::vector<uint8_t> Mapped(uint32_t base) const {
        std::vector<uint8_t> m(sizeOfImage, 0);
        memcpy(m.data(), file.data(), 0x400);
        for (size_t i = 0; i < secs.size(); ++i) memcpy(&m[secs[i].rva], &file[rawOff[i]], secs[i].rawSize);
        const uint32_t d = base - preferredBase;
        for (uint32_t r : relocs) wsp::Wr32(&m[r], wsp::Rd32(&m[r]) + d);
        // The Windows loader rewrites OptionalHeader.ImageBase in the MAPPED header to the actual base (seen on the PC,
        // proxy/runs/20261028_pctest: the log read "preferred 0x00610000"); the preferred base only survives in the file.
        const uint32_t lfanew = wsp::Rd32(&m[0x3c]);
        wsp::Wr32(&m[lfanew + 24 + 28], base);
        return m;
    }
};

// A real game exe's section layout (the first consumer's, measured 2026-10-28), scaled down: .text exec, .rdata, .data (vsize > raw), .reloc.
inline Image GameLike() {
    Image im = Image::Make({ { ".text", 0x1000, 0x3000, 0x3000, 0x60000020 }, { ".rdata", 0x4000, 0x1000, 0x1000, 0x40000040 },
                             { ".data", 0x5000, 0x4000, 0x1000, 0xC0000040 }, { ".reloc", 0x9000, 0x1000, 0x1000, 0x42000040 } }, 0xA000);
    for (uint32_t i = 0; i < 0x3000; ++i) im.file[im.rawOff[0] + i] = 0xCC;   // int3 padding, like the gaps between functions
    return im;
}

inline wsp::ImageView FileView(const Image& im, wsp::PeInfo& pe) {
    pe = wsp::ParsePe(im.file.data(), im.file.size());
    wsp::ImageView v; v.data = im.file.data(); v.size = im.file.size(); v.pe = &pe; v.file = true; return v;
}
inline wsp::ImageView MappedView(const std::vector<uint8_t>& m, wsp::PeInfo& pe) {
    pe = wsp::ParsePe(m.data(), 0x1000);
    wsp::ImageView v; v.data = m.data(); v.size = m.size(); v.pe = &pe; v.file = false; return v;
}

} // namespace tk

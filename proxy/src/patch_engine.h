#pragma once
// Runtime patch engine: pure core (no Windows headers, no globals; host tests in proxy/tests/test_patch_engine.cpp on a synthetic
// image). The driver (patch_driver.cpp) runs it once from DllMain when PlanEngine(...).patches is true, and writes with
// VirtualProtect + FlushInstructionCache. The exe on disk is never touched (D2).
//
// The site table is GENERATED from the engine_sites registry (proxy/tools/gen_tables.py; never edit it by hand). Byte layout of a
// site (the registry has one RVA, so the convention is fixed here and checked by the generator):
//     rva                      rva + len(anchor)
//     | anchor_bytes ...       | stock_bytes ...   (patch_bytes replace stock_bytes; a hook detours at rva + len(anchor))
// The anchor is the fixed context the site is recognised by (an opcode before an immediate, the padding before a function).
// Checks, after rebasing (RVA + the actual module base; ASLR is on): the site lies in one section's file-backed bytes (a hook in an
// executable one); anchor and stock compare equal after taking the load delta off every relocated dword (ReadUnrelocated); a
// patch's changing bytes carry no relocation. A patch site whose bytes already equal patch_bytes counts as done. ANY bad site ->
// nothing is written (all-or-nothing), and every site is still checked and logged. Disabled sites (their config key is off) are
// checked (they are part of the exe's identity) but never written. A value row (valueKey, W7) takes its bytes from a numeric config
// key: patch_value.h resolves the table into an effective copy first (the key at 0 or a refused value = the site disabled, i.e. checked,
// left stock), so these checks hold for value rows exactly as for fixed rows. An absolute address inside the anchor (c7 05 <abs32>
// <imm32>) is compared unrelocated, and its relocation ends where the value starts, so it does not count against the value (B41).
// docs/PROXY_SITES.md is the overview.
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include "pe.h"

namespace wsp {

constexpr unsigned kMaxSiteBytes = 32;
enum SiteKind : uint8_t { kPatch = 0, kHook = 1 };
enum SiteValueType : uint8_t { kValueNone = 0, kValueF32 = 1, kValueI32 = 2 };   // a value row's encoding (its key's type)

struct SiteDef {
    const char* id;          // engine_sites id
    uint8_t kind;            // SiteKind
    uint32_t rva;            // of the first anchor byte
    uint8_t anchorLen; uint8_t anchor[kMaxSiteBytes];
    uint8_t len;       uint8_t stock[kMaxSiteBytes];
    uint8_t patch[kMaxSiteBytes];   // kind == kPatch: len bytes
    const char* configKey;   // nullptr = always on
    // W7 value rows (appended with defaults: a table without value rows omits them). The bytes come from a numeric config key, resolved
    // into an effective copy of the table before the plan (patch_value.h ResolveSites); MakePatchPlan never reads these fields.
    const char* valueKey = nullptr;     // nullptr = fixed patch bytes
    uint8_t valueType = kValueNone;     // SiteValueType: little-endian float32 or int32, len == 4
    uint8_t valueFloorStock = 0;        // 1 = never write below the stock value
    double valueScale = 1.0;            // written = configured x scale
};

enum class SiteState : uint8_t { Stock, Done, BadEntry, Unmapped, NotCode, Relocated, BadAnchor, BadStock, Overlap };
inline const char* SiteStateName(SiteState s) {
    switch (s) {
    case SiteState::Stock: return "stock"; case SiteState::Done: return "already patched"; case SiteState::BadEntry: return "BAD TABLE ENTRY";
    case SiteState::Unmapped: return "UNMAPPED"; case SiteState::NotCode: return "NOT IN CODE"; case SiteState::Relocated: return "RELOCATED VALUE";
    case SiteState::BadAnchor: return "ANCHOR MISMATCH"; case SiteState::BadStock: return "STOCK MISMATCH"; default: return "OVERLAPS ANOTHER SITE";
    }
}
inline bool SiteStateOk(SiteState s) { return s == SiteState::Stock || s == SiteState::Done; }

struct SiteCheck {
    SiteState state = SiteState::Unmapped;
    uint32_t valueRva = 0;   // rva + anchorLen: where the patch is written / the hook goes
    bool enabled = false, write = false;
    int firstDiff = -1;      // byte index of the first mismatch (anchor or stock)
    uint8_t cur[kMaxSiteBytes] = {};
};

enum class PlanVerdict : uint8_t { Apply, NothingToDo, Refuse };
inline const char* PlanVerdictName(PlanVerdict v) { return v == PlanVerdict::Apply ? "apply" : v == PlanVerdict::NothingToDo ? "nothing to do" : "REFUSED"; }

struct PatchPlan {
    PlanVerdict verdict = PlanVerdict::Refuse;
    std::string reason;               // first bad site, or "" when all are good
    std::vector<SiteCheck> sites;
    int nOk = 0, nBad = 0, nWrite = 0, nDone = 0, nHooks = 0, bytesToChange = 0;
};

// enabled[i]: site i's config key is on (nullptr = all on). delta = actual base - preferred base (0 for a file view).
inline PatchPlan MakePatchPlan(const ImageView& v, uint32_t delta, const SiteDef* s, size_t n, const bool* enabled) {
    PatchPlan pl; char b[240];
    pl.sites.resize(n);
    if (!v.pe || !v.pe->ok) { pl.reason = "no PE headers"; pl.nBad = (int)n; if (n == 0) pl.verdict = PlanVerdict::NothingToDo; return pl; }
    for (size_t i = 0; i < n; ++i) {
        const SiteDef& d = s[i]; SiteCheck& c = pl.sites[i];
        c.enabled = enabled ? enabled[i] : true;
        c.valueRva = d.rva + d.anchorLen;
        const uint32_t total = (uint32_t)d.anchorLen + d.len;
        if (!d.id || d.anchorLen == 0 || d.len == 0 || total > 2 * kMaxSiteBytes || d.anchorLen > kMaxSiteBytes || d.len > kMaxSiteBytes ||
            (d.kind != kPatch && d.kind != kHook) || d.rva + (uint64_t)total > 0xFFFFFFFFull) c.state = SiteState::BadEntry;
        else {
            for (size_t j = 0; j < i && c.state != SiteState::Overlap; ++j) {
                const uint32_t lo = s[j].rva, hi = s[j].rva + s[j].anchorLen + s[j].len;
                if (d.rva < hi && lo < d.rva + total) c.state = SiteState::Overlap;
            }
            if (c.state != SiteState::Overlap) {
                const int sec = SectionOfRva(*v.pe, d.rva, total);
                std::vector<uint32_t> rel;
                uint8_t a[kMaxSiteBytes], cur[kMaxSiteBytes];
                if (sec < 0) c.state = SiteState::Unmapped;
                else if (d.kind == kHook && !(v.pe->sections[sec].characteristics & kScnExecute)) c.state = SiteState::NotCode;
                else if (d.kind == kPatch && (RelocsInRange(v, c.valueRva, c.valueRva + d.len, rel), !rel.empty())) c.state = SiteState::Relocated;
                else if (!ReadUnrelocated(v, d.rva, d.anchorLen, delta, a) || !ReadUnrelocated(v, c.valueRva, d.len, delta, cur)) c.state = SiteState::Unmapped;
                else {
                    memcpy(c.cur, cur, d.len);
                    for (unsigned k = 0; k < d.anchorLen; ++k) if (a[k] != d.anchor[k]) { c.firstDiff = (int)k; break; }
                    if (c.firstDiff >= 0) c.state = SiteState::BadAnchor;
                    else if (memcmp(cur, d.stock, d.len) == 0) c.state = SiteState::Stock;
                    else if (d.kind == kPatch && memcmp(cur, d.patch, d.len) == 0) c.state = SiteState::Done;
                    else {
                        c.state = SiteState::BadStock;
                        for (unsigned k = 0; k < d.len; ++k) if (cur[k] != d.stock[k]) { c.firstDiff = (int)k; break; }
                    }
                }
            }
        }
        if (!SiteStateOk(c.state)) {
            ++pl.nBad;
            if (pl.reason.empty()) {
                snprintf(b, sizeof b, "site '%s' (RVA 0x%x): %s%s", d.id ? d.id : "?", (unsigned)d.rva, SiteStateName(c.state),
                         c.firstDiff >= 0 ? (std::string(" at byte +") + std::to_string(c.firstDiff)).c_str() : "");
                pl.reason = b;
            }
            continue;
        }
        ++pl.nOk;
        if (d.kind == kHook) { ++pl.nHooks; continue; }   // hooks are installed by their feature, through the plan's checked address
        if (c.state == SiteState::Done) { ++pl.nDone; continue; }
        if (c.enabled) { c.write = true; ++pl.nWrite; for (unsigned k = 0; k < d.len; ++k) pl.bytesToChange += c.cur[k] != d.patch[k]; }
    }
    if (pl.nBad) {
        for (auto& c : pl.sites) c.write = false;
        pl.nWrite = 0; pl.bytesToChange = 0; pl.verdict = PlanVerdict::Refuse;
        return pl;
    }
    pl.verdict = pl.nWrite ? PlanVerdict::Apply : PlanVerdict::NothingToDo;
    return pl;
}

// Host/test helper: performs the plan's writes on a MAPPED-layout buffer. The driver writes the same bytes under VirtualProtect.
inline int ApplyPlanToBuffer(uint8_t* image, const PatchPlan& pl, const SiteDef* s) {
    if (pl.verdict != PlanVerdict::Apply) return 0;
    int changed = 0;
    for (size_t i = 0; i < pl.sites.size(); ++i) {
        if (!pl.sites[i].write) continue;
        for (unsigned k = 0; k < s[i].len; ++k)
            if (image[pl.sites[i].valueRva + k] != s[i].patch[k]) { image[pl.sites[i].valueRva + k] = s[i].patch[k]; ++changed; }
    }
    return changed;
}

// Memory protection behind an interface so the write step is host-testable (patch_driver.cpp: VirtualProtect, VirtualQuery,
// GetSystemInfo). The host tests' mock with VirtualProtect's page semantics is tk::PageMem (proxy/tests/testkit.h).
struct MemOps {
    virtual bool Unprotect(uint8_t* p, size_t n, uint32_t& old) = 0;   // make writable, return the old protection (of the FIRST page)
    virtual bool Reprotect(uint8_t* p, size_t n, uint32_t old) = 0;
    virtual void Flush(uint8_t*, size_t) {}
    virtual uint32_t PageSize() const { return 0x1000; }
    virtual bool Query(uint8_t* page, uint32_t& prot) { (void)page; (void)prot; return false; }   // a page's protection now; false = unknown
    virtual ~MemOps() {}
};
struct PageProt {
    uint32_t rva = 0;        // the page's RVA
    uint32_t recorded = 0;   // its protection before the write (what Unprotect reported for this page alone)
    uint32_t after = 0;      // what Query read back after the restore
    bool known = false;      // Query answered
};
struct WriteResult {
    bool ok = false;           // every planned site written (or nothing to write)
    int written = 0;           // sites written: 0 or pl.nWrite, never in between
    int failedSite = -1;       // the first written site, in plan order, with a byte on the page whose Unprotect failed
    int64_t failedPage = -1;   // that page's RVA (-1: none)
    int reprotectFailures = 0; // pages whose restore failed
    std::vector<PageProt> pages;   // every page made writable, ascending, with its own recorded protection and the readback
};
// The pages (RVAs, sorted, unique) that a written site's value bytes touch: from the page of valueRva to the page of valueRva + len - 1.
inline std::vector<uint32_t> WritePages(const PatchPlan& pl, const SiteDef* s, uint32_t pageSize) {
    std::vector<uint32_t> v;
    if (!pageSize) return v;
    for (size_t i = 0; i < pl.sites.size(); ++i) {
        if (!pl.sites[i].write || !s[i].len) continue;
        const uint32_t a = pl.sites[i].valueRva, last = (a + s[i].len - 1) / pageSize * pageSize;
        for (uint32_t p = a / pageSize * pageSize; p <= last; p += pageSize) v.push_back(p);
    }
    std::sort(v.begin(), v.end());
    v.erase(std::unique(v.begin(), v.end()), v.end());
    return v;
}
// A page read back after the restore holds what was recorded. An image page that was written is private from then on, so a
// copy-on-write protection reads back as its written form: PAGE_WRITECOPY 0x08 as PAGE_READWRITE 0x04, PAGE_EXECUTE_WRITECOPY 0x80
// as PAGE_EXECUTE_READWRITE 0x40. Anything else (another value, a guard or cache bit) is a page left changed.
inline bool ProtectionRestored(uint32_t recorded, uint32_t after) {
    return recorded == after || (recorded == 0x08 && after == 0x04) || (recorded == 0x80 && after == 0x40);
}
// All-or-nothing at write time (J1 review finding 4), page by page (W33, C3): every page a written site touches is made writable
// FIRST, once, in ascending order, and keeps its OWN old protection (VirtualProtect reports the first page of a range only, so a
// per-site record restored a page shared by two sites, or a site's second page, as RWX). One failure restores the pages already
// changed, each with its own value, and writes nothing. Then all bytes are written, every page restored once with its recorded value,
// each written range flushed, and every page read back (Query). A failed restore leaves a page writable (counted, logged), never a
// site half-written; the readback never refuses or undoes anything (the bytes are written). A page size that is not a power of two
// refuses before any call.
inline WriteResult WritePlanAtomic(uint8_t* base, const PatchPlan& pl, const SiteDef* s, MemOps& ops) {
    WriteResult r;
    if (pl.verdict != PlanVerdict::Apply) { r.ok = pl.verdict == PlanVerdict::NothingToDo; return r; }
    const uint32_t ps = ops.PageSize();
    if (!ps || (ps & (ps - 1))) return r;
    const std::vector<uint32_t> pages = WritePages(pl, s, ps);
    for (uint32_t pg : pages) {
        PageProt p; p.rva = pg;
        if (!ops.Unprotect(base + pg, ps, p.recorded)) {
            for (size_t k = r.pages.size(); k-- > 0;)
                if (!ops.Reprotect(base + r.pages[k].rva, ps, r.pages[k].recorded)) ++r.reprotectFailures;
            r.failedPage = pg;
            for (size_t i = 0; i < pl.sites.size() && r.failedSite < 0; ++i)
                if (pl.sites[i].write && s[i].len && pl.sites[i].valueRva < pg + ps && pl.sites[i].valueRva + s[i].len > pg) r.failedSite = (int)i;
            for (PageProt& q : r.pages) q.known = ops.Query(base + q.rva, q.after);
            return r;
        }
        r.pages.push_back(p);
    }
    int n = 0;
    for (size_t i = 0; i < pl.sites.size(); ++i) if (pl.sites[i].write) { memcpy(base + pl.sites[i].valueRva, s[i].patch, s[i].len); ++n; }
    for (const PageProt& p : r.pages) if (!ops.Reprotect(base + p.rva, ps, p.recorded)) ++r.reprotectFailures;
    for (size_t i = 0; i < pl.sites.size(); ++i) if (pl.sites[i].write) ops.Flush(base + pl.sites[i].valueRva, s[i].len);
    for (PageProt& p : r.pages) p.known = ops.Query(base + p.rva, p.after);
    r.ok = true; r.written = n;
    return r;
}

inline std::string PlanSummary(const PatchPlan& pl, size_t n) {
    char b[300];
    snprintf(b, sizeof b, "patch_engine: %s - %u sites: %d ok, %d bad, %d to write (%d bytes), %d already patched, %d hooks verified%s%s",
             PlanVerdictName(pl.verdict), (unsigned)n, pl.nOk, pl.nBad, pl.nWrite, pl.bytesToChange, pl.nDone, pl.nHooks,
             pl.reason.empty() ? "" : "; first bad: ", pl.reason.c_str());
    return b;
}

} // namespace wsp

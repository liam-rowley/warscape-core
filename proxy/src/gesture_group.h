#pragma once
// gesture_group.h - a grouped selection (W6), platform-free; host-tested by proxy/tests/test_gesture.cpp.
// Ported from empire-remastered rml_mod/src/gesture_group.h: a game's "current selection" may not list the units of a selected group;
// an adapter that can also see the group's cards (or the cards shown as selected) merges them here before it hands the selection to the
// layer. A grouped selection then moves as the same rigid block the same units would ungrouped. Whether a game needs it is the game's
// question (its adapter's); the core only carries the merge.
//   mode (bit mask): 0 = the selection only; bit 0 (1) = + units of a selected group; bit 1 (2) = + units shown as selected; 3 = both.
// Stale-group guard: when the selection lists units and none of them is in a group the extras call selected, the group extras are dropped
// (a plain click after a group selection never drags the old group along).
#include <cstdint>
#include <string>
#include <vector>

namespace wsp {
namespace gest {

enum GroupSrc { kSrcSelected = 0, kSrcGroup = 1, kSrcState = 2 };
constexpr int kGroupModeDefault = 3, kGroupBitGroup = 1, kGroupBitState = 2;
struct GroupEntry { uint32_t unit = 0; int card = 0; int group = 0; int src = kSrcSelected; };
struct GroupStats { unsigned selected = 0, fromGroup = 0, fromState = 0, dropped = 0; bool staleGroups = false; std::string groups; };

inline int ClampGroupMode(int m) { return m < 0 || m > 3 ? kGroupModeDefault : m; }
inline bool GroupUses(int mode, int src) { return src == kSrcSelected || (src == kSrcGroup && (mode & kGroupBitGroup)) || (src == kSrcState && (mode & kGroupBitState)); }

// selected: the game's selection in its order (kept first); extra: group / selected-state units. The merged list has no duplicates.
inline std::vector<GroupEntry> MergeGroups(const std::vector<GroupEntry>& selected, const std::vector<GroupEntry>& extra, int mode, GroupStats* st) {
    mode = ClampGroupMode(mode);
    GroupStats s; std::vector<GroupEntry> out;
    bool groupsOk = true;
    if (!selected.empty()) {
        groupsOk = false;
        for (const GroupEntry& a : selected) for (const GroupEntry& e : extra) if (e.src == kSrcGroup && a.group > 0 && a.group == e.group) groupsOk = true;
    }
    auto has = [&](uint32_t u) { for (const GroupEntry& e : out) if (e.unit == u) return true; return false; };
    for (const GroupEntry& e : selected) { if (!e.unit || has(e.unit)) continue; GroupEntry c = e; c.src = kSrcSelected; out.push_back(c); ++s.selected; }
    for (const GroupEntry& e : extra) {
        if (!e.unit || (e.src != kSrcGroup && e.src != kSrcState)) { ++s.dropped; continue; }
        if (!GroupUses(mode, e.src)) { ++s.dropped; continue; }
        if (e.src == kSrcGroup && !groupsOk) { ++s.dropped; s.staleGroups = true; continue; }
        if (has(e.unit)) continue;
        out.push_back(e);
        if (e.src == kSrcGroup) {
            ++s.fromGroup;
            const std::string g = std::to_string(e.group);
            bool seen = false; size_t p = 0;
            while (p <= s.groups.size()) { size_t q = s.groups.find(',', p); if (q == std::string::npos) q = s.groups.size(); if (s.groups.compare(p, q - p, g) == 0) { seen = true; break; } p = q + 1; }
            if (!seen) s.groups += (s.groups.empty() ? "" : ",") + g;
        } else ++s.fromState;
    }
    if (st) *st = s;
    return out;
}

}  // namespace gest
}  // namespace wsp

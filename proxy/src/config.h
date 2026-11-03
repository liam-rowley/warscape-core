#pragma once
// Config file parsing: pure core (host tests in proxy/tests/test_config.cpp). One INI file next to the exe; `[section]` + `key`
// maps to the config_keys registry id `section.key` (lowercase). The key table (id, type, default) is GENERATED from the registry
// (proxy/tools/gen_tables.py), so the DLL knows exactly the registered keys. Unknown keys, bad values, duplicates and stray lines
// are collected as warnings for the log, never fatal: a bad value falls back to the registry default (the warning names the key's type).
// Numeric keys (W7): an int must fit int32; a float is [+-]digits[.digits][e[+-]digits], checked by hand and converted with
// from_chars, so the C locale never changes the result ("1,5" is refused), and nan, inf and anything beyond float32 are refused.
// A numeric key may carry a range (min/max, from the registry): a file value outside it is clamped to the nearer bound, with a warning.
#include <cfloat>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <map>
#include <string>
#include <vector>

namespace wsp {

enum KeyType : uint8_t { kBool = 0, kInt = 1, kStr = 2, kFloat = 3 };
// min/max: numeric keys only, nullptr = no bound. Appended with defaults, so a table that omits them still compiles (and -Wextra is quiet).
struct KeySpec { const char* id; uint8_t type; const char* def; const char* min = nullptr; const char* max = nullptr; };

// The number in a valid numeric text (Normalise checked it); false = not a number.
inline bool NumberOf(const std::string& s, double& v) {
    const char* b = s.c_str(); const char* e = b + s.size();
    if (b != e && *b == '+') ++b;
    if (b == e) return false;
    const auto r = std::from_chars(b, e, v);
    return r.ec == std::errc() && r.ptr == e;
}

struct Config {
    std::map<std::string, std::string> values;   // every registered key: the file's valid value or the default
    std::map<std::string, bool> fromFile;        // true = the file set it
    std::vector<std::string> warnings;           // one line each, for the log
    std::vector<std::string> unknown;            // ids in the file that the registry does not know
    bool fileRead = false;

    const std::string& Str(const std::string& id) const { static const std::string e; auto it = values.find(id); return it == values.end() ? e : it->second; }
    long Int(const std::string& id) const { return strtol(Str(id).c_str(), nullptr, 10); }
    double Float(const std::string& id) const { double v = 0; return NumberOf(Str(id), v) ? v : 0.0; }
    bool Bool(const std::string& id) const { const std::string& s = Str(id); return s == "1" || s == "true"; }
};

inline std::string Trim(const std::string& s) {
    size_t a = 0, b = s.size();
    while (a < b && (s[a] == ' ' || s[a] == '\t' || s[a] == '\r' || s[a] == '\n')) ++a;
    while (b > a && (s[b - 1] == ' ' || s[b - 1] == '\t' || s[b - 1] == '\r' || s[b - 1] == '\n')) --b;
    return s.substr(a, b - a);
}
inline std::string Lower(std::string s) { for (char& c : s) if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a'); return s; }

// Normalises a value to the key's type; false = invalid.
inline bool Normalise(uint8_t type, const std::string& in, std::string& out) {
    if (type == kStr) { out = in; return true; }
    if (type == kBool) {
        const std::string l = Lower(in);
        if (l == "1" || l == "true" || l == "yes" || l == "on") { out = "1"; return true; }
        if (l == "0" || l == "false" || l == "no" || l == "off") { out = "0"; return true; }
        return false;
    }
    if (in.empty()) return false;
    size_t i = (in[0] == '-' || in[0] == '+') ? 1 : 0;
    auto digits = [&](size_t& k) { const size_t s = k; while (k < in.size() && in[k] >= '0' && in[k] <= '9') ++k; return k > s; };
    if (type == kFloat) {   // [+-]digits[.digits][e[+-]digits], by hand: no locale, no hex, no nan/inf words
        if (!digits(i)) return false;
        if (i < in.size() && in[i] == '.') { ++i; if (!digits(i)) return false; }
        if (i < in.size() && (in[i] == 'e' || in[i] == 'E')) { ++i; if (i < in.size() && (in[i] == '+' || in[i] == '-')) ++i; if (!digits(i)) return false; }
        double v = 0;
        if (i != in.size() || !NumberOf(in, v) || !std::isfinite(v) || std::fabs(v) > FLT_MAX) return false;
        out = in[0] == '+' ? in.substr(1) : in;
        return true;
    }
    if (i == in.size() || in.size() > 11) return false;
    for (; i < in.size(); ++i) if (in[i] < '0' || in[i] > '9') return false;
    const long long v = strtoll(in.c_str(), nullptr, 10);
    if (v < -2147483648LL || v > 2147483647LL) return false;   // int32
    out = std::to_string(v);
    return true;
}

inline const char* KeyTypeName(uint8_t type) {
    return type == kBool ? "0/1" : type == kInt ? "integer (int32)" : type == kFloat ? "number" : "string";
}

// A numeric value outside the key's [min, max] becomes the nearer bound; returns the warning ("" = in range or not numeric).
inline std::string ClampToRange(const KeySpec& k, std::string& value) {
    if (k.type != kInt && k.type != kFloat) return "";
    double v = 0, lo = 0, hi = 0;
    if (!NumberOf(value, v)) return "";
    const char* bound = nullptr; const char* what = nullptr;
    if (k.min && NumberOf(k.min, lo) && v < lo) { bound = k.min; what = "below the minimum"; }
    else if (k.max && NumberOf(k.max, hi) && v > hi) { bound = k.max; what = "above the maximum"; }
    if (!bound) return "";
    const std::string w = std::string(k.id) + "=" + value + " is " + what + " " + bound + ", clamped to " + bound;
    value = bound;
    return w;
}

// text = the whole file ("" with fileRead=false when it is missing: every key takes its default, no warning).
inline Config ParseConfig(const std::string& text, bool fileRead, const KeySpec* specs, size_t n) {
    Config c; c.fileRead = fileRead;
    std::map<std::string, const KeySpec*> byId;
    for (size_t i = 0; i < n; ++i) { byId[specs[i].id] = &specs[i]; c.values[specs[i].id] = specs[i].def; c.fromFile[specs[i].id] = false; }
    std::string section; size_t pos = 0; int lineNo = 0;
    std::string t = text;
    if (t.size() >= 3 && (uint8_t)t[0] == 0xEF && (uint8_t)t[1] == 0xBB && (uint8_t)t[2] == 0xBF) t = t.substr(3);   // UTF-8 BOM (Notepad)
    while (pos <= t.size() && !t.empty()) {
        size_t e = t.find('\n', pos); if (e == std::string::npos) e = t.size();
        std::string line = Trim(t.substr(pos, e - pos)); ++lineNo; pos = e + 1;
        if (line.empty() || line[0] == ';' || line[0] == '#') { if (e >= t.size()) break; continue; }
        if (line[0] == '[') {
            const size_t close = line.find(']');
            if (close == std::string::npos) c.warnings.push_back("line " + std::to_string(lineNo) + ": bad section header '" + line + "', ignored");
            else section = Lower(Trim(line.substr(1, close - 1)));
        } else {
            const size_t eq = line.find('=');
            if (eq == std::string::npos) c.warnings.push_back("line " + std::to_string(lineNo) + ": no '=' in '" + line + "', ignored");
            else if (section.empty()) c.warnings.push_back("line " + std::to_string(lineNo) + ": key outside any [section], ignored");
            else {
                const std::string id = section + "." + Lower(Trim(line.substr(0, eq)));
                std::string val = Trim(line.substr(eq + 1));
                const size_t cm = val.find(" ;");   // trailing comment
                if (cm != std::string::npos) val = Trim(val.substr(0, cm));
                auto it = byId.find(id);
                if (it == byId.end()) { c.unknown.push_back(id); c.warnings.push_back("line " + std::to_string(lineNo) + ": unknown key " + id + " (not in the config_keys registry), ignored"); }
                else {
                    std::string norm;
                    if (c.fromFile[id]) c.warnings.push_back("line " + std::to_string(lineNo) + ": " + id + " set again, the later value wins");
                    if (Normalise(it->second->type, val, norm)) {
                        const std::string w = ClampToRange(*it->second, norm);
                        if (!w.empty()) c.warnings.push_back("line " + std::to_string(lineNo) + ": " + w);
                        c.values[id] = norm; c.fromFile[id] = true;
                    }
                    else c.warnings.push_back("line " + std::to_string(lineNo) + ": " + id + "='" + val + "' is not a valid " +
                                              KeyTypeName(it->second->type) + ", using the default " + it->second->def);
                }
            }
        }
        if (e >= t.size()) break;
    }
    return c;
}

} // namespace wsp

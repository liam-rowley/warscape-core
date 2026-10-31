#pragma once
// SHA-1 (FIPS 180-1), pure and dependency-free: the exe-identity guard hashes the exe FILE at start-up from DllMain, where loading
// bcrypt.dll or another crypto DLL under the loader lock is not safe. Host-tested against the FIPS vectors (proxy/tests).
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>

namespace wsp {

class Sha1 {
public:
    Sha1() { Reset(); }
    void Reset() {
        h_[0] = 0x67452301u; h_[1] = 0xEFCDAB89u; h_[2] = 0x98BADCFEu; h_[3] = 0x10325476u; h_[4] = 0xC3D2E1F0u;
        n_ = 0; used_ = 0;
    }
    void Update(const void* data, size_t len) {
        const uint8_t* p = (const uint8_t*)data;
        n_ += len;
        while (len) {
            size_t take = 64 - used_; if (take > len) take = len;
            memcpy(buf_ + used_, p, take); used_ += take; p += take; len -= take;
            if (used_ == 64) { Block(buf_); used_ = 0; }
        }
    }
    // 40 lowercase hex digits. Resets nothing: call once.
    std::string HexDigest() {
        const uint64_t bits = n_ * 8;
        const uint8_t pad = 0x80, zero = 0;
        Update(&pad, 1);
        while (used_ != 56) Update(&zero, 1);
        uint8_t len[8]; for (int i = 0; i < 8; ++i) len[i] = (uint8_t)(bits >> (56 - 8 * i));
        Update(len, 8);
        static const char* hx = "0123456789abcdef";
        std::string s;
        for (uint32_t w : h_) for (int i = 3; i >= 0; --i) { const uint8_t b = (uint8_t)(w >> (8 * i)); s += hx[b >> 4]; s += hx[b & 15]; }
        return s;
    }
private:
    static uint32_t Rol(uint32_t x, int n) { return (x << n) | (x >> (32 - n)); }
    void Block(const uint8_t* b) {
        uint32_t w[80];
        for (int i = 0; i < 16; ++i) w[i] = (uint32_t)b[4 * i] << 24 | (uint32_t)b[4 * i + 1] << 16 | (uint32_t)b[4 * i + 2] << 8 | b[4 * i + 3];
        for (int i = 16; i < 80; ++i) w[i] = Rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
        uint32_t a = h_[0], bb = h_[1], c = h_[2], d = h_[3], e = h_[4];
        for (int i = 0; i < 80; ++i) {
            uint32_t f, k;
            if (i < 20) { f = (bb & c) | (~bb & d); k = 0x5A827999u; }
            else if (i < 40) { f = bb ^ c ^ d; k = 0x6ED9EBA1u; }
            else if (i < 60) { f = (bb & c) | (bb & d) | (c & d); k = 0x8F1BBCDCu; }
            else { f = bb ^ c ^ d; k = 0xCA62C1D6u; }
            const uint32_t t = Rol(a, 5) + f + e + k + w[i];
            e = d; d = c; c = Rol(bb, 30); bb = a; a = t;
        }
        h_[0] += a; h_[1] += bb; h_[2] += c; h_[3] += d; h_[4] += e;
    }
    uint32_t h_[5]; uint64_t n_; uint8_t buf_[64]; size_t used_;
};

} // namespace wsp

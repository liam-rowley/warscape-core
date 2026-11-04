#pragma once
// SHA-256 (FIPS 180-4), pure and dependency-free, the shape of sha1.h: the DLL hashes its own FILE at start-up from DllMain (the
// self_hash line, docs/PROXY_BUILD.md), where loading bcrypt.dll or another crypto DLL under the loader lock is not safe.
// Host-tested against the FIPS 180-4 vectors and every split point of a 130-byte message (proxy/tests/test_sha256.cpp).
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>

namespace wsp {

class Sha256 {
public:
    Sha256() { Reset(); }
    void Reset() {
        static const uint32_t h0[8] = { 0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au, 0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u };
        memcpy(h_, h0, sizeof h_);
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
    // 64 lowercase hex digits. Resets nothing: call once.
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
    static uint32_t Ror(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }
    void Block(const uint8_t* b) {
        static const uint32_t k[64] = {
            0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u,
            0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u,
            0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
            0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u,
            0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
            0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
            0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
            0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u, 0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u };
        uint32_t w[64];
        for (int i = 0; i < 16; ++i) w[i] = (uint32_t)b[4 * i] << 24 | (uint32_t)b[4 * i + 1] << 16 | (uint32_t)b[4 * i + 2] << 8 | b[4 * i + 3];
        for (int i = 16; i < 64; ++i) {
            const uint32_t s0 = Ror(w[i - 15], 7) ^ Ror(w[i - 15], 18) ^ (w[i - 15] >> 3);
            const uint32_t s1 = Ror(w[i - 2], 17) ^ Ror(w[i - 2], 19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16] + s0 + w[i - 7] + s1;
        }
        uint32_t a = h_[0], bb = h_[1], c = h_[2], d = h_[3], e = h_[4], f = h_[5], g = h_[6], h = h_[7];
        for (int i = 0; i < 64; ++i) {
            const uint32_t S1 = Ror(e, 6) ^ Ror(e, 11) ^ Ror(e, 25);
            const uint32_t ch = (e & f) ^ (~e & g);
            const uint32_t t1 = h + S1 + ch + k[i] + w[i];
            const uint32_t S0 = Ror(a, 2) ^ Ror(a, 13) ^ Ror(a, 22);
            const uint32_t mj = (a & bb) ^ (a & c) ^ (bb & c);
            const uint32_t t2 = S0 + mj;
            h = g; g = f; f = e; e = d + t1; d = c; c = bb; bb = a; a = t1 + t2;
        }
        h_[0] += a; h_[1] += bb; h_[2] += c; h_[3] += d; h_[4] += e; h_[5] += f; h_[6] += g; h_[7] += h;
    }
    uint32_t h_[8]; uint64_t n_; uint8_t buf_[64]; size_t used_;
};

} // namespace wsp

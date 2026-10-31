// Host test: SHA-1 against the FIPS 180-1 vectors and chunked updates (the guard hashes the exe in 1 MiB reads).
#include "testkit.h"
#include "sha1.h"

static std::string H(const std::string& s) { wsp::Sha1 h; h.Update(s.data(), s.size()); return h.HexDigest(); }

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    CHECK_EQ(H(""), std::string("da39a3ee5e6b4b0d3255bfef95601890afd80709"));
    CHECK_EQ(H("abc"), std::string("a9993e364706816aba3e25717850c26c9cd0d89d"));
    CHECK_EQ(H("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"), std::string("84983e441c3bd26ebaae4aa1f95129e5e54670f1"));
    { wsp::Sha1 h; std::string a(1000, 'a'); for (int i = 0; i < 1000; ++i) h.Update(a.data(), a.size()); CHECK_EQ(h.HexDigest(), std::string("34aa973cd4c4daa4f61eeb2bdbad27316534016f")); }
    // every split point of a 130-byte message gives the same digest as one update
    std::string m; for (int i = 0; i < 130; ++i) m += (char)(i * 7);
    const std::string whole = H(m);
    for (size_t k = 0; k <= m.size(); ++k) { wsp::Sha1 h; h.Update(m.data(), k); h.Update(m.data() + k, m.size() - k); CHECK_EQ(h.HexDigest(), whole); }
    return tk::Done("test_sha1");
}

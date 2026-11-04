// Host test: SHA-256 against the FIPS 180-4 vectors and chunked updates (the DLL hashes its own file in 1 MiB reads, W24).
#include "testkit.h"
#include "sha256.h"

static std::string H(const std::string& s) { wsp::Sha256 h; h.Update(s.data(), s.size()); return h.HexDigest(); }

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    CHECK_EQ(H(""), std::string("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"));
    CHECK_EQ(H("abc"), std::string("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"));
    CHECK_EQ(H("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"), std::string("248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"));
    { wsp::Sha256 h; std::string a(1000, 'a'); for (int i = 0; i < 1000; ++i) h.Update(a.data(), a.size()); CHECK_EQ(h.HexDigest(), std::string("cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0")); }
    // every split point of a 130-byte message gives the same digest as one update
    std::string m; for (int i = 0; i < 130; ++i) m += (char)(i * 7);
    const std::string whole = H(m);
    CHECK_EQ(whole, std::string("e3346da76ca302cbddbd3e4f0ed5f2e3bce1630152e22ffb88bbdf720489895b"));   // Python's hashlib.sha256 of the same bytes
    for (size_t k = 0; k <= m.size(); ++k) { wsp::Sha256 h; h.Update(m.data(), k); h.Update(m.data() + k, m.size() - k); CHECK_EQ(h.HexDigest(), whole); }
    return tk::Done("test_sha256");
}

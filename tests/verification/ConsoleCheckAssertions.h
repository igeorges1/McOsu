// Included AFTER product/standard headers in generated verification copies.
// Keep Windows headers out: their near/far/min/max macros break portable tests.
#include <cassert>
#include <cstdio>
#include <cstdlib>
#ifdef NDEBUG
#error Verification requires enabled assertions
#endif
namespace VerificationCheck {
inline void fail(const char *expression, const char *file, int line) {
    std::fprintf(stderr, "VERIFICATION_ASSERT %s:%d: %s\n", file, line, expression);
    std::fflush(stderr);
    std::_Exit(1);
}
}
#undef assert
#define assert(condition) do { if (!(condition)) VerificationCheck::fail(#condition, __FILE__, __LINE__); } while (false)

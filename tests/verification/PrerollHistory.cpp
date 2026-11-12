// Only API bridging differs between historical and current production helpers.
#include "OsuTimingAudioRecentWindow.h"
#include "ConsoleCheckAssertions.h"

int main()
{
    OsuTimingAudioRecentWindow history;
#if defined(HISTORICAL_API) || defined(FIXED_API)
    history.advance(0, false);
#ifdef HISTORICAL_API
    history.record(-50); // accepted ready pre-roll, before playback begins
#else
    history.recordAcceptedHit(-50);
#endif
    history.advance(10, false);
    const auto waiting = history.getMoments();
    history.advance(10, true);
#ifdef HISTORICAL_API
    history.record(0);
#else
    history.recordAcceptedHit(0);
#endif
    const auto after = history.getMoments();
#else
    // Counted-play time stays zero during all ten countdown seconds.
    history.recordAcceptedHit(0, -50);
    const auto waiting = history.getMoments(0, 5);
    history.recordAcceptedHit(0, 0);
    const auto after = history.getMoments(0, 5);
#endif
    std::printf("preroll-history waiting_count=%zu waiting_mean=%.0f final_count=%zu final_mean=%.0f expected=1,-50,2,-25\n",
                waiting.count, waiting.meanMS, after.count, after.meanMS);
    std::fflush(stdout);
    assert(waiting.count == 1 && waiting.meanMS == -50);
    assert(after.count == 2 && after.meanMS == -25);
    std::puts("COMPLETE preroll-history failures=0");
}

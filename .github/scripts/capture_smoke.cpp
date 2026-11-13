// CI-only synthetic production-helper sequence; no game/adapter/music/input.
#include "OsuTimingAudioCapture.h"
#include "OsuTimingAudioPlayClock.h"
#include "OsuTimingAudioRecentWindow.h"
#include <fstream>
#include <cstdio>
#include "../../tests/verification/ConsoleCheckAssertions.h"

int main(int argc, char **argv)
{
    assert(argc == 3);
    using Capture = OsuTimingAudioCapture;
    OsuTimingAudioState state;
    OsuTimingAudioPlayClock clock;
    OsuTimingAudioRecentWindow history;
    Capture capture;
    capture.sync(true, true);
    clock.advance(0, true);
    capture.add(Capture::CLOCK, {0, 1, 0});
    OsuTimingAudioState::Config config;
    state.configure(config, clock.seconds());
    capture.configure(config, clock.seconds());
    state.setActivities({});
    capture.add(Capture::ACTIVITIES, {0});
    const double errors[] = {-20, 20, 0};
    for (int i = 0; i < 3; ++i)
    {
        const double time = (i + 1) * .1, position = (i + 1) * 100;
        clock.advance(time, true);
        capture.add(Capture::CLOCK, {time, 1, 0});
        state.advance(position, 1);
        capture.add(Capture::ADVANCE, {position, 1});
        const auto result = state.sampleMap(errors[i], {45, 1}, false, position, 0, clock.seconds());
        assert(result.accepted);
        capture.hit(errors[i], {45, 1}, false, position, 0, state, result);
        history.recordAcceptedHit(clock.seconds(), errors[i]);
        capture.add(Capture::OUTPUT, {OsuTimingAudioEvaluation::MUTED, 0, 1, 0, 0});
    }
    const auto moments = history.getMoments(clock.seconds(), 5);
    capture.add(Capture::MARK, {.3, clock.seconds(), 5, (long double)moments.count,
                              moments.meanMS, moments.varianceMS2, 0});
    std::ofstream out(argv[2], std::ios::binary);
    assert(capture.complete() && capture.write(out, argv[1], "00000000000000000000000000000001",
           "CI synthetic helpers; no adapter, beatmap file, music, pixels or audio"));
    out.close();
    assert(out.good());
    std::puts("COMPLETE synthetic capture producer failures=0 accepted_hits=3 marks=1");
}

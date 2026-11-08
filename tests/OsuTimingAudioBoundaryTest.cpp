#include "../src/App/Osu/OsuTimingAudioState.h"
#include <cstdio>
#include <cstdlib>
#include <initializer_list>

#define CHECK(condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); std::exit(1); } } while (false)
typedef OsuTimingAudioState State;
typedef OsuTimingAudioReference Ref;

int main()
{
	// Exact independent-review cases, including negative mirrors, non-unit rates,
	// default adaptive floor and the adjacent representable hit outside each edge.
	for (State::BandMode mode : {State::RELATIVE_300, State::ADAPTIVE_SPREAD})
		for (double rate : {.75, 1.0, 1.5, 2.3})
			for (double sign : {-1.0, 1.0})
				for (bool outside : {false, true})
				{
					State state; State::Config config; config.bandMode = mode; state.configure(config);
					const double w = mode == State::RELATIVE_300 ? 68 : 56;
					const auto ref = Ref::calculate((long)(sign * w), rate,
						sign * std::strtold(mode == State::RELATIVE_300 ? "0.8" : "0.9", NULL),
						{w, mode == State::RELATIVE_300 ? 124.0 : 108.0, mode == State::RELATIVE_300 ? 180.0 : 160.0});
					state.sample(0, w, false); state.sample(0, w, false);
					const double hit = outside ? std::nextafter(sign * w, sign * 1000) : sign * w;
					const auto result = state.sampleMap(hit, {w, rate}, false, 0, ref.preciseTargetMapMS);
					CHECK(result.cue == (outside ? (sign < 0 ? State::EARLY : State::LATE) : State::SILENT));
				}

	unsigned cases = 0;
	for (int od = 0; od <= 10; ++od)
		for (double rate : {.75, 1.0, 1.5, 2.3})
			for (int coordinate = -30; coordinate <= 30; ++coordinate)
				for (int fraction : {10, 20, 25, 30, 40, 50, 70, 100, 110, 150, 210})
					for (int side : {-1, 1})
					{
						const int w = 80 - 6 * od, w100 = 140 - 8 * od, w50 = 200 - 10 * od, magnitude = std::abs(coordinate);
						const int target10 = (coordinate < 0 ? -1 : 1) * (magnitude <= 10 ? magnitude * w
							: magnitude <= 20 ? 10 * w + (magnitude - 10) * (w100 - w) : 10 * w100 + (magnitude - 20) * (w50 - w100));
						const int hit100 = target10 * 10 + side * fraction * w;
						if (hit100 % 100 != 0 || std::abs(hit100 / 100) > w50) continue;
						const double hit = hit100 / 100;
						char text[48]; std::sprintf(text, "%s%d.%d", coordinate < 0 ? "-" : "", magnitude / 10, magnitude % 10);
						const auto ref = Ref::calculate((long)hit, rate, std::strtold(text, NULL), {(double)w, (double)w100, (double)w50});
						std::sprintf(text, "%d.%02d", fraction / 100, fraction % 100);
						for (State::BandMode mode : {State::RELATIVE_300, State::ADAPTIVE_SPREAD})
							for (bool outside : {false, true})
							{
								State state; State::Config config; config.bandMode = mode;
								config.relativeFraction = std::strtold(text, NULL);
								config.adaptiveMinFraction = config.adaptiveMaxFraction = config.relativeFraction;
								state.configure(config); state.sample(0, w, false); state.sample(0, w, false);
								const double input = outside ? std::nextafter(hit, side * 1000.0) : hit;
									const auto result = state.sampleMap(input, {(double)w, rate}, false, 0, ref.preciseTargetMapMS);
								if (result.cue != (outside ? (side < 0 ? State::EARLY : State::LATE) : State::SILENT))
									std::fprintf(stderr, "OD%d rate%.17g target%d/10 fraction%d/100 side%d outside%d hit%.17g targetMap%.17g width%.17g cue%d\n", od, rate, coordinate, fraction, side, outside, input, ref.targetMapMS, result.halfWidthMS, (int)result.cue);
								CHECK(result.cue == (outside ? (side < 0 ? State::EARLY : State::LATE) : State::SILENT));
								++cases;
							}
					}
	// Exactly on a decimal target at zero width, including targets whose map
	// interpolation used to retain a tiny cancellation residue.
	for (long double coordinate : {.3L, -0.3L, 2.1L, -2.1L})
	{
		State state; State::Config config; config.deadZoneMS = 0; state.configure(config);
		const long hit = std::lround(coordinate * 50);
		const auto ref = Ref::calculate(hit, 1.5, coordinate, {50, 100, 150});
		CHECK(state.sampleMap(hit, {50, 1.5}, false, 0, ref.preciseTargetMapMS).cue == State::SILENT);
	}
	for (State::BandMode mode : {State::RELATIVE_300, State::ADAPTIVE_SPREAD})
		for (double rate : {.75, 1.0, 1.5, 2.3})
			for (double hit : {-1.0, 0.0, 20.0, 21.0})
			{
				State state; State::Config config; config.bandMode = mode;
				config.adaptiveMinFraction = config.adaptiveMaxFraction = .2L;
				state.configure(config); state.sampleMap(10, {50, rate}, true, 0, 0); state.sampleMap(10, {50, rate}, true, 0, 0);
				CHECK(state.sampleMap(hit, {50, rate}, true, 0, 0).cue == (hit < 0 ? State::EARLY : hit > 20 ? State::LATE : State::SILENT));
			}
	std::printf("PASS: %u mixed fractional target/width/rate endpoint and outward-neighbor cases; review defaults and zero-width targets\n", cases);
}

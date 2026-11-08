#include "../src/App/Osu/OsuTimingAudioState.h"
#include "../src/App/Osu/OsuTimingAudioReference.h"
#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#include <limits>

#define CHECK(condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); std::exit(1); } } while (false)
typedef OsuTimingAudioState State;
static void near(double value, double expected)
{
	if (std::abs(value - expected) >= 0.000001) std::fprintf(stderr, "actual %.12f expected %.12f\n", value, expected);
	CHECK(std::abs(value - expected) < 0.000001);
}
static void spreadSeed(State &s, double amplitude)
{
	for (int i = 0; i < 8; ++i) { s.advance(i * 100, 1); s.sample(i % 2 ? amplitude : -amplitude, 50, true); }
}

int main()
{
	State s; State::Config c; c.bandMode = State::ADAPTIVE_SPREAD; s.configure(c);
	auto r = s.sample(40, 50, false);
	CHECK(r.fixedFallback); near(r.halfWidthMS, 10); CHECK(r.cue == State::LATE); near(s.getVarianceMS2(), 0);
	r = s.sample(40, 50, false); CHECK(r.fixedFallback); near(r.halfWidthMS, 10);
	r = s.sample(6, 50, false); // Updated spread would silence its own hit.
	CHECK(!r.fixedFallback && r.cue == State::LATE); near(r.varianceMS2, 0); near(r.halfWidthMS, 5);
	near(s.getBaselineMS(), 86.0 / 3); near(s.getVarianceMS2(), 2312.0 / 9);

	// Population variance, running startup and both EMA weighting choices.
	for (bool fixed : {false, true})
	{
		c.fixedHits = fixed; c.halfLifeHits = 1; s.configure(c); s.reset();
		for (int i = 0; i < 8; ++i) { s.advance(i * 100, 1); s.sample(i * 20, 200, true); }
		near(s.getBaselineMS(), 70); near(s.getVarianceMS2(), 2100);
		if (!fixed) s.advance(5700, 1);
		s.sample(110, 200, true); near(s.getBaselineMS(), 90); near(s.getVarianceMS2(), 1450);
	}
	c.fixedHits = true; c.halfLifeHits = 16; s.configure(c); s.reset(); spreadSeed(s, 0);
	for (int i = 0; i < 16; ++i) s.sample(40, 50, true);
	near(s.getBaselineMS(), 20); near(s.getVarianceMS2(), 400);
	c.fixedHits = false; s.configure(c); s.reset(); spreadSeed(s, 10);
	const double mean = s.getBaselineMS(), variance = s.getVarianceMS2();
	s.sample(80, 50, true); near(s.getBaselineMS(), mean); near(s.getVarianceMS2(), variance); CHECK(s.getSamples() == 9);

	State translated, centered;
	for (int i = 0; i < 8; ++i)
	{
		translated.sample(i % 2 ? 42 : 38, 50, true);
		centered.sample(i % 2 ? 2 : -2, 50, true);
	}
	near(translated.getBaselineMS(), 40); near(translated.getVarianceMS2(), 4); near(centered.getVarianceMS2(), 4);
	// Relative widths, current window changes, adaptive floor/cap and literal fallback.
	c.bandMode = State::RELATIVE_300; s.configure(c); s.reset();
	near(s.sample(0, 50, false).halfWidthMS, 10); near(s.sample(0, 20, false).halfWidthMS, 4);
	near(s.sample(0, 0, false).halfWidthMS, 0);
	for (double amplitude : {2.0, 20.0, 80.0})
	{
		c.bandMode = State::ADAPTIVE_SPREAD; s.configure(c); s.reset(); spreadSeed(s, amplitude);
		r = s.sample(0, 50, false); near(r.halfWidthMS, amplitude < 5 ? 5 : amplitude > 50 ? 50 : amplitude);
	}
	c.deadZoneMS = 7; s.configure(c); s.reset();
	r = s.sample(0, 2, false); CHECK(r.fixedFallback); near(r.halfWidthMS, 7);
	r = s.sample(0, 2, false); CHECK(r.fixedFallback); near(r.halfWidthMS, 7);
	r = s.sample(0, 2, false); CHECK(!r.fixedFallback); near(r.halfWidthMS, .2);
	r = s.sample(0, 0, false); CHECK(!r.fixedFallback); near(r.halfWidthMS, 0);

	// Width/target/reference switches keep both moments warm and identical.
	State control; c.deadZoneMS = 10; c.require300 = false;
	s.configure(c); control.configure(c); s.reset(); control.reset();
	for (int i = 0; i < 40; ++i)
	{
		const double error = (i % 5 - 2) * 20;
		c.bandMode = i < 10 ? State::FIXED_MS : i < 20 ? State::RELATIVE_300 : State::ADAPTIVE_SPREAD;
		s.configure(c); s.advance(i * 150, 1); control.advance(i * 150, 1);
		s.sample(error, 50, i % 2 != 0, i * 150, error - 25);
		control.sample(error, 50, true);
		near(s.getBaselineMS(), control.getBaselineMS()); near(s.getVarianceMS2(), control.getVarianceMS2());
		CHECK(s.getSamples() == control.getSamples()); near(s.getActiveMS(), control.getActiveMS());
	}
	// Invalid shifted reference mutes only that cue; original errors still learn.
	s.reset(); r = s.sample(30, 50, false, 0, std::numeric_limits<double>::quiet_NaN());
	CHECK(r.cue == State::SILENT && s.getSamples() == 1); near(s.getBaselineMS(), 30);
	r = s.sample(50, 50, true, 0, std::numeric_limits<double>::quiet_NaN()); CHECK(r.cue == State::LATE);
	c.require300 = true; s.configure(c); s.reset();
	CHECK(s.sample(80, 50, false, 0, -20).cue == State::SILENT);
	CHECK(s.sample(-80, 50, false, 0, -180).cue == State::SILENT);
	CHECK(s.sample(30, 50, false, 0, -70).cue == State::EARLY); // Gate is at original zero.
	CHECK(s.getSamples() == 3); near(s.getBaselineMS(), 10);
	c.require300 = false; c.silentStartup = true; s.configure(c); s.reset();
	for (int i = 0; i < 8; ++i) CHECK(s.sample(i * 20, 200, true).cue == State::SILENT);
	near(s.getVarianceMS2(), 2100); CHECK(!s.sample(0, 200, true).fixedFallback);
	c.silentStartup = false; c.bandMode = State::FIXED_MS; s.configure(c);
	for (double boundary : {-10.0, 10.0})
	{
		CHECK(s.sample(0, 50, false, 0, boundary).cue == State::SILENT);
		const double outside = std::nextafter(boundary, boundary < 0 ? -100.0 : 100.0);
		CHECK(s.sample(0, 50, false, 0, outside).cue == (boundary < 0 ? State::EARLY : State::LATE));
	}
	const auto shifted = OsuTimingAudioReference::calculate(35, 1.5, 1, {50, 100, 150});
	CHECK(s.sample(35 / 1.5, 50 / 1.5, false, 0, shifted.deviationMS).cue == State::SILENT);
	for (long error : {139L, 140L, 150L})
	{
		const auto edge = OsuTimingAudioReference::calculate(error, 1, 3, {50, 100, 150});
		CHECK(s.sample(error, 50, false, 0, edge.deviationMS).cue == (error < 140 ? State::EARLY : State::SILENT));
	}
	// Each method includes its boundary and cues immediately outside it.
	for (State::BandMode mode : {State::FIXED_MS, State::RELATIVE_300, State::ADAPTIVE_SPREAD})
		for (double sign : {-1.0, 1.0})
			for (bool outside : {false, true})
			{
				State boundaryState; State::Config boundaryConfig; boundaryConfig.bandMode = mode;
				boundaryState.configure(boundaryConfig); spreadSeed(boundaryState, 10);
				const double deviation = outside ? std::nextafter(sign * 10, sign * 100) : sign * 10;
				const auto boundary = boundaryState.sample(0, 50, false, 0, deviation);
				near(boundary.halfWidthMS, 10);
				CHECK(boundary.cue == (outside ? (sign < 0 ? State::EARLY : State::LATE) : State::SILENT));
			}
	// Decimal fractions at runtime must include their nominal stored-double edge
	// on i686 x87 as well as on compilers that round each product immediately.
	State decimalState; State::Config decimalConfig;
	const volatile double decimalFraction = 0.3;
	decimalConfig.bandMode = State::RELATIVE_300; decimalConfig.relativeFraction = decimalFraction;
	decimalState.configure(decimalConfig);
	const auto decimalTarget = OsuTimingAudioReference::calculate(-40, 1, -1.1L, {50, 100, 150});
	CHECK(decimalTarget.deviationMS == 15);
	CHECK(decimalState.sample(-40, 50, false, 0, decimalTarget.deviationMS).cue == State::SILENT);
	CHECK(decimalState.sample(0, 50, false, 0, -15).cue == State::SILENT);
	decimalConfig.bandMode = State::FIXED_MS; decimalConfig.deadZoneMS = 0;
	decimalState.configure(decimalConfig);
	const volatile long double zeroBandTarget = 2.1L;
	const auto exactTarget = OsuTimingAudioReference::calculate(105, 1, zeroBandTarget, {50, 100, 150});
	CHECK(decimalState.sample(105, 50, false, 0, exactTarget.deviationMS).cue == State::SILENT);
	// Reviewer repro: multiply decimal fractions in map units before converting
	// rate. Relative and BOTH adaptive bounds include the same converted edge.
	for (State::BandMode mode : {State::RELATIVE_300, State::ADAPTIVE_SPREAD})
		for (double speed : {.75, 1.5, 2.3})
			for (double sign : {-1.0, 1.0})
				for (long target : {0L, 1L})
				{
					State edgeState; State::Config edgeConfig;
					const volatile long double fraction = 0.7L;
					edgeConfig.bandMode = mode; edgeConfig.relativeFraction = fraction;
					edgeConfig.adaptiveMinFraction = edgeConfig.adaptiveMaxFraction = fraction;
					edgeState.configure(edgeConfig); edgeState.sample(0, 20, false); edgeState.sample(0, 20, false);
					const long delta = (long)(sign * (target * 20 + 14));
					const auto reference = OsuTimingAudioReference::calculate(delta, speed, sign * target, {20, 60, 100});
					const State::Window window = {20, speed};
					const auto edge = edgeState.sample(delta / speed, window, false, 0, reference.deviationMS);
					CHECK(edge.cue == State::SILENT); near(edge.halfWidthMS, 14 / speed);
					const double outside = std::nextafter(sign * edge.halfWidthMS, sign * 100);
					CHECK(edgeState.sample(0, window, false, 0, outside).cue == (sign < 0 ? State::EARLY : State::LATE));
				}
	State invalidWindow;
	for (State::BandMode mode : {State::RELATIVE_300, State::ADAPTIVE_SPREAD})
		for (double sign : {-1.0, 1.0})
		{
			State zeroTargetState; State::Config zeroTargetConfig;
			zeroTargetConfig.bandMode = mode; zeroTargetConfig.relativeFraction = 0.1L;
			zeroTargetConfig.adaptiveMinFraction = zeroTargetConfig.adaptiveMaxFraction = 0.1L;
			zeroTargetState.configure(zeroTargetConfig); zeroTargetState.sample(0, 80, false); zeroTargetState.sample(0, 80, false);
			const auto zeroTarget = OsuTimingAudioReference::calculate((long)(sign * 8), .75, 0, {80, 140, 200});
			CHECK(zeroTargetState.sample(sign * 8 / .75, State::Window{80, .75}, false, 0, zeroTarget.deviationMS).cue == State::SILENT);
		}
	CHECK(invalidWindow.sample(30, State::Window{20, 0}, false, 0, 30).cue == State::SILENT);
	CHECK(invalidWindow.getSamples() == 0);

	// Qualifying rests must restore matching mean/variance BEFORE the return cue.
	c.bandMode = State::ADAPTIVE_SPREAD; s.configure(c);
	for (bool extraDeparture : {false, true})
	{
		s.setActivities({{0, 0}, {800, 800}, {3800, 3800}}); spreadSeed(s, 10);
		s.advance(900, 1); s.sample(100, 50, false, 800);
		near(s.getBaselineMS(), 2.73450525877145); near(s.getVarianceMS2(), 363.238501608125);
		if (extraDeparture) { s.advance(920, 1); s.sample(120, 50, false, 800); }
		c.bandMode = State::RELATIVE_300; s.configure(c); c.bandMode = State::ADAPTIVE_SPREAD; s.configure(c);
		s.advance(3782, 1); r = s.sample(-18, 50, false, 3800);
		CHECK(r.cue == State::EARLY); near(r.halfWidthMS, 15.3101548411527);
		near(r.baselineMS, 1.37672955066408); near(r.varianceMS2, 234.400841260072);
		near(s.getVarianceMS2(), r.varianceMS2); CHECK(r.precedingSamples == (extraDeparture ? 10u : 9u));
		s.advance(3800, 1); CHECK(s.getSamples() == (extraDeparture ? 11u : 10u));
	}
	s.setActivities({{0, 0}, {800, 800}, {1500, 1500}}); spreadSeed(s, 10);
	s.advance(900, 1); s.sample(100, 50, false, 800); s.advance(1512, 1);
	r = s.sample(-18, 50, false, 1500); near(r.varianceMS2, 363.238501608125); CHECK(r.cue == State::SILENT);
	// Rate changes classify actual elapsed time, for both moments.
	s.setActivities({{0, 0}, {800, 800}, {3800, 3800}}); spreadSeed(s, 10);
	s.advance(900, 1); s.sample(100, 50, false, 800); s.advance(3800, 3);
	r = s.sample(-18, 50, false, 3800); near(r.varianceMS2, 363.238501608125);
	s.setActivities({{0, 0}, {800, 800}, {2800, 2800}}); spreadSeed(s, 10);
	s.advance(900, 1); s.sample(100, 50, false, 800); s.advance(2806, .5);
	r = s.sample(-18, 50, false, 2800); near(r.varianceMS2, 234.400841260072);
	// A pending correction crossing startup -> EMA uses the same sample count.
	s.setActivities({{0, 0}, {800, 800}, {3800, 3800}});
	for (int i = 0; i < 7; ++i) { s.advance(i * 100, 1); s.sample(i * 20, 200, true); }
	s.advance(900, 1); s.sample(100, 200, true, 800);
	s.advance(920, 1); s.sample(120, 200, true, 800);
	s.advance(3782, 1); r = s.sample(0, 200, true, 3800);
	near(r.baselineMS, 65); near(r.varianceMS2, 1575); CHECK(r.precedingSamples == 9);

	// Retain and restart apply to spread, including a pending alternative.
	for (bool restart : {false, true})
	{
		c.restartAfterBreak = restart; s.configure(c);
		s.setActivities({{0, 0}, {800, 800}, {3800, 3800}}); spreadSeed(s, 10);
		s.advance(900, 1); s.sample(100, 50, true, 800);
		s.pause(restart);
		if (restart) { near(s.getVarianceMS2(), 0); CHECK(s.getSamples() == 0); }
		else near(s.getVarianceMS2(), 363.238501608125);
		s.advance(3782, 1); r = s.sample(-18, 50, true, 3800);
		if (restart) { CHECK(r.fixedFallback && r.precedingSamples == 0); near(s.getVarianceMS2(), 0); }
		else { near(r.varianceMS2, 234.400841260072); CHECK(r.precedingSamples == 9); }
	}
	s.reset(); near(s.getVarianceMS2(), 0); CHECK(s.getSamples() == 0);
	spreadSeed(s, 10); s.advance(690, 1); near(s.getVarianceMS2(), 100);
	c.fixedHits = true; s.configure(c); near(s.getVarianceMS2(), 0); CHECK(s.getSamples() == 0);
	// Derived spread overflow falls back without changing raw-input learning.
	s.sample(1e200, 50, false); s.sample(-1e200, 50, false); CHECK(std::isnan(s.getVarianceMS2()));
	r = s.sample(6, 50, false); CHECK(r.fixedFallback && s.getSamples() == 3); near(r.halfWidthMS, 10);
	std::puts("PASS: preceding bands, weighted population spread, switches/gate/startup and whole-gap variance correction");
}

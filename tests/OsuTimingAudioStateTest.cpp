#include "../src/App/Osu/OsuTimingAudioState.h"
#include <cstdlib>
#include <chrono>
#include <cstdio>

#define CHECK(condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); std::exit(1); } } while (false)

typedef OsuTimingAudioState State;
static void near(double actual, double expected)
{
	if (std::abs(actual - expected) >= 0.00001) std::fprintf(stderr, "actual %.12f expected %.12f\n", actual, expected);
	CHECK(std::abs(actual - expected) < 0.00001);
}
static void seed(State &s, double error, double speed = 1.0)
{
	for (int i = 0; i < 8; ++i) { s.advance(i * 100.0 * speed, speed); s.sample(error, 50, true); }
}

int main()
{
	State s;
	CHECK(s.sample(-30, 50, true).cue == State::SILENT);
	auto r = s.sample(-10, 50, true);
	CHECK(r.cue == State::LATE); near(r.baselineMS, -30); near(s.getBaselineMS(), -20);
	// Switching reference changes output, never estimator state.
	r = s.sample(-10, 50, false); CHECK(r.cue == State::SILENT); CHECK(r.precedingSamples == 2);
	r = s.sample(-30, 50, false); CHECK(r.cue == State::EARLY); CHECK(r.precedingSamples == 3);
	s.reset(); CHECK(s.sample(20, 50, false).cue == State::LATE);

	State::Config c; c.require300 = true; s.configure(c); s.reset();
	CHECK(s.sample(80, 50, false).cue == State::SILENT); // no preceding baseline
	CHECK(s.sample(-80, 50, false).cue == State::SILENT); // outside window, still learns
	near(s.getBaselineMS(), 0); CHECK(s.sample(30, 50, false).cue == State::LATE);
	s.reset(); s.sample(50, 50, true);
	CHECK(s.sample(80, 50, true).cue == State::LATE); // inclusive boundary
	s.reset(); s.sample(-50, 50, true);
	CHECK(s.sample(-80, 50, true).cue == State::EARLY);

	c.require300 = false; c.silentStartup = true; s.configure(c); s.reset();
	for (int i = 0; i < 8; ++i) CHECK(s.sample(i * 20, 100, true).cue == State::SILENT);
	near(s.getBaselineMS(), 70); CHECK(s.sample(100, 100, true).cue == State::LATE);
	// Both startup modes calculate the same baseline, despite different muting.
	State audible; for (int i = 0; i < 8; ++i) audible.sample(i * 20, 100, true);
	near(audible.getBaselineMS(), 70);
	c.silentStartup = false; s.configure(c); s.reset();
	seed(s, 0); s.advance(5700, 1); s.sample(40, 50, true); near(s.getBaselineMS(), 20);
	// Same real-play interval under a fixed speed modifier.
	State fast; fast.configure(c);
	for (int i = 0; i < 8; ++i) { fast.advance(i * 150, 1.5); fast.sample(0, 50, true); }
	fast.advance(8550, 1.5); fast.sample(40, 50, true); near(fast.getBaselineMS(), 20);
	c.fixedHits = true; s.configure(c); seed(s, 0);
	for (int i = 0; i < 16; ++i) s.sample(40, 50, true);
	near(s.getBaselineMS(), 20);

	// Full rest exclusion, including the first three seconds before qualification.
	c.fixedHits = false; s.configure(c); s.setActivities({{0, 0}, {700, 700}, {6700, 6700}});
	seed(s, 0); s.advance(3700, 1); near(s.getActiveMS(), 700);
	s.advance(6700, 1); near(s.getActiveMS(), 700);
	s.sample(40, 50, true); near(s.getBaselineMS(), 0);
	// A missed scheduled head interrupts inactivity just like a hit opportunity.
	s.setActivities({{0, 0}, {2000, 2000}, {4000, 4000}});
	s.advance(0, 1); s.sample(20, 50, true); s.advance(4000, 1);
	near(s.getActiveMS(), 4000); CHECK(s.getSamples() == 1);
	// Slider body activity off: long body stays active. Toggle on: head is a point.
	for (int restart = 0; restart < 2; ++restart)
		for (int excludeActivity = 0; excludeActivity < 2; ++excludeActivity)
		{
			c.restartAfterBreak = restart; s.configure(c);
			s.setActivities({{0, excludeActivity ? 0.0 : 6000.0}, {6000, 6000}});
			s.advance(0, 1); s.sample(20, 50, true); s.advance(6000, 1);
			near(s.getActiveMS(), excludeActivity ? 0 : 6000);
			CHECK(s.getSamples() == (unsigned)(restart && excludeActivity ? 0 : 1));
		}
	// Manual pause follows policy, and restart permits second-hit startup again.
	c.restartAfterBreak = true; s.configure(c); s.pause(true); CHECK(s.getSamples() == 0);
	CHECK(s.sample(-30, 50, true).cue == State::SILENT);
	CHECK(s.sample(0, 50, true).cue == State::LATE);
	c.restartAfterBreak = false; s.configure(c); auto count = s.getSamples(); s.pause(false); CHECK(s.getSamples() == count);
	// Clock follows real elapsed time when playback speed changes between frames.
	s.setActivities({{0, 10000}}); s.advance(0, 1); s.advance(1000, 1); s.advance(3000, 2); near(s.getActiveMS(), 2000);
	// Explicit seek uses reset; ordinary clock corrections retain learned hits.
	s.sample(20, 50, true); s.advance(2990, 2); CHECK(s.getSamples() == 1);
	s.reset(); s.advance(0, 1); CHECK(s.getSamples() == 0);
	CHECK(s.sample(10, 50, false).cue == State::SILENT);
	CHECK(s.sample(-10, 50, false).cue == State::SILENT);
	// A single advance can cross several gaps, including a qualifying one.
	s.setActivities({{0, 0}, {1000, 1000}, {5000, 5000}, {6000, 6000}});
	s.advance(0, 1); s.advance(6000, 1); near(s.getActiveMS(), 2000);
	// Qualification at exactly three real seconds must not depend on frame size.
	for (double speed : {0.75, 1.5, 3.0})
	{
		const double end = 3000 * speed;
		s.setActivities({{0, 0}, {end, end}});
		s.advance(0, speed);
		for (double position = 17; position < end; position += 17) s.advance(position, speed);
		s.advance(end, speed);
		near(s.getActiveMS(), 0);
	}
	// An early accepted return resolves the WHOLE scheduled break first.
	for (bool restart : {false, true})
	{
		for (double speed : {0.75, 1.0, 1.5, 3.0})
		{
			c.restartAfterBreak = restart; s.configure(c);
			s.setActivities({{0, 0}, {700 * speed, 700 * speed}, {3700 * speed, 3700 * speed}}); seed(s, 0, speed);
			s.advance(3670 * speed, speed);
			r = s.sample(-30, 50, true, 3700 * speed);
			CHECK(r.precedingSamples == (restart ? 0u : 8u));
			CHECK(r.cue == (restart ? State::SILENT : State::EARLY));
			near(s.getActiveMS(), 700); near(s.getBaselineMS(), restart ? -30 : 0);
			s.advance(3700 * speed, speed);
			CHECK(s.getSamples() == (restart ? 1u : 9u)); // returning hit is not erased
		}
	}
	// Late departing judgements must not permanently weight an eventual long rest.
	c.restartAfterBreak = false; s.configure(c);
	s.setActivities({{0, 0}, {800, 800}, {3800, 3800}}); seed(s, 0);
	s.advance(900, 1); s.sample(100, 50, true, 800);
	s.advance(3812, 1); r = s.sample(12, 50, true, 3800);
	near(r.baselineMS, 1.376729551); CHECK(r.cue == State::LATE);
	// Short gaps retain their elapsed time; do not pre-emptively discard it.
	s.setActivities({{0, 0}, {800, 800}, {1500, 1500}}); seed(s, 0);
	s.advance(900, 1); s.sample(100, 50, true, 800);
	s.advance(1512, 1); r = s.sample(12, 50, true, 1500);
	near(r.baselineMS, 2.734505259); CHECK(r.cue == State::SILENT);
	// Multiple late judgements at a shared opportunity all stay in the sample count.
	s.setActivities({{0, 0}, {800, 800}, {3800, 3800}}); seed(s, 0);
	s.advance(900, 1); s.sample(100, 50, true, 800);
	s.advance(920, 1); s.sample(120, 50, true, 800);
	s.advance(3812, 1); r = s.sample(12, 50, true, 3800);
	near(r.baselineMS, 1.376729551); CHECK(r.precedingSamples == 10); CHECK(r.cue == State::LATE);
	// Classification uses elapsed real time, not a prediction made at departure.
	s.setActivities({{0, 0}, {800, 800}, {3800, 3800}}); seed(s, 0);
	s.advance(900, 1); s.sample(100, 50, true, 800);
	s.advance(3800, 3); r = s.sample(12, 50, true, 3800);
	near(r.baselineMS, 2.734505259); // speeding up made the gap shorter than 3s
	s.setActivities({{0, 0}, {800, 800}, {2800, 2800}}); seed(s, 0);
	s.advance(900, 1); s.sample(100, 50, true, 800);
	s.advance(2806, 0.5); r = s.sample(12, 50, true, 2800);
	near(r.baselineMS, 1.376729551); // slowing down made the gap qualify
	// Raw/interpolated clock correction after pause must preserve retained timing.
	s.setActivities({{0, 10000}}); s.advance(0, 1); s.advance(3000, 1);
	s.sample(20, 50, true); s.pause(false); s.advance(2980, 1);
	CHECK(s.getSamples() == 1); near(s.getBaselineMS(), 20); near(s.getActiveMS(), 3000);
	s.advance(3010, 1); CHECK(s.getSamples() == 1); near(s.getActiveMS(), 3010);
	// Pre-roll (negative music time) can contain eligible hits.
	s.reset(); s.advance(-30, 1);
	CHECK(s.sample(-30, 50, false, 0).cue == State::EARLY);
	s.advance(500, 1); r = s.sample(0, 50, true, 500);
	CHECK(r.precedingSamples == 1); CHECK(r.cue == State::LATE);

	const auto start = std::chrono::steady_clock::now();
	s.setActivities({{0, 50000000}});
	for (int i = 0; i < 1000000; ++i) { s.advance(i * 50.0, 1); s.sample((i % 5 - 2) * 20, 50, true); }
	const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
	std::printf("PASS: timing state contracts; 1000000 samples %.3fs, %.3fus/sample; baseline %.3fms\n", seconds, seconds, s.getBaselineMS());
}

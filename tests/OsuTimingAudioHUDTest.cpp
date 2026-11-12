#include "../src/App/Osu/OsuTimingAudioHUD.h"
#include "../src/App/Osu/OsuTimingAudioState.h"

#include <cassert>

using State = OsuTimingAudioState;
using Evaluation = OsuTimingAudioEvaluation;

static void near(double actual, double expected)
{
	assert(std::abs(actual - expected) < 0.00001);
}

int main()
{
	State state;
	State::Config config;
	config.deadZoneMS = 4;
	state.configure(config);
	assert(state.getLastEvaluation().phase == Evaluation::WAITING);
	const State::Window fast = {50, 1.5};
	const State::Window slow = {50, 0.75};
	state.advance(0, fast.speed);
	const auto target = OsuTimingAudioReference::calculate(0, fast.speed, 1.5L, {50.9, 100.9, 150.9});
	assert(target.valid);

	// Two errors of 10 and 30 real ms give mean 20 and population SD 10.
	assert(state.sampleMap(15, fast, true, 0, 0).cue == State::SILENT);
	assert(state.getLastEvaluation().phase == Evaluation::WARMUP);
	assert(!OsuTimingAudioHUD::project(state.getLastEvaluation(), 150, 90).showReference);
	assert(state.sampleMap(45, fast, true, 0, 0).cue == State::LATE);
	assert(!OsuTimingAudioHUD::project(state.getLastEvaluation(), 150, 90).spread.visible);
	assert(state.sampleMap(81, fast, false, 0, target.preciseTargetMapMS).cue == State::SILENT);
	const auto beatmap = state.getLastEvaluation();
	assert(beatmap.phase == Evaluation::ACTIVE && !beatmap.recent);
	const auto shifted = OsuTimingAudioHUD::project(beatmap, 150, 90);
	near(shifted.reference, 45);
	assert(shifted.showMean);
	near(shifted.mean, 18);
	near(shifted.spread.lower, 9);
	near(shifted.spread.upper, 27);
	near(shifted.silent.lower, 41.4);
	near(shifted.silent.upper, 48.6);
	const auto shiftedMarkers = OsuTimingAudioHUD::project(beatmap, 150, 90, true);
	assert(!shiftedMarkers.spread.visible && !shiftedMarkers.silent.visible);
	assert(shiftedMarkers.showReference && shiftedMarkers.showMean);
	near(shiftedMarkers.reference, shifted.reference);
	near(shiftedMarkers.mean, shifted.mean);

	// Reading and projecting cannot advance the estimator or replace the hit.
	const double mean = state.getBaselineMS(), variance = state.getVarianceMS2();
	const auto wideWindow = OsuTimingAudioHUD::project(state.getLastEvaluation(), 300, 120);
	near(wideWindow.reference, 30);
	near(wideWindow.silent.upper, 32.4);
	assert(state.getSamples() == 3 && state.getBaselineMS() == mean && state.getVarianceMS2() == variance);
	near(state.getLastEvaluation().referenceMapMS, 75);
	state.advance(1000, 2.0); // time and rate can advance without a new evaluation
	near(state.getActiveMS(), 500);
	const auto afterRateChange = OsuTimingAudioHUD::project(state.getLastEvaluation(), 150, 90);
	near(afterRateChange.reference, 45);
	near(afterRateChange.spread.lower, 9);
	near(afterRateChange.silent.upper, 48.6);
	const auto narrowWindow = OsuTimingAudioHUD::project(beatmap, 72, 90);
	assert(!narrowWindow.showReference && narrowWindow.silent.visible && !narrowWindow.silent.showUpperCap);
	near(narrowWindow.silent.upper, 90);

	// In Recent mode both are centred on the preceding learned mean, with
	// each real-play interval projected at the speed of the hit that used it.
	config.bandMode = State::RELATIVE_300;
	config.relativeFraction = 0.2L;
	state.configure(config);
	assert(state.sampleMap(23, slow, true, 0, 0).cue == State::SILENT);
	const auto recent = state.getLastEvaluation();
	assert(recent.phase == Evaluation::ACTIVE && recent.recent);
	const auto relative = OsuTimingAudioHUD::project(recent, 150, 150);
	near(relative.reference, 23.5);
	near(relative.silent.lower, 13.5);
	near(relative.silent.upper, 33.5);
	near((relative.spread.lower + relative.spread.upper) / 2, 23.5);
	assert(relative.showMean);
	near(relative.mean, relative.reference);
	const auto recentMarkers = OsuTimingAudioHUD::project(recent, 150, 150, true);
	assert(recentMarkers.showReference && recentMarkers.showMean);
	near(recentMarkers.mean, recentMarkers.reference);

	config.bandMode = State::ADAPTIVE_SPREAD;
	config.adaptiveScale = 2;
	config.adaptiveMinFraction = 0.1L;
	config.adaptiveMaxFraction = 0.2L;
	state.configure(config);
	state.reset(); // same reset used by seek and retry
	assert(state.getLastEvaluation().phase == Evaluation::WAITING);
	assert(state.sampleMap(15, fast, false, 0, 0).cue == State::LATE);
	assert(state.getLastEvaluation().fixedFallback);
	near(state.getLastEvaluation().silentMapMS.upper, 6);
	assert(state.sampleMap(45, fast, false, 0, 0).cue == State::LATE);
	assert(state.getLastEvaluation().fixedFallback);
	assert(state.sampleMap(10, fast, false, 0, 0).cue == State::SILENT);
	assert(!state.getLastEvaluation().fixedFallback);
	const auto adaptive = OsuTimingAudioHUD::project(state.getLastEvaluation(), 150, 150);
	near(adaptive.spread.upper - adaptive.spread.lower, 30);
	near(adaptive.silent.lower, -10);
	near(adaptive.silent.upper, 10);

	config.bandMode = State::FIXED_MS;
	config.deadZoneMS = 0;
	state.configure(config);
	assert(state.sampleMap(0, slow, false, 0, 0).cue == State::SILENT);
	const auto zero = OsuTimingAudioHUD::project(state.getLastEvaluation(), 100, 50);
	assert(zero.showReference && zero.silent.visible);
	near(zero.reference, 0);
	near(zero.silent.lower, 0);
	near(zero.silent.upper, 0);
	assert(state.sampleMap(1, slow, false, 0, 0).cue == State::LATE);
	assert(state.sampleMap(-1, slow, false, 0, 0).cue == State::EARLY);

	config.require300 = true;
	state.configure(config);
	state.reset();
	assert(state.sampleMap(75, slow, false, 0, 0).cue == State::SILENT);
	assert(state.getLastEvaluation().phase == Evaluation::GATED && state.getSamples() == 1);
	assert(state.sampleMap(25, slow, false, 0, 0).cue == State::SILENT);
	assert(state.getLastEvaluation().phase == Evaluation::GATED && state.getSamples() == 2);
	const auto gated = OsuTimingAudioHUD::project(state.getLastEvaluation(), 150, 100);
	assert(gated.showReference && !gated.silent.visible);
	state.sampleMap(0, fast, false, 0, std::numeric_limits<long double>::quiet_NaN());
	assert(state.getLastEvaluation().phase == Evaluation::INVALID);
	assert(!OsuTimingAudioHUD::project(state.getLastEvaluation(), 150, 100).showReference);

	state.pause(false);
	assert(state.getLastEvaluation().phase == Evaluation::INVALID);
	state.pause(true);
	assert(state.getLastEvaluation().phase == Evaluation::WAITING);
	config.require300 = false;
	config.silentStartup = true;
	config.restartAfterBreak = true;
	state.configure(config);
	state.setActivities({{0, 0}, {10000, 10000}});
	state.advance(0, fast.speed);
	for (int i = 0; i < 8; ++i)
	{
		assert(state.sampleMap(15, fast, true, 0, 0).cue == State::SILENT);
		assert(state.getLastEvaluation().phase == Evaluation::WARMUP);
	}
	assert(state.sampleMap(30, fast, true, 0, 0).cue == State::LATE);
	assert(state.getLastEvaluation().phase == Evaluation::ACTIVE);
	state.advance(6000, fast.speed);
	assert(state.getLastEvaluation().phase == Evaluation::WAITING);
	assert(state.getSamples() == 0);

	// A late hit at half speed can leave a Recent reference and band well
	// beyond the visible map window when the next eligible hit is at double speed.
	State offBar;
	State::Config narrowBand;
	narrowBand.deadZoneMS = 5;
	offBar.configure(narrowBand);
	offBar.sampleMap(100, {49, 0.5}, true, 0, 0);
	offBar.sampleMap(20, {49, 2.0}, true, 0, 0);
	const auto offBarHit = offBar.getLastEvaluation();
	near(offBarHit.referenceMapMS, 400);
	near(offBarHit.silentMapMS.lower, 390);
	near(offBarHit.silentMapMS.upper, 410);
	const auto clipped = OsuTimingAudioHUD::project(offBarHit, 149.5, 149.5);
	assert(!clipped.showReference && !clipped.silent.visible);
	const auto clippedMarkers = OsuTimingAudioHUD::project(offBarHit, 149.5, 149.5, true);
	assert(!clippedMarkers.showReference && !clippedMarkers.showMean);

	offBar.sampleMap(20, {49, 2.0}, false, 0, 0);
	const auto partial = OsuTimingAudioHUD::project(offBar.getLastEvaluation(), 300, 300);
	assert(partial.spread.visible && partial.showMean && !partial.spread.showUpperCap);
	near(partial.spread.lower, 20);
	near(partial.spread.upper, 300);
	near(partial.mean, 210); // midpoint of 20..400, not midpoint of the clipped 20..300
	const auto meanOffBar = OsuTimingAudioHUD::project(offBar.getLastEvaluation(), 149.5, 149.5);
	assert(meanOffBar.spread.visible && !meanOffBar.showMean && !meanOffBar.spread.showUpperCap);
	const auto meanOffBarMarkers = OsuTimingAudioHUD::project(offBar.getLastEvaluation(), 149.5, 149.5, true);
	assert(meanOffBarMarkers.showReference && !meanOffBarMarkers.showMean);
}

#include "../src/App/Osu/OsuTimingAudioHUD.h"
#include "../src/App/Osu/OsuTimingAudioRecentWindow.h"
#include "../src/App/Osu/OsuTimingAudioPlayClock.h"
#include "../src/App/Osu/OsuTimingAudioState.h"

#include <cassert>

using State = OsuTimingAudioState;
using Evaluation = OsuTimingAudioEvaluation;

static void near(double actual, double expected)
{
	assert(std::abs(actual - expected) < 0.00001);
}

static void checkLiveEvaluation()
{
	State state;
	const State::Window window = {50, 1.5};
	assert(state.getCurrentEvaluation(window, true, 0).phase == Evaluation::WARMUP);
	state.sampleMap(-12, window, true, 0, 0);
	state.sampleMap(36, window, true, 0, 0);
	const auto last = state.getLastEvaluation();
	near(last.referenceMapMS, -12);
	assert(!std::isfinite(last.spreadMapMS.lower));

	const auto live = state.getCurrentEvaluation(window, true, 0);
	assert(live.phase == Evaluation::ACTIVE);
	near(live.referenceMapMS, 12);
	near(live.learnedMeanMapMS, 12);
	near(live.spreadMapMS.lower, -12);
	near(live.spreadMapMS.upper, 36);
	near(live.silentMapMS.lower, -3);
	near(live.silentMapMS.upper, 27);

	State::Config config;
	config.bandMode = State::RELATIVE_300;
	config.relativeFraction = 0.25;
	state.configure(config);
	const auto revised = state.getCurrentEvaluation({40, 2}, false, 40);
	near(revised.referenceMapMS, 40);
	near(revised.learnedMeanMapMS, 16);
	near(revised.spreadMapMS.upper, 48);
	near(revised.silentMapMS.lower, 30);
	near(revised.silentMapMS.upper, 50);
	near(state.getLastEvaluation().referenceMapMS, -12);
	assert(state.getSamples() == 2);
	assert(state.getCurrentEvaluation({40, 0}, false, 40).phase == Evaluation::INVALID);
	config.require300 = true;
	state.configure(config);
	assert(state.getCurrentEvaluation({10, 2}, false, 10).phase == Evaluation::GATED);
	config.fixedHits = true;
	assert(state.wouldResetEstimator(config));
	const auto pending = state.getCurrentEvaluation(window, true, 0, config, true);
	assert(pending.phase == Evaluation::WARMUP && !std::isfinite(pending.learnedMeanMapMS));
	assert(state.getSamples() == 2);
	near(state.getLastEvaluation().referenceMapMS, -12);
	const auto generation = state.getGeneration();
	state.reset();
	assert(state.getGeneration() != generation);
	assert(!std::isfinite(state.getCurrentEvaluation(window, true, 0).learnedMeanMapMS));
}

static void checkRecentWindow()
{
	OsuTimingAudioRecentWindow history;
	OsuTimingAudioPlayClock clock;
	clock.advance(0, true);
	history.recordAcceptedHit(clock.seconds(), -6);
	clock.advance(1, true);
	history.recordAcceptedHit(clock.seconds(), 18);
	history.recordAcceptedHit(clock.seconds(), std::numeric_limits<double>::infinity());
	const auto moments = history.getMoments(clock.seconds(), 5);
	assert(moments.count == 2);
	near(moments.meanMS, 6);
	near(moments.varianceMS2, 144);

	State state;
	state.sampleMap(15, {50, 1.5}, false, 0, 0);
	auto view = state.getCurrentEvaluation({50, 1.5}, false, 30);
	history.apply(view, 1.5, clock.seconds(), 5);
	near(view.learnedMeanMapMS, 9);
	near(view.spreadMapMS.lower, -9);
	near(view.spreadMapMS.upper, 27);
	near(view.referenceMapMS, 30);
	near(view.silentMapMS.lower, 15);
	near(view.silentMapMS.upper, 45);
	assert(history.getMoments(clock.seconds(), 5).count == 2 && state.getSamples() == 1);

	clock.advance(1, false);
	clock.advance(10, false);
	clock.advance(20, true);
	clock.advance(23.99, true);
	assert(history.getMoments(clock.seconds(), 5).count == 2);
	clock.advance(24, true); // exactly five playing seconds after the first hit
	assert(history.getMoments(clock.seconds(), 5).count == 1);
	history.apply(view, 2, clock.seconds(), 5);
	near(view.learnedMeanMapMS, 36);
	assert(!std::isfinite(view.spreadMapMS.lower));
	clock.advance(25, true);
	assert(history.getMoments(clock.seconds(), 5).count == 0);
	assert(history.getMoments(clock.seconds(), 7).count == 2);
	history.recordAcceptedHit(clock.seconds(), 25);
	history.reset();
	history.apply(view, 1, clock.seconds(), 5);
	assert(!std::isfinite(view.learnedMeanMapMS));

	clock = OsuTimingAudioPlayClock();
	clock.advance(100, false);
	history.recordAcceptedHit(clock.seconds(), -50); // accepted before playback starts
	clock.advance(110, false);
	clock.advance(111, true);
	history.recordAcceptedHit(clock.seconds(), 0);
	assert(history.getMoments(clock.seconds(), 5).count == 2);
	near(history.getMoments(clock.seconds(), 5).meanMS, -25);
	clock.advance(112, true);
	clock.advance(111.5, true);
	clock.advance(112, true);
	near(clock.seconds(), 1);
	clock.advance(std::numeric_limits<double>::quiet_NaN(), true);
	clock.advance(114, true);
	near(clock.seconds(), 1);
	for (int i = 0; i < 2048; ++i) history.recordAcceptedHit(clock.seconds(), i);
	assert(history.truncated(1, 5) && history.getMoments(1, 5).count == 2048);
	assert(!history.truncated(5, 5));
}

static void checkTransition()
{
	OsuTimingAudioView view;
	view.evaluation.phase = Evaluation::ACTIVE;
	view.evaluation.learnedMeanMapMS = 10;
	view.evaluation.spreadMapMS = {5, 15};
	OsuTimingAudioHUD::Transition direct, partitioned;
	direct.present(view, 100, 0);
	partitioned.present(view, 100, 0);
	view.evaluation.learnedMeanMapMS = 22;
	view.evaluation.spreadMapMS = {9, 35};
	view.evaluation.referenceMapMS = 22;
	view.evaluation.silentMapMS = {15, 29};
	near(direct.present(view, 100, 1).learnedMeanMapMS, 10);
	partitioned.present(view, 100, 1);
	partitioned.present(view, 100, 1.03);
	const auto mid = direct.present(view, 100, 1.06);
	near(mid.learnedMeanMapMS, 16);
	near(mid.learnedMeanMapMS, partitioned.present(view, 100, 1.06).learnedMeanMapMS);
	near(mid.spreadMapMS.upper, 25);
	near(mid.referenceMapMS, 22);
	near(mid.silentMapMS.upper, 29);
	near(direct.present(view, 100, 2).learnedMeanMapMS, 22);

	view.generation++;
	view.evaluation.learnedMeanMapMS = 6;
	near(direct.present(view, 100, 2.01).learnedMeanMapMS, 6);
	view.speed = 2;
	view.evaluation.learnedMeanMapMS = 12;
	near(direct.present(view, 100, 2.02).learnedMeanMapMS, 12);
	view.evaluation.learnedMeanMapMS = 110;
	assert(!OsuTimingAudioHUD::project(direct.present(view, 100, 2.03), 100, 100).showMean);
	view.evaluation.phase = Evaluation::OFF;
	view.evaluation.learnedMeanMapMS = std::numeric_limits<double>::quiet_NaN();
	assert(!std::isfinite(direct.present(view, 100, 2.04).learnedMeanMapMS));
}

static void checkProjection()
{
	State state;
	const State::Window window = {50, 1};
	auto empty = state.getCurrentEvaluation(window, false, 30);
	state.projectNextHit(empty, 1, true);
	assert(!std::isfinite(empty.learnedMeanMapMS));

	state.advance(0, 1);
	state.sampleMap(0, window, false, 0, 30);
	auto startup = state.getCurrentEvaluation(window, false, 30);
	state.projectNextHit(startup, 1, true);
	near(startup.learnedMeanMapMS, 15);
	near(startup.spreadMapMS.upper, 30);
	for (int i = 1; i < 8; ++i)
		state.sampleMap(i % 2 ? 20 : 0, window, false, 0, 30);
	auto noTime = state.getCurrentEvaluation(window, false, 30);
	state.projectNextHit(noTime, 1, true);
	near(noTime.learnedMeanMapMS, 10);
	near(noTime.spreadMapMS.upper, 20);

	state.advance(5000, 1); // One active-play half-life without an observation.
	auto average = state.getCurrentEvaluation(window, false, 30);
	auto reference = average;
	state.projectNextHit(average, 1, false);
	state.projectNextHit(reference, 1, true);
	near(average.learnedMeanMapMS, 10);
	near(average.spreadMapMS.upper, 10 + std::sqrt(50.0));
	near(reference.learnedMeanMapMS, 20);
	near(reference.spreadMapMS.upper, 20 + std::sqrt(150.0));
	near(reference.referenceMapMS, 30);
	near(reference.silentMapMS.upper, 40);
	assert(state.getSamples() == 8);
	near(state.getBaselineMS(), 10);
	near(state.getVarianceMS2(), 100);
	state.sampleMap(30, window, false, 5000, 30);
	const auto observed = state.getCurrentEvaluation(window, false, 30);
	near(observed.learnedMeanMapMS, reference.learnedMeanMapMS);
	near(observed.spreadMapMS.lower, reference.spreadMapMS.lower);

	State::Config config;
	config.fixedHits = true;
	state.configure(config);
	for (int i = 0; i < 8; ++i) state.sampleMap(i % 2 ? 20 : 0, window, false, 0, 30);
	auto fixed = state.getCurrentEvaluation(window, false, 30);
	state.projectNextHit(fixed, 1, true);
	state.advance(5000, 1);
	auto fixedLater = state.getCurrentEvaluation(window, false, 30);
	state.projectNextHit(fixedLater, 1, true);
	near(fixed.learnedMeanMapMS, fixedLater.learnedMeanMapMS);
	near(fixed.spreadMapMS.upper, fixedLater.spreadMapMS.upper);
}

int main()
{
	checkLiveEvaluation();
	checkRecentWindow();
	checkTransition();
	checkProjection();
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
	const auto shiftedMarkers = OsuTimingAudioHUD::project(beatmap, 150, 90, false, false);
	assert(!shiftedMarkers.spread.visible && !shiftedMarkers.silent.visible);
	assert(shiftedMarkers.showReference && shiftedMarkers.showMean);
	near(shiftedMarkers.reference, shifted.reference);
	near(shiftedMarkers.mean, shifted.mean);
	const auto withoutSpread = OsuTimingAudioHUD::project(beatmap, 150, 90, false, true);
	assert(!withoutSpread.spread.visible && withoutSpread.silent.visible);
	near(withoutSpread.mean, shifted.mean);
	const auto withoutBand = OsuTimingAudioHUD::project(beatmap, 150, 90, true, false);
	assert(withoutBand.spread.visible && !withoutBand.silent.visible);
	near(withoutBand.reference, shifted.reference);

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
	const auto recentMarkers = OsuTimingAudioHUD::project(recent, 150, 150, false, false);
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
	const auto clippedMarkers = OsuTimingAudioHUD::project(offBarHit, 149.5, 149.5, false, false);
	assert(!clippedMarkers.showReference && !clippedMarkers.showMean);

	offBar.sampleMap(20, {49, 2.0}, false, 0, 0);
	const auto partial = OsuTimingAudioHUD::project(offBar.getLastEvaluation(), 300, 300);
	assert(partial.spread.visible && partial.showMean && !partial.spread.showUpperCap);
	near(partial.spread.lower, 20);
	near(partial.spread.upper, 300);
	near(partial.mean, 210); // midpoint of 20..400, not midpoint of the clipped 20..300
	const auto meanOffBar = OsuTimingAudioHUD::project(offBar.getLastEvaluation(), 149.5, 149.5);
	assert(meanOffBar.spread.visible && !meanOffBar.showMean && !meanOffBar.spread.showUpperCap);
	const auto meanOffBarMarkers = OsuTimingAudioHUD::project(offBar.getLastEvaluation(), 149.5, 149.5, false, false);
	assert(meanOffBarMarkers.showReference && !meanOffBarMarkers.showMean);
}

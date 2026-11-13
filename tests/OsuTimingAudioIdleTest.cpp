#include "../src/App/Osu/OsuTimingAudioState.h"
#include <cassert>

using State = OsuTimingAudioState;
using View = OsuTimingAudioView;
using Evaluation = OsuTimingAudioEvaluation;

static const State::Window window = {50, 2};

static State::Config idleConfig()
{
	State::Config config;
	config.bandMode = State::ADAPTIVE_SPREAD;
	config.idleForgiveness = true;
	config.deadZoneMS = 3;
	config.adaptiveScale = 0;
	config.adaptiveMinFraction = 0.2L;
	config.adaptiveMaxFraction = 0.8L;
	return config;
}

static void near(double value, double expected)
{
	assert(std::abs(value - expected) < 1e-9);
}

static Evaluation query(const State &state, const State::Config &config, double seconds, View::BandStatus &band)
{
	return state.getCurrentEvaluation(window, false, 0, config, state.wouldResetEstimator(config), &band, seconds);
}

static void startup()
{
	for (bool idle : {false, true})
		for (bool maximum : {false, true})
		{
			State state;
			auto config = idleConfig();
			config.idleForgiveness = idle;
			config.adaptiveStartupMaximum = maximum;
			state.configure(config);
			for (int i = 0; i < 2; ++i)
			{
				const auto sample = state.sampleMap(6, window, false, 0, 0, i);
				assert(sample.accepted && sample.cue == State::SILENT);
				assert(sample.fixedFallback == !maximum);
				near(sample.halfWidthMS, maximum ? 20 : 3);
			}
			View::BandStatus band;
			query(state, config, 1, band);
			assert(band.idleActive == idle && !band.startupMaximum);
			near(band.allowance, idle && maximum ? 0.75 : 0);
			near(band.resolvedHalfWidthMS, idle && maximum ? 16.25 : 5);
		}
}

static void idleReturn()
{
	State state;
	auto config = idleConfig();
	state.configure(config);
	state.sampleMap(-20, window, false, 0, 0, 0);
	state.sampleMap(20, window, false, 0, 0, 0);
	View::BandStatus band;
	query(state, config, 1, band);
	near(band.allowance, 0);
	near(band.resolvedHalfWidthMS, 5);
	const auto current = query(state, config, 2.5, band);
	near(band.allowance, 0.5);
	near(band.ordinaryHalfWidthMS, 5);
	near(band.maximumHalfWidthMS, 20);
	near(band.resolvedHalfWidthMS, 12.5);
	near(current.silentMapMS.upper, 25);
	near(current.silentMapMS.lower, -25);
	const auto before = state.getLastEvaluation();
	query(state, config, 4, band);
	near(band.resolvedHalfWidthMS, 20);
	assert(state.getSamples() == 2 && before.silentMapMS.upper == state.getLastEvaluation().silentMapMS.upper);
	near(state.secondsSinceAcceptedHit(4), 4);

	for (double sign : {-1.0, 1.0})
	{
		State edge = state, outside = state;
		const double endpoint = sign * current.silentMapMS.upper;
		assert(edge.sampleMap(endpoint, window, false, 0, 0, 2.5).cue == State::SILENT);
		assert(outside.sampleMap(endpoint + sign * 0.001, window, false, 0, 0, 2.5).cue
			== (sign < 0 ? State::EARLY : State::LATE));
	}
	assert(state.sampleMap(25, window, false, 0, 0, 2.5).accepted);
	assert(state.getLastEvaluation().silentMapMS.upper == current.silentMapMS.upper);
	query(state, config, 2.5, band);
	near(band.allowance, 0.25);
	assert(!state.sampleMap(0, {50, 0}, false, 0, 0, 2.5).accepted);
	query(state, config, 2.5, band);
	near(band.allowance, 0.25);
	assert(state.sampleMap(0, window, false, 0, std::numeric_limits<long double>::quiet_NaN(), 2.5).accepted);
	query(state, config, 2.5, band);
	near(band.allowance, 0);
	query(state, config, 5, band);
	near(band.allowance, 0.5);
	state.sampleMap(0, window, false, 0, 0, 5);
	query(state, config, 7.5, band);
	near(band.allowance, 0.75);

	config.idleGraceSeconds = 0;
	config.idleRampSeconds = 0;
	config.idleRecoveryHits = 1;
	state.configure(config, 7.5);
	query(state, config, 7.5, band);
	near(band.allowance, 1);
	state.sampleMap(0, window, false, 0, 0, 7.5);
	query(state, config, 7.5, band);
	near(band.allowance, 0);
	query(state, config, 7.50001, band);
	near(band.allowance, 1);

	config.idleForgiveness = false;
	state.configure(config, 7.5);
	config.idleForgiveness = true;
	query(state, config, 8, band); // pending activation and live activation agree
	near(band.allowance, 0);
	state.configure(config, 8);
	query(state, config, 8, band);
	near(band.allowance, 0);
}

static void learnerAndBreaks()
{
	State state;
	auto config = idleConfig();
	config.startupAverageHits = 1;
	config.silentStartup = true;
	config.silentStartupHits = 3;
	config.fixedHits = true;
	config.halfLifeHits = 1;
	config.restartAfterBreak = true;
	config.breakSeconds = 1;
	state.configure(config);
	state.setActivities({{0, 0}, {4000, 4000}});
	state.advance(0, 2);
	state.sampleMap(0, window, true, 0, 0, 0);
	state.sampleMap(16, window, true, 0, 0, 0);
	state.sampleMap(0, window, true, 0, 0, 0);
	near(state.getBaselineMS(), 2);
	assert(state.getLastEvaluation().phase == Evaluation::WARMUP);
	assert(state.getCurrentEvaluation(window, true, 0).phase == Evaluation::ACTIVE);
	state.advance(500, 2);
	View::BandStatus band;
	query(state, config, 4, band);
	near(band.resolvedHalfWidthMS, 20);
	const auto early = state.sampleMap(-20, window, false, 4000, 0, 4);
	assert(early.accepted && early.precedingSamples == 0 && early.fixedFallback && early.cue == State::EARLY);
	near(early.halfWidthMS, 3);
	assert(state.getSamples() == 1 && state.secondsSinceAcceptedHit(4) == 0);
	config.startupAverageHits = 2;
	query(state, config, 4, band);
	assert(band.learnedHits == 0 && state.getSamples() == 1);
	state.configure(config, 4);
	assert(state.getSamples() == 0 && !std::isfinite(state.secondsSinceAcceptedHit(4)));
}

int main()
{
	startup();
	idleReturn();
	learnerAndBreaks();
}

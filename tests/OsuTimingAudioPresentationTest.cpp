#include "../src/App/Osu/OsuTimingCuePresentation.h"
#include "../src/App/Osu/OsuTimingAudioState.h"
#include <cassert>

int main()
{
	using State = OsuTimingAudioState;
	namespace Cue = OsuTimingCuePresentation;
	for (int direction : {-1, 1})
	{
		assert(Cue::side(direction, false) == direction && Cue::side(direction, true) == -direction);
		assert(Cue::pan(direction, false, true) == 0 && Cue::pan(direction, true, false) == direction);
		assert(Cue::pan(direction, true, true) == -direction);
		State state;
		assert(state.sampleMap(direction * 15, {50, 1.5}, false, 0, 0).cue == State::SILENT);
		const auto outside = state.sampleMap(direction * 21, {50, 1.5}, false, 0, 0);
		assert(outside.cue == direction && outside.excessMS == 4);
		assert(state.getLastEvaluation().excessMS == 4);
		State recent;
		recent.sampleMap(15, {50, 1.5}, true, 0, 0);
		const auto recentOutside = recent.sampleMap(15 + direction * 21, {50, 1.5}, true, 0, 0);
		assert(recentOutside.cue == direction && recentOutside.excessMS == 4);
		State::Config config;
		config.bandMode = State::RELATIVE_300;
		state.configure(config);
		const auto shifted = state.sampleMap(25 + direction * 16, {50, 2}, false, 0, 25);
		assert(shifted.cue == direction && shifted.excessMS == 3);
	}
	Cue::Pulse pulse;
	pulse.direction = -1;
	pulse.started = 10;
	pulse.excessMS = 12;
	assert(std::abs(pulse.opacity(10, 0, .5, 1, true, 24, .2) - .6) < 1e-12);
	assert(std::abs(pulse.opacity(10.25, 0, .5, 1, true, 24, .2) - .3) < 1e-12);
	assert(pulse.opacity(10.25, .25, .5, 1, false, 24, 0) == 1);
	assert(pulse.opacity(10.5, 0, .5, 1, false, 24, 0) == 0 && pulse.opacity(9, 0, .5, 1, false, 24, 0) == 0);
	pulse.excessMS = 100;
	assert(pulse.opacity(10, 0, .5, 1, true, 24, .2) == 1);
	const auto left = Cue::margin(-1, 1280, 720, 120, .05, .4, .01, .25);
	const auto right = Cue::margin(1, 1280, 720, 1160, .05, .4, .01, .25);
	assert(left.x == 12 && left.width == 64 && right.x == 1204 && right.width == 64);
	assert(left.y == 36 && left.height == 288 && right.y == left.y);
	assert(Cue::margin(-1, 1280, 720, 0, .05, .4, .01, .25).width == 0);
	assert(Cue::margin(1, 800, 1000, 775, .10, 1, 0, 1).width == 25);
	assert(Cue::margin(1, 800, 1000, 0, .10, 1, 0, 1).width == 80);
	for (int side : {-1, 1})
	{
		const auto overlap = Cue::margin(side, 800, 600, side < 0 ? 800 : 0, .125, .4, .15f, .5);
		assert(overlap.width == 100 && overlap.x == (side < 0 ? 120 : 580));
		const auto confined = Cue::margin(side, 800, 600, side < 0 ? 140 : 660, .125, .4, .15f, .5);
		assert(confined.width == 20 && confined.x == (side < 0 ? 120 : 660));
	}
}

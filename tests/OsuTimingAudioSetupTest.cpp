#include "../src/App/Osu/OsuTimingAudioSetup.h"
#include "../src/App/Osu/OsuTimingAudioState.h"
#include <cassert>

int main()
{
	OsuTimingAudioSettings::Values applied;
	applied["osu_timing_audio_recent"] = "0";
	applied["osu_timing_audio_target"] = "-0.2";
	applied["osu_timing_audio_deadzone_mode"] = "2";
	OsuTimingAudioState state;
	OsuTimingAudioState::Config config;
	config.bandMode = OsuTimingAudioState::ADAPTIVE_SPREAD;
	config.adaptiveMinFraction = 0.3L;
	state.configure(config);
	const OsuTimingAudioState::Window window = {50, 1.5};
	OsuTimingAudioView view;
	view.speed = 1.5;
	view.window300MapMS = 50;
	view.bandMode = config.bandMode;
	view.evaluation = state.getCurrentEvaluation(window, false, -10, config, false, &view.band);
	assert(view.evaluation.fixedFallback && view.band.learnedHits == 0);
	assert(view.band.baseHalfWidthMS == 10 && view.band.resolvedHalfWidthMS == 10);

	state.sampleMap(-6, window, false, 0, -10);
	state.sampleMap(6, window, false, 0, -10);
	view.evaluation = state.getCurrentEvaluation(window, false, -10, config, false, &view.band);
	view.evaluation.output = OsuTimingAudioEvaluation::MUTED;
	assert(view.band.baseHalfWidthMS == 4 && view.band.resolvedHalfWidthMS == 10);
	assert(view.band.learnedHits == 2 && view.band.limit == OsuTimingAudioView::BandStatus::MINIMUM);
	const auto text = OsuTimingAudioSetup::copyText(applied, view, OsuTimingAudioView::RECENT_WINDOW, true);
	assert(text.find("Unapplied editor changes are excluded.") != std::string::npos);
	assert(text.find("Beatmap / Adaptive spread") != std::string::npos);
	assert(text.find("Half-width: 10.00 ms (minimum clamp)") != std::string::npos);
	assert(text.find("Base half-width before limits 4.00 ms") != std::string::npos);
	assert(text.find("Playback 1.50x; 300 half-window 50.00 map ms; reference -10.00 map ms") != std::string::npos);
	assert(text.find("Learned SD: 4.00 ms / 2 hits") != std::string::npos);
	assert(text.find("Cue mute status muted") != std::string::npos);
	assert(text.find("HUD view Recent window (selected)") != std::string::npos);
	assert(text.find("ordinary 10.00 ms; cap 33.33 ms") != std::string::npos);
	assert(text.find("osu_timing_audio_target = -0.2") != std::string::npos);

	config.require300 = true;
	view.evaluation = state.getCurrentEvaluation(window, false, -10, config, true, &view.band);
	assert(view.band.learnedHits == 0 && view.band.limit == OsuTimingAudioView::BandStatus::NONE);
	assert(OsuTimingAudioSetup::summarize(applied, view).band == "Silent band: 300 gate active");
	assert(state.getSamples() == 2); // telemetry never applies the pending reset

	view = OsuTimingAudioView();
	const auto noMap = OsuTimingAudioSetup::summarize(applied, view);
	assert(noMap.band == "Silent band: waiting for gameplay");
	assert(noMap.spread == "Learned SD: unavailable");
}

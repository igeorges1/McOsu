#include "OsuTimingAudioFeedback.h"
#include "OsuTimingAudioReference.h"

#include "Engine.h"
#include "ConVar.h"
#include "ResourceManager.h"
#include "SoundEngine.h"
#include "Osu.h"
#include "OsuBeatmap.h"
#include "OsuGameRules.h"
#include "OsuHitObject.h"
#include <cstdlib>

ConVar osu_timing_audio("osu_timing_audio", false, FCVAR_NONE, "Opt-in timing audio experiment for manual circles and slider heads.");
ConVar osu_timing_audio_recent("osu_timing_audio_recent", true, FCVAR_NONE, "Recent timing reference; false selects beatmap timing. Switching preserves the baseline.");
ConVar osu_timing_audio_fixed_hits("osu_timing_audio_fixed_hits", false, FCVAR_NONE, "Use hit-count EMA instead of active-play-time EMA.");
ConVar osu_timing_audio_half_life_seconds("osu_timing_audio_half_life_seconds", 5.0f, FCVAR_NONE, "Active-play half-life in seconds after startup. Used in time adaptation.");
ConVar osu_timing_audio_half_life_hits("osu_timing_audio_half_life_hits", 16.0f, FCVAR_NONE, "Accepted-hit half-life after startup. Used in hit-count adaptation.");
ConVar osu_timing_audio_silent_startup("osu_timing_audio_silent_startup", false, FCVAR_NONE, "Mute Recent until its warmup count is reached.");
ConVar osu_timing_audio_silent_startup_hits("osu_timing_audio_silent_startup_hits", 8, FCVAR_NONE, "Preceding accepted hits required during silent Recent startup (0-128). Recent always needs at least one.");
ConVar osu_timing_audio_startup_average_hits("osu_timing_audio_startup_average_hits", 8, FCVAR_NONE, "Number of accepted hits using a running average before exponential weighting (1-128). Applying resets learning.");
ConVar osu_timing_audio_require_300("osu_timing_audio_require_300", false, FCVAR_NONE, "Mute BOTH references unless the preceding baseline exists and is inside the current 300 window. Muted hits still update.");
ConVar osu_timing_audio_restart("osu_timing_audio_restart", false, FCVAR_NONE, "Restart startup on pause and after qualifying breaks. Off retains the learner.");
ConVar osu_timing_audio_exclude_activity("osu_timing_audio_exclude_activity", false, FCVAR_NONE, "Also treat long slider-body/spinner spans without circle/head opportunities as breaks.");
ConVar osu_timing_audio_break_seconds("osu_timing_audio_break_seconds", 3.0f, FCVAR_NONE, "Real-play seconds; exclude the entire qualifying break from EMA time.");
ConVar osu_timing_audio_deadzone("osu_timing_audio_deadzone", 10.0f, FCVAR_NONE, "Silent +/- dead zone in real-play milliseconds.");
ConVar osu_timing_audio_target("osu_timing_audio_target", 0.0f, FCVAR_NONE, "Beatmap reference: 0=center, +/-1=300 edge, +/-2=100 edge, +/-3=50 edge. Recent ignores this setting; scores are unchanged.");
ConVar osu_timing_audio_deadzone_mode("osu_timing_audio_deadzone_mode", 0, FCVAR_NONE, "0=fixed milliseconds, 1=fraction of current 300 half-window, 2=preceding timing spread. Switching preserves learning.");
ConVar osu_timing_audio_deadzone_fraction("osu_timing_audio_deadzone_fraction", 0.2f, FCVAR_NONE, "Relative half-width as a fraction of the current 300 half-window.");
ConVar osu_timing_audio_deadzone_adaptive_scale("osu_timing_audio_deadzone_adaptive_scale", 1.0f, FCVAR_NONE, "Adaptive half-width in preceding population standard deviations. Uses the selected estimator's weights.");
ConVar osu_timing_audio_deadzone_adaptive_min("osu_timing_audio_deadzone_adaptive_min", 0.1f, FCVAR_NONE, "Adaptive minimum half-width as a fraction of the current 300 half-window.");
ConVar osu_timing_audio_deadzone_adaptive_max("osu_timing_audio_deadzone_adaptive_max", 1.0f, FCVAR_NONE, "Adaptive maximum half-width as a fraction of the current 300 half-window.");
ConVar osu_timing_audio_adaptive_startup_maximum("osu_timing_audio_adaptive_startup_maximum", false, FCVAR_NONE, "Use the adaptive maximum for the first two accepted hits. Off uses fixed width.");
ConVar osu_timing_audio_idle_forgiveness("osu_timing_audio_idle_forgiveness", false, FCVAR_NONE, "Widen the learned adaptive band toward its configured maximum during counted play without accepted hits.");
ConVar osu_timing_audio_idle_grace_seconds("osu_timing_audio_idle_grace_seconds", 1.0f, FCVAR_NONE, "Counted-play seconds before the band starts widening (0-60).");
ConVar osu_timing_audio_idle_ramp_seconds("osu_timing_audio_idle_ramp_seconds", 3.0f, FCVAR_NONE, "Counted-play seconds to ramp from zero allowance to the cap (0-60). Zero widens to cap after grace.");
ConVar osu_timing_audio_idle_recovery_hits("osu_timing_audio_idle_recovery_hits", 4, FCVAR_NONE, "Accepted hits to remove full idle allowance (1-128). A hit uses the width before its recovery step.");
ConVar osu_timing_audio_volume("osu_timing_audio_volume", 0.2f, FCVAR_NONE, "Independent cue gain, multiplied by master volume. Effects/hitsound volume does not mute it. Zero mutes while learning.");
ConVar osu_timing_audio_muted("osu_timing_audio_muted", false, FCVAR_NONE, "Mute training cues without changing gain or stopping learning. Feature off still resets learning.");
ConVar osu_timing_audio_early_sound("osu_timing_audio_early_sound", "timing-early.wav", FCVAR_NONE, "Early cue filename within sounds/. Changing sounds preserves learning; retry reloads the files.");
ConVar osu_timing_audio_late_sound("osu_timing_audio_late_sound", "timing-late.wav", FCVAR_NONE, "Late cue filename within sounds/. Supports custom WAVs.");
ConVar osu_timing_audio_retain_failed_cue("osu_timing_audio_retain_failed_cue", true, FCVAR_NONE, "Keep using the last good cue for a direction after a failed replacement. Off leaves that direction silent.");
ConVar osu_timing_audio_trace("osu_timing_audio_trace", false, FCVAR_NONE, "Log preceding baseline, error, output and actual playback success; diagnostic overhead only when enabled.");

static double timingAudioValue(float value, double fallback, double minimum, double maximum)
{
	return std::isfinite(value) ? std::max(minimum, std::min(maximum, (double)value)) : fallback;
}

// New coordinate/fraction controls retain the entered decimal precision instead
// of rounding through ConVar's float (which can move an inclusive cue boundary).
static long double timingAudioPreciseValue(const ConVar &var, long double fallback, long double minimum, long double maximum)
{
	const char *text = var.getString().toUtf8();
	char *end = NULL;
	const long double value = std::strtold(text, &end);
	return end != text && *end == '\0' && std::isfinite(value)
		? std::max(minimum, std::min(maximum, value)) : fallback;
}

struct TimingAudioInputs
{
	OsuTimingAudioState::Window window300;
	bool recent;
	long double target;
	OsuTimingAudioReference::Result reference;

	long double targetMapMS() const
	{
		return reference.valid ? reference.preciseTargetMapMS : std::numeric_limits<long double>::quiet_NaN();
	}
};

static TimingAudioInputs timingAudioInputs(OsuBeatmap *beatmap, long delta)
{
	const double speed = beatmap->getSpeedMultiplier();
	const bool recent = osu_timing_audio_recent.getBool();
	const long double target = recent ? 0.0L : timingAudioPreciseValue(osu_timing_audio_target, 0.0L, -3.0L, 3.0L);
	const double raw300 = OsuGameRules::getHitWindow300(beatmap);
	long edge300 = 0;
	const OsuTimingAudioState::Window window300 = {OsuTimingAudioReference::truncateWindow(raw300, edge300)
		? (double)edge300 : std::numeric_limits<double>::quiet_NaN(), speed};
	const auto reference = OsuTimingAudioReference::calculate(delta, speed, target,
		{raw300, target != 0.0 ? OsuGameRules::getHitWindow100(beatmap) : 0.0,
			target != 0.0 ? OsuGameRules::getHitWindow50(beatmap) : 0.0});
	return {window300, recent, target, reference};
}

static float timingAudioVolume()
{
	return osu_timing_audio_muted.getBool() ? 0.0f : timingAudioValue(osu_timing_audio_volume.getFloat(), 0.2, 0.0, 1.0);
}

static OsuTimingAudioState::Config timingAudioConfig()
{
	OsuTimingAudioState::Config config;
	config.fixedHits = osu_timing_audio_fixed_hits.getBool();
	config.halfLifeSeconds = timingAudioValue(osu_timing_audio_half_life_seconds.getFloat(), 5.0, 0.001, 3600.0);
	config.halfLifeHits = timingAudioValue(osu_timing_audio_half_life_hits.getFloat(), 16.0, 0.001, 100000.0);
	config.breakSeconds = timingAudioValue(osu_timing_audio_break_seconds.getFloat(), 3.0, 0.001, 3600.0);
	config.deadZoneMS = timingAudioValue(osu_timing_audio_deadzone.getFloat(), 10.0, 0.0, 1000.0);
	config.bandMode = static_cast<OsuTimingAudioState::BandMode>((int)timingAudioValue(osu_timing_audio_deadzone_mode.getFloat(), 0.0, 0.0, 2.0));
	config.relativeFraction = timingAudioPreciseValue(osu_timing_audio_deadzone_fraction, 0.2L, 0.0L, 10.0L);
	config.adaptiveScale = timingAudioPreciseValue(osu_timing_audio_deadzone_adaptive_scale, 1.0L, 0.0L, 10.0L);
	config.adaptiveMinFraction = timingAudioPreciseValue(osu_timing_audio_deadzone_adaptive_min, 0.1L, 0.0L, 10.0L);
	config.adaptiveMaxFraction = timingAudioPreciseValue(osu_timing_audio_deadzone_adaptive_max, std::max(1.0L, config.adaptiveMinFraction), config.adaptiveMinFraction, 10.0L);
	config.silentStartup = osu_timing_audio_silent_startup.getBool();
	config.silentStartupHits = (unsigned int)timingAudioValue(osu_timing_audio_silent_startup_hits.getFloat(), 8, 0, 128);
	config.startupAverageHits = (unsigned int)timingAudioValue(osu_timing_audio_startup_average_hits.getFloat(), 8, 1, 128);
	config.adaptiveStartupMaximum = osu_timing_audio_adaptive_startup_maximum.getBool();
	config.idleForgiveness = osu_timing_audio_idle_forgiveness.getBool();
	config.idleGraceSeconds = timingAudioValue(osu_timing_audio_idle_grace_seconds.getFloat(), 1, 0, 60);
	config.idleRampSeconds = timingAudioValue(osu_timing_audio_idle_ramp_seconds.getFloat(), 3, 0, 60);
	config.idleRecoveryHits = (unsigned int)timingAudioValue(osu_timing_audio_idle_recovery_hits.getFloat(), 4, 1, 128);
	config.require300 = osu_timing_audio_require_300.getBool();
	config.restartAfterBreak = osu_timing_audio_restart.getBool();
	return config;
}

OsuTimingAudioFeedback::OsuTimingAudioFeedback(OsuBeatmap *beatmap) : m_beatmap(beatmap), m_enabled(false), m_prepared(false), m_excludeActivity(false), m_breakSeconds(3.0)
{
}

OsuTimingAudioFeedback::~OsuTimingAudioFeedback()
{
	for (const Cue *cue : {&m_early, &m_late})
		if (cue->sound != NULL) engine->getResourceManager()->destroyResource(cue->sound);
}

void OsuTimingAudioFeedback::reset()
{
	m_state.reset();
	m_recentWindow.reset();
	m_playClock = OsuTimingAudioPlayClock();
	m_prepared = false;
	m_early.attemptedPath = "";
	m_late.attemptedPath = "";
}

void OsuTimingAudioFeedback::reloadSounds()
{
	// Backend restarts invalidate sample handles, not learned timing or file choices.
	// Reload the actual owned files, including a retained fallback after a failed change.
	for (const Cue *cue : {&m_early, &m_late})
		if (cue->sound != NULL) cue->sound->reload();
}

Sound *OsuTimingAudioFeedback::Cue::selected(const UString &requested, bool retain, OsuTimingAudioView::CueStatus *status) const
{
	const bool ready = sound != NULL && sound->isReady();
	const bool exact = ready && lastLoadSucceeded && attemptedPath == requested;
	const bool available = exact || (retain && ready);
	if (status != NULL)
	{
		if (available) status->activeFile = loadedPath.toUtf8();
		if (exact) status->reason = "requested file";
		else if (!(attemptedPath == requested)) status->reason = available ? "request pending; previous cue" : "request pending";
		else if (available) status->reason = "replacement failed; previous cue";
		else if (ready) status->reason = "replacement failed; silence selected";
		else status->reason = "requested cue unavailable";
	}
	return available ? sound : NULL;
}

void OsuTimingAudioFeedback::loadCue(Cue &cue, const UString &path)
{
	if (path == cue.attemptedPath) return;
	cue.attemptedPath = path;
	cue.lastLoadSucceeded = false;
	Sound *replacement = engine->getResourceManager()->loadSound(path, "");
	if (replacement == NULL || !replacement->isReady())
	{
		OsuTimingAudioView::CueStatus status;
		cue.selected(path, osu_timing_audio_retain_failed_cue.getBool(), &status);
		debugLog("TimingAudio: couldn't load sounds/%s; %s. Retry after fixing the file.\n", path.toUtf8(), status.reason);
		if (replacement != NULL) engine->getResourceManager()->destroyResource(replacement);
		return;
	}
	replacement->setOverlayable(true);
	if (cue.sound != NULL) engine->getResourceManager()->destroyResource(cue.sound);
	cue.sound = replacement;
	cue.loadedPath = path;
	cue.lastLoadSucceeded = true;
	if (osu_timing_audio_trace.getBool()) debugLog("TimingAudio: loaded cue sounds/%s\n", path.toUtf8());
}

void OsuTimingAudioFeedback::pause()
{
	suspendPlayClock();
	if (m_enabled) m_state.pause(osu_timing_audio_restart.getBool());
}

void OsuTimingAudioFeedback::suspendPlayClock()
{
	m_playClock.advance(engine->getTime(), false);
}

bool OsuTimingAudioFeedback::needsActivities(const OsuTimingAudioState::Config &config, bool excludeActivity) const
{
	return !m_prepared || excludeActivity != m_excludeActivity || config.breakSeconds != m_breakSeconds;
}

OsuTimingAudioEvaluation OsuTimingAudioFeedback::getLastEvaluation() const
{
	if (!osu_timing_audio.getBool())
	{
		OsuTimingAudioEvaluation evaluation;
		evaluation.phase = OsuTimingAudioEvaluation::OFF;
		return evaluation;
	}
	auto evaluation = m_state.getLastEvaluation();
	if (evaluation.phase != OsuTimingAudioEvaluation::WAITING) evaluation.output = m_lastOutput;
	return evaluation;
}

OsuTimingAudioView OsuTimingAudioFeedback::getCurrentView(OsuTimingAudioView::Mode mode, double recentSeconds, bool includeCueStatus) const
{
	OsuTimingAudioView view;
	view.mode = mode;
	if (!osu_timing_audio.getBool())
		view.evaluation.phase = OsuTimingAudioEvaluation::OFF;
	else if (m_prepared)
	{
		const auto inputs = timingAudioInputs(m_beatmap, 0);
		const auto config = timingAudioConfig();
		// Describe settings that will apply on resume without resetting the live learner.
		const bool pendingReset = m_state.wouldResetEstimator(config)
			|| needsActivities(config, osu_timing_audio_exclude_activity.getBool());
		view.playSeconds = m_playClock.seconds();
		view.learnerSeconds = pendingReset ? 0 : m_state.getActiveMS() / 1000;
		view.secondsSinceHit = pendingReset ? std::numeric_limits<double>::quiet_NaN() : m_state.secondsSinceAcceptedHit(view.playSeconds);
		view.pendingReset = pendingReset;
		view.lastHit = getLastEvaluation();
		view.evaluation = m_state.getCurrentEvaluation(inputs.window300, inputs.recent, inputs.targetMapMS(), config, pendingReset, &view.band, view.playSeconds);
		view.generation = m_state.getGeneration();
		view.bandMode = config.bandMode;
		view.speed = inputs.window300.speed;
		view.window300MapMS = inputs.window300.mapMS;
		if (mode == OsuTimingAudioView::RECENT_WINDOW)
			m_recentWindow.apply(view.evaluation, view.speed, view.playSeconds, recentSeconds);
		else if (!pendingReset && (mode == OsuTimingAudioView::NEXT_AT_AVERAGE || mode == OsuTimingAudioView::NEXT_AT_REFERENCE))
			m_state.projectNextHit(view.evaluation, view.speed, mode == OsuTimingAudioView::NEXT_AT_REFERENCE);
		if (timingAudioVolume() <= 0.0f || engine->getSound()->getVolume() <= 0.0f)
			view.evaluation.output = OsuTimingAudioEvaluation::MUTED;
		view.recentTruncated = m_recentWindow.truncated(view.playSeconds, recentSeconds);
		if (includeCueStatus)
		{
			const bool retain = osu_timing_audio_retain_failed_cue.getBool();
			m_early.selected(osu_timing_audio_early_sound.getString(), retain, &view.early);
			m_late.selected(osu_timing_audio_late_sound.getString(), retain, &view.late);
		}
	}
	return view;
}

void OsuTimingAudioFeedback::update()
{
	if (!osu_timing_audio.getBool())
	{
		if (m_enabled) reset();
		m_enabled = false;
		return;
	}
	const bool playing = m_beatmap->isPlaying() && !m_beatmap->isPaused()
		&& !m_beatmap->isContinueScheduled() && !m_beatmap->isLoading();
	m_playClock.advance(engine->getTime(), playing && !m_beatmap->isWaiting());
	if (!playing) return;
	m_enabled = true;

	const auto config = timingAudioConfig();
	m_state.configure(config, m_playClock.seconds());

	const bool excludeActivity = osu_timing_audio_exclude_activity.getBool();
	if (needsActivities(config, excludeActivity))
	{
		std::vector<OsuTimingAudioState::Activity> activities;
		for (OsuHitObject *object : m_beatmap->getHitObjectsPointer())
		{
			if (excludeActivity && !object->isCircle() && !object->isSlider()) continue;
			activities.push_back({(double)object->getTime(), (double)object->getTime() + (excludeActivity ? 0.0 : (double)object->getDuration())});
		}
		m_state.setActivities(activities);
		m_excludeActivity = excludeActivity;
		m_breakSeconds = config.breakSeconds;
		m_prepared = true;
	}

	// Separately owned samples; explicit file changes never reset the estimator.
	loadCue(m_early, osu_timing_audio_early_sound.getString());
	loadCue(m_late, osu_timing_audio_late_sound.getString());
	m_state.advance(m_beatmap->getCurMusicPosWithOffsets(), m_beatmap->getSpeedMultiplier());
}

void OsuTimingAudioFeedback::onManualHit(long opportunityMS, long delta)
{
	if (!osu_timing_audio.getBool()) return;
	Osu *osu = m_beatmap->getOsu();
	if (osu->getModAuto() || osu->getModRelax() || osu->getModAutopilot() || osu->isInVRMode() || osu->getInstanceID() > 0) return;
	update();
	if (!m_enabled || !m_prepared || m_beatmap->isPaused() || m_beatmap->isContinueScheduled()) return;
	const auto inputs = timingAudioInputs(m_beatmap, delta);
	const double playSeconds = m_playClock.seconds();
	const auto result = m_state.sampleMap(delta, inputs.window300, inputs.recent, opportunityMS, inputs.targetMapMS(), playSeconds);
	if (!result.accepted)
	{
		m_lastOutput = OsuTimingAudioEvaluation::NO_ISSUE;
		return;
	}
	m_recentWindow.recordAcceptedHit(playSeconds, static_cast<double>(delta) / inputs.window300.speed);
	const float volume = timingAudioVolume();
	bool played = false;
	Sound *sound = NULL;
	if (result.cue != OsuTimingAudioState::SILENT && volume > 0.0f)
	{
		const bool early = result.cue == OsuTimingAudioState::EARLY;
		sound = (early ? m_early : m_late).selected((early ? osu_timing_audio_early_sound : osu_timing_audio_late_sound).getString(),
			osu_timing_audio_retain_failed_cue.getBool());
		if (sound != NULL)
		{
			sound->setVolume(volume);
			played = engine->getSound()->play(sound);
		}
	}
	// Report the last hit's output status without changing the playback request.
	if (volume <= 0.0f || engine->getSound()->getVolume() <= 0.0f)
		m_lastOutput = OsuTimingAudioEvaluation::MUTED;
	else if (result.cue != OsuTimingAudioState::SILENT && !played)
		m_lastOutput = sound == NULL ? OsuTimingAudioEvaluation::CUE_UNAVAILABLE : OsuTimingAudioEvaluation::PLAY_FAILED;
	else
		m_lastOutput = played ? OsuTimingAudioEvaluation::PLAYED : OsuTimingAudioEvaluation::NO_ISSUE;
	if (osu_timing_audio_trace.getBool())
		debugLog("TimingAudio: map=%ld error=%.3f baseline=%.3f deviation=%.3f preceding=%llu cue=%i played=%i gain=%.3f target_units=%.3f target_ms=%.3f target_valid=%i halfwidth=%.6f variance=%.6f fallback=%i\n", m_beatmap->getCurMusicPosWithOffsets(), (double)delta / inputs.window300.speed, result.baselineMS, result.deviationMS, result.precedingSamples, (int)result.cue, (int)played, volume, (double)inputs.target, inputs.reference.targetMS, (int)inputs.reference.valid, result.halfWidthMS, result.varianceMS2, (int)result.fixedFallback);
}

#include "OsuTimingAudioFeedback.h"

#include "Engine.h"
#include "ConVar.h"
#include "ResourceManager.h"
#include "SoundEngine.h"
#include "Osu.h"
#include "OsuBeatmap.h"
#include "OsuGameRules.h"
#include "OsuHitObject.h"

ConVar osu_timing_audio("osu_timing_audio", false, FCVAR_NONE, "Opt-in timing audio experiment for manual circles and slider heads.");
ConVar osu_timing_audio_recent("osu_timing_audio_recent", true, FCVAR_NONE, "Recent timing reference; false selects beatmap timing. Switching preserves the baseline.");
ConVar osu_timing_audio_fixed_hits("osu_timing_audio_fixed_hits", false, FCVAR_NONE, "Use hit-count EMA instead of active-play-time EMA.");
ConVar osu_timing_audio_half_life_seconds("osu_timing_audio_half_life_seconds", 5.0f, FCVAR_NONE);
ConVar osu_timing_audio_half_life_hits("osu_timing_audio_half_life_hits", 16.0f, FCVAR_NONE);
ConVar osu_timing_audio_silent_startup("osu_timing_audio_silent_startup", false, FCVAR_NONE, "Mute first eight eligible hits; otherwise recent feedback starts at hit two.");
ConVar osu_timing_audio_require_300("osu_timing_audio_require_300", false, FCVAR_NONE, "Mute BOTH references unless the preceding baseline exists and is inside the current 300 window. Muted hits still update.");
ConVar osu_timing_audio_restart("osu_timing_audio_restart", false, FCVAR_NONE, "Restart startup after qualifying breaks; false retains the baseline.");
ConVar osu_timing_audio_exclude_activity("osu_timing_audio_exclude_activity", false, FCVAR_NONE, "Also treat long slider-body/spinner spans without circle/head opportunities as breaks.");
ConVar osu_timing_audio_break_seconds("osu_timing_audio_break_seconds", 3.0f, FCVAR_NONE, "Real-play seconds; exclude the entire qualifying break from EMA time.");
ConVar osu_timing_audio_deadzone("osu_timing_audio_deadzone", 10.0f, FCVAR_NONE, "Silent +/- dead zone in real-play milliseconds.");
ConVar osu_timing_audio_volume("osu_timing_audio_volume", 0.2f, FCVAR_NONE, "Cue gain, multiplied by effects and master volume. Zero mutes while learning.");
ConVar osu_timing_audio_trace("osu_timing_audio_trace", false, FCVAR_NONE, "Log preceding baseline, error, output and actual playback success; diagnostic overhead only when enabled.");
extern ConVar osu_volume_effects;

static double timingAudioValue(float value, double fallback, double minimum, double maximum)
{
	return std::isfinite(value) ? std::max(minimum, std::min(maximum, (double)value)) : fallback;
}

OsuTimingAudioFeedback::OsuTimingAudioFeedback(OsuBeatmap *beatmap) : m_beatmap(beatmap), m_early(NULL), m_late(NULL), m_enabled(false), m_prepared(false), m_excludeActivity(false), m_breakSeconds(3.0)
{
}

OsuTimingAudioFeedback::~OsuTimingAudioFeedback()
{
	if (m_early != NULL) engine->getResourceManager()->destroyResource(m_early);
	if (m_late != NULL) engine->getResourceManager()->destroyResource(m_late);
}

void OsuTimingAudioFeedback::reset()
{
	m_state.reset();
	m_prepared = false;
}

void OsuTimingAudioFeedback::pause()
{
	if (m_enabled && osu_timing_audio_restart.getBool()) reset();
	// Retain uses the music-position clock, which excludes the manual pause.
}

void OsuTimingAudioFeedback::update()
{
	if (!osu_timing_audio.getBool())
	{
		if (m_enabled) reset();
		m_enabled = false;
		return;
	}
	if (!m_beatmap->isPlaying() || m_beatmap->isPaused() || m_beatmap->isWaiting() || m_beatmap->isContinueScheduled()) return;
	m_enabled = true;

	OsuTimingAudioState::Config config;
	config.fixedHits = osu_timing_audio_fixed_hits.getBool();
	config.halfLifeSeconds = timingAudioValue(osu_timing_audio_half_life_seconds.getFloat(), 5.0, 0.001, 3600.0);
	config.halfLifeHits = timingAudioValue(osu_timing_audio_half_life_hits.getFloat(), 16.0, 0.001, 100000.0);
	config.breakSeconds = timingAudioValue(osu_timing_audio_break_seconds.getFloat(), 3.0, 0.001, 3600.0);
	config.deadZoneMS = timingAudioValue(osu_timing_audio_deadzone.getFloat(), 10.0, 0.0, 1000.0);
	config.silentStartup = osu_timing_audio_silent_startup.getBool();
	config.require300 = osu_timing_audio_require_300.getBool();
	config.restartAfterBreak = osu_timing_audio_restart.getBool();
	m_state.configure(config);

	const bool excludeActivity = osu_timing_audio_exclude_activity.getBool();
	if (!m_prepared || excludeActivity != m_excludeActivity || config.breakSeconds != m_breakSeconds)
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

	// Immutable, separately owned samples: no changes to song/hitsound voices.
	if (m_early == NULL)
	{
		m_early = engine->getResourceManager()->loadSound("timing-early.wav", "");
		m_late = engine->getResourceManager()->loadSound("timing-late.wav", "");
		m_early->setOverlayable(true);
		m_late->setOverlayable(true);
	}
	m_state.advance(m_beatmap->getCurMusicPosWithOffsets(), m_beatmap->getSpeedMultiplier());
}

void OsuTimingAudioFeedback::onManualHit(long delta)
{
	if (!osu_timing_audio.getBool()) return;
	Osu *osu = m_beatmap->getOsu();
	if (osu->getModAuto() || osu->getModRelax() || osu->getModAutopilot() || osu->isInVRMode() || osu->getInstanceID() > 0) return;
	update();
	if (!m_enabled || !m_prepared || m_beatmap->isPaused() || m_beatmap->isContinueScheduled()) return;
	const double speed = m_beatmap->getSpeedMultiplier();
	const auto result = m_state.sample((double)delta / speed, (long)OsuGameRules::getHitWindow300(m_beatmap) / speed, osu_timing_audio_recent.getBool());
	const float volume = timingAudioValue(osu_timing_audio_volume.getFloat(), 0.2, 0.0, 1.0) * osu_volume_effects.getFloat();
	bool played = false;
	if (result.cue != OsuTimingAudioState::SILENT && volume > 0.0f)
	{
		Sound *sound = result.cue == OsuTimingAudioState::EARLY ? m_early : m_late;
		sound->setVolume(volume);
		played = engine->getSound()->play(sound);
	}
	if (osu_timing_audio_trace.getBool())
		debugLog("TimingAudio: map=%ld error=%.3f baseline=%.3f deviation=%.3f preceding=%llu cue=%i played=%i\n", m_beatmap->getCurMusicPosWithOffsets(), (double)delta / speed, result.baselineMS, result.deviationMS, result.precedingSamples, (int)result.cue, (int)played);
}

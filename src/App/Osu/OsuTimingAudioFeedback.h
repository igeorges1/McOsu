#ifndef OSUTIMINGAUDIOFEEDBACK_H
#define OSUTIMINGAUDIOFEEDBACK_H

#include "OsuTimingAudioState.h"
#include "UString.h"

class OsuBeatmap;
class Sound;

class OsuTimingAudioFeedback
{
public:
	explicit OsuTimingAudioFeedback(OsuBeatmap *beatmap);
	~OsuTimingAudioFeedback();
	void update();
	void reset();
	void reloadSounds();
	void pause();
	void onManualHit(long opportunityMS, long delta);
	OsuTimingAudioEvaluation getLastEvaluation() const;

private:
	void loadCue(Sound *&sound, UString &attemptedPath, const UString &path);
	OsuBeatmap *m_beatmap;
	OsuTimingAudioState m_state;
	Sound *m_early, *m_late;
	UString m_earlyPath, m_latePath;
	bool m_enabled, m_prepared, m_excludeActivity;
	bool m_mutedAtLastHit = false;
	double m_breakSeconds;
};

#endif

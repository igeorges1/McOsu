#ifndef OSUTIMINGAUDIOFEEDBACK_H
#define OSUTIMINGAUDIOFEEDBACK_H

#include "OsuTimingAudioState.h"

class OsuBeatmap;
class Sound;

class OsuTimingAudioFeedback
{
public:
	explicit OsuTimingAudioFeedback(OsuBeatmap *beatmap);
	~OsuTimingAudioFeedback();
	void update();
	void reset();
	void pause();
	void onManualHit(long opportunityMS, long delta);

private:
	OsuBeatmap *m_beatmap;
	OsuTimingAudioState m_state;
	Sound *m_early, *m_late;
	bool m_enabled, m_prepared, m_excludeActivity;
	double m_breakSeconds;
};

#endif

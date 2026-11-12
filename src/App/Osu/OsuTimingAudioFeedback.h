#ifndef OSUTIMINGAUDIOFEEDBACK_H
#define OSUTIMINGAUDIOFEEDBACK_H

#include "OsuTimingAudioState.h"
#include "OsuTimingAudioRecentWindow.h"
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
	void suspendRecentWindow();
	void onManualHit(long opportunityMS, long delta);
	OsuTimingAudioEvaluation getLastEvaluation() const;
	OsuTimingAudioView getCurrentView(OsuTimingAudioView::Mode mode) const;

private:
	bool needsActivities(const OsuTimingAudioState::Config &config, bool excludeActivity) const;
	void loadCue(Sound *&sound, UString &attemptedPath, const UString &path);
	OsuBeatmap *m_beatmap;
	OsuTimingAudioState m_state;
	OsuTimingAudioRecentWindow m_recentWindow;
	Sound *m_early, *m_late;
	UString m_earlyPath, m_latePath;
	bool m_enabled, m_prepared, m_excludeActivity;
	OsuTimingAudioEvaluation::Output m_lastOutput = OsuTimingAudioEvaluation::NO_ISSUE;
	double m_breakSeconds;
};

#endif

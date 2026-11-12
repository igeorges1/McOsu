#ifndef OSUTIMINGAUDIOFEEDBACK_H
#define OSUTIMINGAUDIOFEEDBACK_H

#include "OsuTimingAudioState.h"
#include "OsuTimingAudioRecentWindow.h"
#include "OsuTimingAudioPlayClock.h"
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
	void suspendPlayClock();
	void onManualHit(long opportunityMS, long delta);
	OsuTimingAudioEvaluation getLastEvaluation() const;
	OsuTimingAudioView getCurrentView(OsuTimingAudioView::Mode mode, double recentSeconds = 5, bool includeCueStatus = false) const;

private:
	bool needsActivities(const OsuTimingAudioState::Config &config, bool excludeActivity) const;
	struct Cue
	{
		Sound *sound = NULL;
		UString loadedPath, attemptedPath;
		bool lastLoadSucceeded = false;
		Sound *selected(const UString &requested, bool retain, OsuTimingAudioView::CueStatus *status = NULL) const;
	};
	void loadCue(Cue &cue, const UString &path);
	OsuBeatmap *m_beatmap;
	OsuTimingAudioState m_state;
	OsuTimingAudioRecentWindow m_recentWindow;
	OsuTimingAudioPlayClock m_playClock;
	Cue m_early, m_late;
	bool m_enabled, m_prepared, m_excludeActivity;
	OsuTimingAudioEvaluation::Output m_lastOutput = OsuTimingAudioEvaluation::NO_ISSUE;
	double m_breakSeconds;
};

#endif

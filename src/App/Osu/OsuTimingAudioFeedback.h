#ifndef OSUTIMINGAUDIOFEEDBACK_H
#define OSUTIMINGAUDIOFEEDBACK_H

#include "OsuTimingAudioState.h"
#include "OsuTimingAudioRecentWindow.h"
#include "OsuTimingAudioPlayClock.h"
#include "OsuTimingAudioCapture.h"
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
	bool writeCapture(std::ostream &out, const std::string &source, const std::string &map,
		const std::string &metadata, double recentSeconds, bool &sufficient);
	bool snapshotCapture(OsuTimingAudioCapture &snapshot, double recentSeconds);
	void captureSkip();
	unsigned long long captureEpoch() const { return m_captureEpoch; }

private:
	bool needsActivities(const OsuTimingAudioState::Config &config, bool excludeActivity) const;
	void syncCapture();
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
	OsuTimingAudioCapture m_capture;
	bool m_captureFromReset = true;
	unsigned long long m_captureEpoch = 0;
	Cue m_early, m_late;
	bool m_enabled, m_prepared, m_excludeActivity;
	OsuTimingAudioEvaluation::Output m_lastOutput = OsuTimingAudioEvaluation::NO_ISSUE;
	double m_breakSeconds;
};

#endif

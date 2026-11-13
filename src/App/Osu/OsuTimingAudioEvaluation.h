#ifndef OSUTIMINGAUDIOEVALUATION_H
#define OSUTIMINGAUDIOEVALUATION_H

#include <limits>
#include <cmath>
#include <string>

// Cue geometry in map ms, at the playback rate used to evaluate it.
// The state exposes both a live view and the frozen pre-update hit evaluation.
struct OsuTimingAudioEvaluation
{
	enum Phase { OFF, WAITING, INVALID, WARMUP, GATED, ACTIVE };
	enum Output { NO_ISSUE, MUTED, CUE_UNAVAILABLE, PLAY_FAILED, PLAYED, AUDIO_DISABLED };
	struct Range
	{
		double lower = std::numeric_limits<double>::quiet_NaN();
		double upper = std::numeric_limits<double>::quiet_NaN();
		Range() = default;
		Range(double lower, double upper) : lower(lower), upper(upper) {}
	};

	Phase phase = WAITING;
	bool recent = false;
	bool fixedFallback = false;
	Output output = NO_ISSUE;
	int classifiedCue = 0; // -1 early, +1 late
	double excessMS = 0;
	double requestedPan = std::numeric_limits<double>::quiet_NaN();
	// NaN marks geometry that was unavailable for the evaluation.
	double referenceMapMS = std::numeric_limits<double>::quiet_NaN();
	double learnedMeanMapMS = std::numeric_limits<double>::quiet_NaN();
	Range spreadMapMS; // learned mean +/- one population standard deviation
	Range silentMapMS; // inclusive cue interval when the timing gate permits cues

	void setStatistics(unsigned long long count, double meanMS, double varianceMS2, double speed)
	{
		const double unavailable = std::numeric_limits<double>::quiet_NaN();
		learnedMeanMapMS = count > 0 ? meanMS * speed : unavailable;
		spreadMapMS = Range();
		if (count >= 2 && std::isfinite(varianceMS2) && varianceMS2 >= 0.0)
		{
			const double spread = std::sqrt(varianceMS2) * speed;
			spreadMapMS = {learnedMeanMapMS - spread, learnedMeanMapMS + spread};
		}
	}
};

struct OsuTimingAudioView
{
	struct CueStatus
	{
		std::string activeFile;
		const char *reason = "not prepared";
	};
	struct BandStatus
	{
		enum Limit { NONE, MINIMUM, MAXIMUM };
		double baseHalfWidthMS = std::numeric_limits<double>::quiet_NaN();
		double resolvedHalfWidthMS = std::numeric_limits<double>::quiet_NaN();
		double ordinaryHalfWidthMS = std::numeric_limits<double>::quiet_NaN();
		double maximumHalfWidthMS = std::numeric_limits<double>::quiet_NaN();
		double allowance = 0;
		unsigned long long learnedHits = 0;
		Limit limit = NONE;
		bool idleActive = false, startupMaximum = false;
	};

	enum Mode { AUDIO_ESTIMATE, RECENT_WINDOW, NEXT_AT_AVERAGE, NEXT_AT_REFERENCE, MODE_COUNT };
	static Mode fromSetting(int setting)
	{
		return setting >= 0 && setting < MODE_COUNT ? static_cast<Mode>(setting) : AUDIO_ESTIMATE;
	}
	static const char *name(Mode mode)
	{
		switch (mode)
		{
		case RECENT_WINDOW: return "Recent window";
		case NEXT_AT_AVERAGE: return "Projected at average";
		case NEXT_AT_REFERENCE: return "Projected at reference";
		default: return "Audio estimate";
		}
	}

	OsuTimingAudioEvaluation evaluation;
	OsuTimingAudioEvaluation lastHit;
	BandStatus band;
	unsigned long long generation = 0;
	int bandMode = 0;
	Mode mode = AUDIO_ESTIMATE;
	double speed = 0;
	double window300MapMS = 0;
	double playSeconds = 0, learnerSeconds = 0;
	double secondsSinceHit = std::numeric_limits<double>::quiet_NaN();
	bool pendingReset = false;
	bool recentTruncated = false;
	CueStatus early, late;
};

#endif

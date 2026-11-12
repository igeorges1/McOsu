#ifndef OSUTIMINGAUDIOEVALUATION_H
#define OSUTIMINGAUDIOEVALUATION_H

#include <limits>
#include <cmath>

// Cue geometry in map ms, at the playback rate used to evaluate it.
// The state exposes both a live view and the frozen pre-update hit evaluation.
struct OsuTimingAudioEvaluation
{
	enum Phase { OFF, WAITING, INVALID, WARMUP, GATED, ACTIVE };
	enum Output { NO_ISSUE, MUTED, CUE_UNAVAILABLE };
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
	struct BandStatus
	{
		enum Limit { NONE, MINIMUM, MAXIMUM };
		double baseHalfWidthMS = std::numeric_limits<double>::quiet_NaN();
		double resolvedHalfWidthMS = std::numeric_limits<double>::quiet_NaN();
		unsigned long long learnedHits = 0;
		Limit limit = NONE;
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
		case RECENT_WINDOW: return "Recent window (5s)";
		case NEXT_AT_AVERAGE: return "Projected at average";
		case NEXT_AT_REFERENCE: return "Projected at reference";
		default: return "Audio estimate";
		}
	}

	OsuTimingAudioEvaluation evaluation;
	BandStatus band;
	unsigned long long generation = 0;
	int bandMode = 0;
	Mode mode = AUDIO_ESTIMATE;
	double speed = 0;
	double window300MapMS = 0;
};

#endif

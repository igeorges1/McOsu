#ifndef OSUTIMINGAUDIOEVALUATION_H
#define OSUTIMINGAUDIOEVALUATION_H

#include <limits>

// The latest eligible hit's pre-update evaluation. Coordinates are map ms,
// projected at the hit's playback rate so they line up with hit-error ticks.
struct OsuTimingAudioEvaluation
{
	enum Phase { OFF, WAITING, INVALID, WARMUP, GATED, ACTIVE };
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
	bool muted = false;
	// NaN marks geometry that was unavailable for the evaluation.
	double referenceMapMS = std::numeric_limits<double>::quiet_NaN();
	Range spreadMapMS; // learned mean +/- one preceding population standard deviation
	Range silentMapMS; // inclusive cue interval, available only when classification ran
};

#endif

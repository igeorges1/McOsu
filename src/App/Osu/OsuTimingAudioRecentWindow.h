#ifndef OSUTIMINGAUDIORECENTWINDOW_H
#define OSUTIMINGAUDIORECENTWINDOW_H

#include "OsuTimingAudioEvaluation.h"
#include <cmath>
#include <cstddef>
#include <deque>

// HUD history on the shared counted-play clock. Retain up to 2048 entries so
// expanding the selected duration can reveal older retained observations.
class OsuTimingAudioRecentWindow
{
public:
	struct Moments
	{
		std::size_t count = 0;
		double meanMS = 0;
		double varianceMS2 = 0;
	};

	void reset()
	{
		m_entries.clear();
		m_lastDropped = std::numeric_limits<double>::quiet_NaN();
	}

	void recordAcceptedHit(double playSeconds, double errorMS)
	{
		// Accepted pre-roll hits share the playback start timestamp.
		if (!std::isfinite(playSeconds) || !std::isfinite(errorMS)) return;
		if (m_entries.size() == 2048)
		{
			m_lastDropped = m_entries.front().at;
			m_entries.pop_front();
		}
		m_entries.push_back({playSeconds, errorMS});
	}

	bool truncated(double playSeconds, double duration) const { return playSeconds - m_lastDropped < duration; }

	Moments getMoments(double playSeconds, double duration) const
	{
		Moments result;
		double sumSquared = 0;
		for (const Entry &entry : m_entries)
		{
			if (playSeconds - entry.at >= duration) continue;
			const double delta = entry.errorMS - result.meanMS;
			result.meanMS += delta / ++result.count;
			sumSquared += delta * (entry.errorMS - result.meanMS);
		}
		if (result.count > 0) result.varianceMS2 = sumSquared / result.count;
		return result;
	}

	void apply(OsuTimingAudioEvaluation &evaluation, double speed, double playSeconds, double duration) const
	{
		if (evaluation.phase == OsuTimingAudioEvaluation::INVALID) return;
		const auto moments = getMoments(playSeconds, duration);
		evaluation.setStatistics(moments.count, moments.meanMS, moments.varianceMS2, speed);
	}

private:
	struct Entry { double at, errorMS; };
	std::deque<Entry> m_entries;
	double m_lastDropped = std::numeric_limits<double>::quiet_NaN();
};

#endif

#ifndef OSUTIMINGAUDIORECENTWINDOW_H
#define OSUTIMINGAUDIORECENTWINDOW_H

#include "OsuTimingAudioEvaluation.h"
#include <cmath>
#include <cstddef>
#include <deque>

// HUD diagnostics only. The clock counts unpaused playback, including map
// breaks, independently of the audio estimator's corrected active clock.
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
		m_playSeconds = 0;
		m_haveTime = m_playing = false;
	}

	void advance(double nowSeconds, bool playing)
	{
		if (!std::isfinite(nowSeconds))
		{
			m_haveTime = m_playing = false;
			return;
		}
		if (m_haveTime && m_playing && playing && nowSeconds >= m_lastSeconds)
			m_playSeconds += nowSeconds - m_lastSeconds;
		m_lastSeconds = nowSeconds;
		m_haveTime = true;
		m_playing = playing;
		while (!m_entries.empty() && m_playSeconds - m_entries.front().at >= 5.0)
			m_entries.pop_front();
	}

	void recordAcceptedHit(double errorMS)
	{
		// Accepted pre-roll hits share the playback start timestamp.
		if (!std::isfinite(errorMS)) return;
		if (m_entries.size() == 2048) m_entries.pop_front();
		m_entries.push_back({m_playSeconds, errorMS});
	}

	Moments getMoments() const
	{
		Moments result;
		double sumSquared = 0;
		for (const Entry &entry : m_entries)
		{
			const double delta = entry.errorMS - result.meanMS;
			result.meanMS += delta / ++result.count;
			sumSquared += delta * (entry.errorMS - result.meanMS);
		}
		if (result.count > 0) result.varianceMS2 = sumSquared / result.count;
		return result;
	}

	void apply(OsuTimingAudioEvaluation &evaluation, double speed) const
	{
		if (evaluation.phase == OsuTimingAudioEvaluation::INVALID) return;
		const auto moments = getMoments();
		evaluation.setStatistics(moments.count, moments.meanMS, moments.varianceMS2, speed);
	}

private:
	struct Entry { double at, errorMS; };
	std::deque<Entry> m_entries;
	double m_lastSeconds = 0, m_playSeconds = 0;
	bool m_haveTime = false, m_playing = false;
};

#endif

// Timing-audio experiment: deterministic estimation and scheduled-rest handling.
#ifndef OSUTIMINGAUDIOSTATE_H
#define OSUTIMINGAUDIOSTATE_H

#include <algorithm>
#include <cmath>
#include <vector>

class OsuTimingAudioState
{
public:
	struct Config
	{
		bool fixedHits = false;
		double halfLifeSeconds = 5.0;
		double halfLifeHits = 16.0;
		double breakSeconds = 3.0;
		double deadZoneMS = 10.0;
		bool silentStartup = false;
		bool require300 = false;
		bool restartAfterBreak = false;
	};

	struct Activity { double startMS, endMS; };
	enum Cue { EARLY = -1, SILENT = 0, LATE = 1 };
	struct Result
	{
		Cue cue;
		double baselineMS;
		double deviationMS;
		unsigned long long precedingSamples;
	};

	OsuTimingAudioState() { reset(); }

	void configure(const Config &config)
	{
		const bool changedEstimator = config.fixedHits != m_config.fixedHits
			|| config.halfLifeSeconds != m_config.halfLifeSeconds || config.halfLifeHits != m_config.halfLifeHits;
		m_config = config;
		if (changedEstimator) reset();
	}

	// Activities are scheduled objects, independent of successful judgements.
	// The adapter includes bodies/spinners only when the activity toggle is off.
	void setActivities(std::vector<Activity> activities)
	{
		std::sort(activities.begin(), activities.end(), [](const Activity &a, const Activity &b) { return a.startMS < b.startMS; });
		m_gaps.clear();
		if (!activities.empty())
		{
			double end = activities.front().endMS;
			for (size_t i = 1; i < activities.size(); ++i)
			{
				if (activities[i].startMS > end) m_gaps.push_back({end, activities[i].startMS});
				end = std::max(end, activities[i].endMS);
			}
		}
		reset();
	}

	void reset()
	{
		m_activeMS = 0.0;
		restartBaseline();
		m_lastMapMS = 0.0;
		m_havePosition = false;
		m_gapIndex = 0;
		m_gapElapsedMS = 0.0;
		m_gapQualified = false;
	}

	void pause()
	{
		if (m_config.restartAfterBreak) restartBaseline();
		// Music-position time does not advance while paused or waiting to continue.
	}

	void advance(double mapMS, double speed)
	{
		if (!std::isfinite(mapMS) || !std::isfinite(speed) || speed <= 0.0) return;
		if (m_havePosition && mapMS < m_lastMapMS) reset();
		if (!m_havePosition)
		{
			m_lastMapMS = mapMS;
			m_havePosition = true;
			while (m_gapIndex < m_gaps.size() && m_gaps[m_gapIndex].endMS <= mapMS) ++m_gapIndex;
			return;
		}

		double position = m_lastMapMS;
		while (m_gapIndex < m_gaps.size() && position < mapMS)
		{
			const Activity &gap = m_gaps[m_gapIndex];
			if (position < gap.startMS)
			{
				const double end = std::min(mapMS, gap.startMS);
				m_activeMS += (end - position) / speed;
				position = end;
			}
			if (position >= mapMS) break;
			const double end = std::min(mapMS, gap.endMS);
			const double elapsed = std::max(0.0, end - position) / speed;
			m_gapElapsedMS += elapsed;
			if (!m_gapQualified)
			{
				m_activeMS += elapsed;
				if (m_gapElapsedMS + 0.000001 >= m_config.breakSeconds * 1000.0)
				{
					// Remove the WHOLE gap, including time before its threshold.
					m_activeMS -= m_gapElapsedMS;
					m_lastSampleMS = std::min(m_lastSampleMS, m_activeMS);
					m_gapQualified = true;
					if (m_config.restartAfterBreak) restartBaseline();
				}
			}
			position = end;
			if (position >= gap.endMS)
			{
				++m_gapIndex;
				m_gapElapsedMS = 0.0;
				m_gapQualified = false;
			}
		}
		m_activeMS += std::max(0.0, mapMS - position) / speed;
		m_lastMapMS = mapMS;
	}

	Result sample(double errorMS, double window300MS, bool recent)
	{
		Result result = {SILENT, m_baselineMS, recent ? errorMS - m_baselineMS : errorMS, m_samples};
		if (!std::isfinite(errorMS) || !std::isfinite(window300MS) || window300MS < 0.0) return result;
		const bool ready = !recent || (m_samples > 0 && (!m_config.silentStartup || m_samples >= 8));
		const bool inside300 = !m_config.require300 || (m_samples > 0 && std::abs(m_baselineMS) <= window300MS);
		if (ready && inside300)
		{
			if (result.deviationMS < -m_config.deadZoneMS) result.cue = EARLY;
			else if (result.deviationMS > m_config.deadZoneMS) result.cue = LATE;
		}

		if (m_samples < 8)
			m_baselineMS += (errorMS - m_baselineMS) / (double)(m_samples + 1);
		else
		{
			const double elapsed = m_config.fixedHits ? 1.0 : std::max(0.0, m_activeMS - m_lastSampleMS) / 1000.0;
			const double halfLife = m_config.fixedHits ? m_config.halfLifeHits : m_config.halfLifeSeconds;
			const double alpha = -std::expm1(-std::log(2.0) * elapsed / halfLife);
			m_baselineMS += alpha * (errorMS - m_baselineMS);
		}
		++m_samples;
		m_lastSampleMS = m_activeMS;
		return result;
	}

	double getBaselineMS() const { return m_baselineMS; }
	double getActiveMS() const { return m_activeMS; }
	unsigned long long getSamples() const { return m_samples; }

private:
	void restartBaseline() { m_baselineMS = 0.0; m_samples = 0; m_lastSampleMS = m_activeMS; }
	Config m_config;
	std::vector<Activity> m_gaps;
	double m_baselineMS, m_activeMS, m_lastSampleMS, m_lastMapMS, m_gapElapsedMS;
	unsigned long long m_samples;
	size_t m_gapIndex;
	bool m_havePosition, m_gapQualified;
};

#endif

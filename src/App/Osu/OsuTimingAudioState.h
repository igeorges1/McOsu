// Timing-audio experiment: deterministic estimation and scheduled-rest handling.
#ifndef OSUTIMINGAUDIOSTATE_H
#define OSUTIMINGAUDIOSTATE_H

#include <algorithm>
#include <cmath>
#include <limits>
#include <vector>

class OsuTimingAudioState
{
public:
	enum BandMode { FIXED_MS = 0, RELATIVE_300 = 1, ADAPTIVE_SPREAD = 2 };
	struct Config
	{
		bool fixedHits = false;
		double halfLifeSeconds = 5.0;
		double halfLifeHits = 16.0;
		double breakSeconds = 3.0;
		double deadZoneMS = 10.0;
		BandMode bandMode = FIXED_MS;
		double relativeFraction = 0.2;
		double adaptiveScale = 1.0;
		double adaptiveMinFraction = 0.1;
		double adaptiveMaxFraction = 1.0;
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
		double halfWidthMS;
		double varianceMS2; // preceding population variance, before this hit
		bool fixedFallback;
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
		m_speed = 1.0;
	}

	void pause(bool restart)
	{
		if (restart) restartBaseline();
		// Music-position time does not advance during the manual pause.
	}

	void advance(double mapMS, double speed)
	{
		if (!std::isfinite(mapMS) || !std::isfinite(speed) || speed <= 0.0) return;
		m_speed = speed;
		// Audio interpolation, pre-roll and pause/resume can correct time backward.
		// Explicit seeks/retries call reset(); a clock correction must not erase hits.
		if (m_havePosition && mapMS < m_lastMapMS) return;
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
					qualifyGap();
				}
			}
			position = end;
			if (position >= gap.endMS)
			{
				++m_gapIndex;
				m_gapElapsedMS = 0.0;
				m_gapQualified = false;
				m_haveGapCorrection = false;
			}
		}
		m_activeMS += std::max(0.0, mapMS - position) / speed;
		m_lastMapMS = mapMS;
	}

	Result sample(double errorMS, double window300MS, bool recent)
	{
		return sample(errorMS, window300MS, recent, m_lastMapMS);
	}

	Result sample(double errorMS, double window300MS, bool recent, double opportunityMS)
	{
		return sample(errorMS, window300MS, recent, opportunityMS, errorMS);
	}

	// The adapter computes shifted Beatmap deviation in map units before dividing
	// by rate. Original error remains the sole learning input in every mode.
	Result sample(double errorMS, double window300MS, bool recent, double opportunityMS, double beatmapDeviationMS)
	{
		// An accepted early hit belongs to the opportunity at the END of a gap.
		// Resolve its scheduled boundary before evaluating/updating this sample.
		if (std::isfinite(errorMS) && std::isfinite(window300MS) && window300MS >= 0.0
			&& m_havePosition && !m_gapQualified && m_gapIndex < m_gaps.size())
		{
			const Activity &gap = m_gaps[m_gapIndex];
			if (opportunityMS >= gap.endMS && m_lastMapMS >= gap.startMS && m_lastMapMS < gap.endMS
				&& m_gapElapsedMS + (gap.endMS - m_lastMapMS) / m_speed + 0.000001 >= m_config.breakSeconds * 1000.0)
				qualifyGap();
		}
		Result result = {SILENT, m_baselineMS, recent ? errorMS - m_baselineMS : beatmapDeviationMS,
			m_samples, m_config.deadZoneMS, m_varianceMS2, false};
		if (!std::isfinite(errorMS) || !std::isfinite(window300MS) || window300MS < 0.0) return result;
		// i686 x87 may keep a product's excess precision across an inline return.
		// Compare the stored double width exposed by Result, including its boundary.
		const volatile double halfWidthMS = bandHalfWidth(window300MS, result.fixedFallback);
		result.halfWidthMS = halfWidthMS;
		const bool ready = !recent || (m_samples > 0 && (!m_config.silentStartup || m_samples >= 8));
		const bool inside300 = !m_config.require300 || (m_samples > 0 && std::abs(m_baselineMS) <= window300MS);
		if (ready && inside300)
		{
			if (result.deviationMS < -result.halfWidthMS) result.cue = EARLY;
			else if (result.deviationMS > result.halfWidthMS) result.cue = LATE;
		}

		// A late departure may be judged after a rest has started but before its
		// duration qualifies. Keep the alternative with that pending gap removed;
		// commit it only if the gap qualifies, otherwise retain ordinary elapsed time.
		if (!m_config.fixedHits && !m_gapQualified && m_gapIndex < m_gaps.size()
			&& m_gapElapsedMS > 0.0 && opportunityMS <= m_gaps[m_gapIndex].startMS)
		{
			if (!m_haveGapCorrection)
			{
				m_gapBaselineMS = m_baselineMS;
				m_gapVarianceMS2 = m_varianceMS2;
				m_gapSampleClockMS = m_lastSampleMS;
				m_haveGapCorrection = true;
			}
			const double clock = m_activeMS - m_gapElapsedMS;
			m_gapBaselineMS = blend(m_gapBaselineMS, m_gapVarianceMS2, errorMS, clock - m_gapSampleClockMS);
			m_gapSampleClockMS = clock;
		}
		m_baselineMS = blend(m_baselineMS, m_varianceMS2, errorMS, m_activeMS - m_lastSampleMS);
		++m_samples;
		m_lastSampleMS = m_activeMS;
		return result;
	}

	double getBaselineMS() const { return m_baselineMS; }
	double getVarianceMS2() const { return m_varianceMS2; }
	double getActiveMS() const { return m_activeMS; }
	unsigned long long getSamples() const { return m_samples; }

private:
	double bandHalfWidth(double window300MS, bool &fallback) const
	{
		if (m_config.bandMode == FIXED_MS) return m_config.deadZoneMS;
		if (m_config.bandMode == RELATIVE_300)
		{
			const double width = m_config.relativeFraction * window300MS;
			if (std::isfinite(width) && width >= 0.0) return width;
		}
		else if (m_config.bandMode == ADAPTIVE_SPREAD && m_samples >= 2
			&& std::isfinite(m_varianceMS2) && m_varianceMS2 >= 0.0)
		{
			const double low = m_config.adaptiveMinFraction * window300MS;
			const double high = m_config.adaptiveMaxFraction * window300MS;
			const double width = m_config.adaptiveScale * std::sqrt(m_varianceMS2);
			if (std::isfinite(low) && std::isfinite(high) && std::isfinite(width)
				&& low >= 0.0 && high >= low && width >= 0.0)
				return std::max(low, std::min(high, width));
		}
		fallback = true;
		return m_config.deadZoneMS;
	}

	void blendVariance(double &variance, double mean, double error, double alpha) const
	{
		if (m_samples == 0 || alpha == 1.0) { variance = 0.0; return; }
		if (alpha == 0.0) return;
		const double delta = error - mean;
		const double next = (1.0 - alpha) * (variance + alpha * delta * delta);
		variance = std::isfinite(variance) && variance >= 0.0 && std::isfinite(next) && next >= 0.0
			? next : std::numeric_limits<double>::quiet_NaN();
	}

	double blend(double baselineMS, double &varianceMS2, double errorMS, double elapsedMS) const
	{
		if (m_samples < 8)
		{
			blendVariance(varianceMS2, baselineMS, errorMS, 1.0 / (double)(m_samples + 1));
			return baselineMS + (errorMS - baselineMS) / (double)(m_samples + 1);
		}
		const double elapsed = m_config.fixedHits ? 1.0 : std::max(0.0, elapsedMS) / 1000.0;
		const double halfLife = m_config.fixedHits ? m_config.halfLifeHits : m_config.halfLifeSeconds;
		const double coefficient = std::expm1(-std::log(2.0) * elapsed / halfLife);
		blendVariance(varianceMS2, baselineMS, errorMS, -coefficient);
		return baselineMS - coefficient * (errorMS - baselineMS);
	}
	void qualifyGap()
	{
		// Remove elapsed gap time; its remaining early-hit tail stays excluded.
		m_activeMS -= m_gapElapsedMS;
		if (m_haveGapCorrection)
		{
			m_baselineMS = m_gapBaselineMS;
			m_varianceMS2 = m_gapVarianceMS2;
			m_lastSampleMS = m_gapSampleClockMS;
			m_haveGapCorrection = false;
		}
		m_lastSampleMS = std::min(m_lastSampleMS, m_activeMS);
		m_gapQualified = true;
		if (m_config.restartAfterBreak) restartBaseline();
	}
	void restartBaseline() { m_baselineMS = 0.0; m_varianceMS2 = 0.0; m_samples = 0; m_lastSampleMS = m_activeMS; m_haveGapCorrection = false; }
	Config m_config;
	std::vector<Activity> m_gaps;
	double m_baselineMS, m_activeMS, m_lastSampleMS, m_lastMapMS, m_gapElapsedMS, m_speed;
	double m_gapBaselineMS, m_gapSampleClockMS;
	double m_varianceMS2, m_gapVarianceMS2;
	unsigned long long m_samples;
	size_t m_gapIndex;
	bool m_havePosition, m_gapQualified, m_haveGapCorrection;
};

#endif

// Timing-audio experiment: deterministic estimation and scheduled-rest handling.
#ifndef OSUTIMINGAUDIOSTATE_H
#define OSUTIMINGAUDIOSTATE_H

#include <algorithm>
#include <cmath>
#include <limits>
#include <vector>
#include "OsuTimingAudioEvaluation.h"
#include "OsuTimingAudioReference.h"

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
		long double relativeFraction = 0.2L;
		long double adaptiveScale = 1.0L;
		long double adaptiveMinFraction = 0.1L;
		long double adaptiveMaxFraction = 1.0L;
		bool silentStartup = false;
		bool require300 = false;
		bool restartAfterBreak = false;
	};

	struct Activity { double startMS, endMS; };
	struct Window { double mapMS, speed; }; // truncated map window, actual audio rate
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
		bool accepted;
	};

	OsuTimingAudioState() { reset(); }

	void configure(const Config &config)
	{
		const bool changedEstimator = wouldResetEstimator(config);
		m_config = config;
		if (changedEstimator) reset();
	}

	bool wouldResetEstimator(const Config &config) const
	{
		return config.fixedHits != m_config.fixedHits || config.halfLifeSeconds != m_config.halfLifeSeconds
			|| config.halfLifeHits != m_config.halfLifeHits;
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
		m_qualifiedGaps.assign(m_gaps.size(), false);
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
				m_gapQualified = m_gapIndex < m_qualifiedGaps.size() && m_qualifiedGaps[m_gapIndex];
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
		// Unshifted, already-converted inputs; the game uses sampleMap below.
		return sampleInternal(errorMS, Window{window300MS, 1.0}, recent, opportunityMS, errorMS, false, 0, 0);
	}

	// Production path retains the original hit and target for endpoint comparison.
	Result sampleMap(double errorMapMS, Window window, bool recent, double opportunityMS, long double targetMapMS)
	{
		const double errorMS = errorMapMS / window.speed;
		const double deviationMS = targetMapMS == 0 ? errorMS
			: OsuTimingAudioReference::stored((static_cast<long double>(errorMapMS) - OsuTimingAudioReference::stored(targetMapMS)) / window.speed);
		return sampleInternal(errorMS, window, recent, opportunityMS, deviationMS, true, errorMapMS, targetMapMS);
	}

	double getBaselineMS() const { return m_baselineMS; }
	double getVarianceMS2() const { return m_varianceMS2; }
	double getActiveMS() const { return m_activeMS; }
	unsigned long long getSamples() const { return m_samples; }
	const OsuTimingAudioEvaluation &getLastEvaluation() const { return m_lastEvaluation; }
	unsigned long long getGeneration() const { return m_generation; }

	OsuTimingAudioEvaluation getCurrentEvaluation(Window window, bool recent, long double targetMapMS) const
	{
		return getCurrentEvaluation(window, recent, targetMapMS, m_config, false);
	}

	OsuTimingAudioEvaluation getCurrentEvaluation(Window window, bool recent, long double targetMapMS,
		const Config &config, bool pendingReset) const
	{
		if (!std::isfinite(window.speed) || window.speed <= 0.0) return invalidEvaluation(recent);
		const volatile double window300MS = window.mapMS / window.speed;
		if (!std::isfinite(window300MS) || window300MS < 0.0) return invalidEvaluation(recent);

		Result current = {SILENT, pendingReset ? 0.0 : m_baselineMS, 0, pendingReset ? 0 : m_samples,
			0, pendingReset ? 0.0 : m_varianceMS2, false, false};
		long double mapHalfWidthMS = 0;
		const volatile double halfWidthMS = bandHalfWidth(window, config, current, mapHalfWidthMS);
		current.halfWidthMS = halfWidthMS;
		const auto evaluation = describeEvaluation(current, recent, isReady(config, recent, current.precedingSamples),
			isInside300(config, window300MS, current), window.speed, targetMapMS, mapHalfWidthMS);
		return evaluation.phase == OsuTimingAudioEvaluation::INVALID ? invalidEvaluation(recent) : evaluation;
	}

	void projectNextHit(OsuTimingAudioEvaluation &evaluation, double speed, bool atReference) const
	{
		// Hypothetical update of local scalars. Opportunity-based gap handling,
		// eligibility, judgement and cue playback still belong to a real hit.
		if (m_samples == 0 || evaluation.phase == OsuTimingAudioEvaluation::INVALID
			|| !std::isfinite(speed) || speed <= 0) return;
		const double assumedErrorMS = atReference && !evaluation.recent ? evaluation.referenceMapMS / speed : m_baselineMS;
		if (!std::isfinite(assumedErrorMS)) return;
		double variance = m_varianceMS2;
		const double mean = blend(m_baselineMS, variance, assumedErrorMS, m_activeMS - m_lastSampleMS);
		evaluation.setStatistics(m_samples + 1, mean, variance, speed);
	}

private:
	static bool isReady(const Config &config, bool recent, unsigned long long samples)
	{
		return !recent || (samples > 0 && (!config.silentStartup || samples >= 8));
	}

	static bool isInside300(const Config &config, double window300MS, const Result &result)
	{
		return !config.require300 || (result.precedingSamples > 0 && std::abs(result.baselineMS) <= window300MS);
	}

	static OsuTimingAudioEvaluation invalidEvaluation(bool recent)
	{
		OsuTimingAudioEvaluation evaluation;
		evaluation.phase = OsuTimingAudioEvaluation::INVALID;
		evaluation.recent = recent;
		return evaluation;
	}

	Result sampleInternal(double errorMS, Window window, bool recent, double opportunityMS, double beatmapDeviationMS,
		bool mapComparison, double errorMapMS, long double targetMapMS)
	{
		// The baseline is stored as double; its inclusive gate needs the same
		// precision, not an excess-precision x87 quotient at the current edge.
		const volatile double window300MS = std::isfinite(window.speed) && window.speed > 0.0
			? window.mapMS / window.speed : std::numeric_limits<double>::quiet_NaN();
		// An accepted early hit belongs to the opportunity at the END of a gap.
		// Resolve its scheduled boundary before evaluating/updating this sample.
		if (std::isfinite(errorMS) && std::isfinite(window300MS) && window300MS >= 0.0
			&& m_havePosition)
		{
			// At short thresholds, more than one return can be accepted before
			// the clock traverses the first gap. Apply each policy only once.
			for (size_t i = m_gapIndex; i < m_gaps.size() && opportunityMS >= m_gaps[i].endMS; ++i)
			{
				if (m_qualifiedGaps[i]) continue;
				const Activity &gap = m_gaps[i];
				const double elapsed = i == m_gapIndex ? m_gapElapsedMS : 0.0;
				const double remaining = std::max(0.0, gap.endMS - std::max(m_lastMapMS, gap.startMS)) / m_speed;
				if (elapsed + remaining + 0.000001 < m_config.breakSeconds * 1000.0) continue;
				if (i == m_gapIndex) qualifyGap();
				else
				{
					m_qualifiedGaps[i] = true;
					if (m_config.restartAfterBreak) restartBaseline();
				}
			}
		}
		Result result = {SILENT, m_baselineMS, recent ? errorMS - m_baselineMS : beatmapDeviationMS,
			m_samples, m_config.deadZoneMS, m_varianceMS2, false, false};
		if (m_config.bandMode != FIXED_MS)
		{
			// New widths and deviations use the same stored-double comparison,
			// even when the original target0 division remains in an x87 register.
			const volatile double deviationMS = result.deviationMS;
			result.deviationMS = deviationMS;
		}
		if (!std::isfinite(errorMS) || !std::isfinite(window300MS) || window300MS < 0.0
			|| !std::isfinite(window.speed) || window.speed <= 0.0)
		{
			m_lastEvaluation = invalidEvaluation(recent);
			return result;
		}
		// i686 x87 may keep a product's excess precision across an inline return.
		// Compare the stored double width exposed by Result, including its boundary.
		long double mapHalfWidthMS = 0;
		const volatile double halfWidthMS = bandHalfWidth(window, m_config, result, mapHalfWidthMS);
		result.halfWidthMS = halfWidthMS;
		const bool ready = isReady(m_config, recent, result.precedingSamples);
		const bool inside300 = isInside300(m_config, window300MS, result);
		if (ready && inside300)
		{
			if (recent || (mapComparison && (m_config.bandMode != FIXED_MS || targetMapMS != 0)))
			{
				// Recent's learned quantities already live in real-play units.
				// Beatmap geometry stays in map units until its endpoints are rounded.
				result.cue = static_cast<Cue>(recent
					? OsuTimingAudioReference::classify(OsuTimingAudioReference::stored(errorMS), m_baselineMS, result.halfWidthMS)
					: OsuTimingAudioReference::classify(errorMapMS, targetMapMS, mapHalfWidthMS));
			}
			else
			{
				if (result.deviationMS < -result.halfWidthMS) result.cue = EARLY;
				else if (result.deviationMS > result.halfWidthMS) result.cue = LATE;
			}
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
		result.accepted = true;
		m_lastEvaluation = describeEvaluation(result, recent, ready, inside300, window.speed, targetMapMS, mapHalfWidthMS);
		return result;
	}

	static OsuTimingAudioEvaluation describeEvaluation(const Result &result, bool recent, bool ready, bool inside300,
		double speed, long double targetMapMS, long double mapHalfWidthMS)
	{
		using Evaluation = OsuTimingAudioEvaluation;
		Evaluation evaluation;
		evaluation.recent = recent;
		evaluation.fixedFallback = result.fixedFallback;
		const double meanMapMS = result.baselineMS * speed;
		evaluation.setStatistics(result.precedingSamples, result.baselineMS, result.varianceMS2, speed);
		if (!recent || result.precedingSamples > 0)
			evaluation.referenceMapMS = recent ? meanMapMS : OsuTimingAudioReference::stored(targetMapMS);

		if (!(recent ? std::isfinite(meanMapMS) : std::isfinite(targetMapMS)))
			evaluation.phase = Evaluation::INVALID;
		else if (!ready)
			evaluation.phase = Evaluation::WARMUP;
		else if (!inside300)
			evaluation.phase = Evaluation::GATED;
		else
		{
			evaluation.phase = Evaluation::ACTIVE;
			if (recent)
			{
				const auto band = OsuTimingAudioReference::band(result.baselineMS, result.halfWidthMS);
				evaluation.silentMapMS = {band.lower * speed, band.upper * speed};
			}
			else
			{
				const auto band = OsuTimingAudioReference::band(targetMapMS, mapHalfWidthMS);
				evaluation.silentMapMS = {band.lower, band.upper};
			}
		}
		return evaluation;
	}

	static long double fractionalMapWidth(Window window, long double fraction)
	{
		// Retain entered fraction precision until completed interval endpoints.
		// Multiplying an already rounded real window can exclude a nominal edge.
		return fraction * window.mapMS;
	}

	static double bandHalfWidth(Window window, const Config &config, Result &result, long double &mapWidth)
	{
		mapWidth = static_cast<long double>(config.deadZoneMS) * window.speed;
		if (config.bandMode == FIXED_MS) return config.deadZoneMS;
		if (config.bandMode == RELATIVE_300)
		{
			const long double candidate = fractionalMapWidth(window, config.relativeFraction);
			const double width = OsuTimingAudioReference::stored(candidate / window.speed);
			if (std::isfinite(width) && width >= 0.0) { mapWidth = candidate; return width; }
		}
		else if (config.bandMode == ADAPTIVE_SPREAD && result.precedingSamples >= 2
			&& std::isfinite(result.varianceMS2) && result.varianceMS2 >= 0.0)
		{
			const long double low = fractionalMapWidth(window, config.adaptiveMinFraction);
			const long double high = fractionalMapWidth(window, config.adaptiveMaxFraction);
			const long double width = config.adaptiveScale * std::sqrt(result.varianceMS2) * window.speed;
			if (std::isfinite(low) && std::isfinite(high) && std::isfinite(width)
				&& low >= 0.0 && high >= low && width >= 0.0)
			{
				mapWidth = std::max(low, std::min(high, width));
				return mapWidth / window.speed;
			}
		}
		result.fixedFallback = true;
		return config.deadZoneMS;
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
		m_qualifiedGaps[m_gapIndex] = true;
		if (m_config.restartAfterBreak) restartBaseline();
	}
	void restartBaseline()
	{
		m_baselineMS = 0.0;
		m_varianceMS2 = 0.0;
		m_samples = 0;
		m_lastSampleMS = m_activeMS;
		m_haveGapCorrection = false;
		m_lastEvaluation = OsuTimingAudioEvaluation();
		++m_generation;
	}
	Config m_config;
	OsuTimingAudioEvaluation m_lastEvaluation;
	unsigned long long m_generation = 0;
	std::vector<Activity> m_gaps;
	std::vector<bool> m_qualifiedGaps;
	double m_baselineMS, m_activeMS, m_lastSampleMS, m_lastMapMS, m_gapElapsedMS, m_speed;
	double m_gapBaselineMS, m_gapSampleClockMS;
	double m_varianceMS2, m_gapVarianceMS2;
	unsigned long long m_samples;
	size_t m_gapIndex;
	bool m_havePosition, m_gapQualified, m_haveGapCorrection;
};

#endif

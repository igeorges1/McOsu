#ifndef OSUTIMINGAUDIOHUD_H
#define OSUTIMINGAUDIOHUD_H

#include "OsuTimingAudioEvaluation.h"
#include <algorithm>
#include <cmath>

namespace OsuTimingAudioHUD
{
	struct Span
	{
		bool visible = false;
		bool showLowerCap = false, showUpperCap = false;
		float lower = 0, upper = 0;
	};

	struct Geometry
	{
		bool showReference = false;
		bool showMean = false;
		float reference = 0;
		float mean = 0;
		Span spread, silent;
	};

	// Same map-ms divisor and half-width as the hit-error entries. Clip ranges
	// at the bar edge, without turning an off-bar reference into a false mark.
	inline Geometry project(const OsuTimingAudioEvaluation &evaluation, float windowMapMS, float halfWidth,
		bool showSpread = true, bool showSilentBand = true)
	{
		Geometry geometry;
		if (!std::isfinite(windowMapMS) || windowMapMS <= 0 || !std::isfinite(halfWidth) || halfWidth <= 0)
			return geometry;

		const auto position = [=](double mapMS) { return static_cast<float>(mapMS / windowMapMS * halfWidth); };
		const auto projectRange = [=](const OsuTimingAudioEvaluation::Range &range)
		{
			Span span;
			if (std::isfinite(range.lower) && std::isfinite(range.upper) && range.lower <= range.upper
				&& range.lower <= windowMapMS && range.upper >= -windowMapMS)
			{
				span.visible = true;
				span.showLowerCap = range.lower >= -windowMapMS;
				span.showUpperCap = range.upper <= windowMapMS;
				span.lower = position(std::max(range.lower, -static_cast<double>(windowMapMS)));
				span.upper = position(std::min(range.upper, static_cast<double>(windowMapMS)));
			}
			return span;
		};
		geometry.showReference = std::abs(evaluation.referenceMapMS) <= windowMapMS;
		if (geometry.showReference) geometry.reference = position(evaluation.referenceMapMS);
		geometry.showMean = std::abs(evaluation.learnedMeanMapMS) <= windowMapMS;
		if (geometry.showMean) geometry.mean = position(evaluation.learnedMeanMapMS);
		if (showSpread) geometry.spread = projectRange(evaluation.spreadMapMS);
		if (showSilentBand) geometry.silent = projectRange(evaluation.silentMapMS);
		return geometry;
	}

	// Animate the white statistics only. The audio reference and cue interval
	// always use their exact current positions.
	class Transition
	{
	public:
		OsuTimingAudioEvaluation present(const OsuTimingAudioView &view, double windowMapMS, double now)
		{
			const auto &previous = m_target.evaluation;
			const auto &next = view.evaluation;
			if (!m_initialized || !std::isfinite(now) || now < m_started || windowMapMS != m_window
				|| view.generation != m_target.generation || view.speed != m_target.speed
				|| view.window300MapMS != m_target.window300MapMS || view.bandMode != m_target.bandMode
				|| view.mode != m_target.mode || next.recent != previous.recent
				|| next.phase != previous.phase || next.phase == OsuTimingAudioEvaluation::OFF
				|| next.phase == OsuTimingAudioEvaluation::INVALID
				|| side(previous.learnedMeanMapMS, windowMapMS) != side(next.learnedMeanMapMS, windowMapMS)
				|| side(previous.spreadMapMS.lower, windowMapMS) != side(next.spreadMapMS.lower, windowMapMS)
				|| side(previous.spreadMapMS.upper, windowMapMS) != side(next.spreadMapMS.upper, windowMapMS))
			{
				m_initialized = std::isfinite(now);
				m_window = windowMapMS;
				m_target = view;
				m_start = next;
				m_started = now;
				return next;
			}

			if (!same(previous.learnedMeanMapMS, next.learnedMeanMapMS)
				|| !same(previous.spreadMapMS.lower, next.spreadMapMS.lower)
				|| !same(previous.spreadMapMS.upper, next.spreadMapMS.upper))
			{
				m_start = at(now);
				m_started = now;
			}
			m_target = view;
			return at(now);
		}

	private:
		static bool same(double a, double b)
		{
			return a == b || (std::isnan(a) && std::isnan(b));
		}

		static int side(double value, double window)
		{
			if (!std::isfinite(value)) return 2;
			return value < -window ? -1 : (value > window ? 1 : 0);
		}

		static double interpolate(double from, double to, double fraction)
		{
			return std::isfinite(from) && std::isfinite(to) ? from + fraction * (to - from) : to;
		}

		OsuTimingAudioEvaluation at(double now) const
		{
			auto value = m_target.evaluation;
			const double fraction = (now - m_started) / 0.12;
			if (fraction >= 1.0) return value;
			value.learnedMeanMapMS = interpolate(m_start.learnedMeanMapMS, value.learnedMeanMapMS, fraction);
			value.spreadMapMS.lower = interpolate(m_start.spreadMapMS.lower, value.spreadMapMS.lower, fraction);
			value.spreadMapMS.upper = interpolate(m_start.spreadMapMS.upper, value.spreadMapMS.upper, fraction);
			return value;
		}

		bool m_initialized = false;
		double m_window = 0, m_started = 0;
		OsuTimingAudioView m_target;
		OsuTimingAudioEvaluation m_start;
	};
}

#endif

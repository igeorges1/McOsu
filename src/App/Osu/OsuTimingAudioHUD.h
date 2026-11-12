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
	inline Geometry project(const OsuTimingAudioEvaluation &evaluation, float windowMapMS, float halfWidth, bool markersOnly = false)
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
		if (evaluation.spreadMapMS.lower <= evaluation.spreadMapMS.upper)
		{
			// The mean belongs to the evaluated spread, even if its drawn span is clipped.
			const double meanMapMS = evaluation.spreadMapMS.lower * 0.5 + evaluation.spreadMapMS.upper * 0.5;
			geometry.showMean = std::abs(meanMapMS) <= windowMapMS;
			if (geometry.showMean) geometry.mean = position(meanMapMS);
		}
		if (!markersOnly)
		{
			geometry.spread = projectRange(evaluation.spreadMapMS);
			geometry.silent = projectRange(evaluation.silentMapMS);
		}
		return geometry;
	}
}

#endif

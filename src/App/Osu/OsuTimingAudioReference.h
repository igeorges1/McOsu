// Pure cue-reference mapping. Judgement and sample eligibility stay with the game.
#ifndef OSUTIMINGAUDIOREFERENCE_H
#define OSUTIMINGAUDIOREFERENCE_H

#include <climits>
#include <cmath>
#include <limits>

class OsuTimingAudioReference
{
public:
	struct Windows { double hit300, hit100, hit50; }; // raw map-ms getters
	struct Result { bool valid; double targetMapMS, targetMS, deviationMS; long double preciseTargetMapMS; };
	struct Band { double lower, upper; };

	static double stored(long double value)
	{
		const volatile double result = static_cast<double>(value);
		return result;
	}

	// Round completed interval endpoints, not a subtracted deviation and width.
	// Callers use map units for Beatmap geometry, real ms for learned Recent data.
	static Band band(long double center, long double halfWidth)
	{
		// A zero-width interval is the canonical point also exposed by calculate().
		if (halfWidth == 0) center = stored(center);
		return {stored(center - halfWidth), stored(center + halfWidth)};
	}
	static int classify(double value, long double center, long double halfWidth, double *excess = nullptr)
	{
		if (excess) *excess = 0;
		if (!std::isfinite(value) || !std::isfinite(center) || !std::isfinite(halfWidth) || halfWidth < 0) return 0;
		const Band edges = band(center, halfWidth);
		if (value < edges.lower)
		{
			if (excess) *excess = edges.lower - value;
			return -1;
		}
		if (value > edges.upper)
		{
			if (excess) *excess = value - edges.upper;
			return 1;
		}
		return 0;
	}

	static bool truncateWindow(double value, long &edge)
	{
		// Upper bound is exclusive and exactly representable, including on 64-bit long.
		if (!std::isfinite(value) || value < 0.0 || value >= -static_cast<double>(LONG_MIN)) return false;
		edge = static_cast<long>(value);
		return true;
	}

	static Result calculate(long errorMapMS, double speed, long double coordinate, Windows windows)
	{
		Result result = {false, 0.0, 0.0, std::numeric_limits<double>::quiet_NaN(), 0.0L};
		if (!std::isfinite(speed) || speed <= 0.0 || !std::isfinite(coordinate) || std::abs(coordinate) > 3.0) return result;
		if (coordinate == 0.0L)
		{
			result.deviationMS = static_cast<double>(errorMapMS) / speed;
			result.valid = std::isfinite(result.deviationMS);
			return result;
		}
		else
		{
			long w300, w100, w50;
			if (!truncateWindow(windows.hit300, w300) || !truncateWindow(windows.hit100, w100)
				|| !truncateWindow(windows.hit50, w50) || !(0 < w300 && w300 < w100 && w100 < w50)) return result;
			const long double magnitude = std::abs(coordinate);
			const long double target = magnitude <= 1.0L ? magnitude * w300
				: magnitude <= 2.0L ? w300 + (magnitude - 1.0L) * (w100 - w300)
				: w100 + (magnitude - 2.0L) * (w50 - w100);
			const long double signedTarget = coordinate < 0.0L ? -target : target;
			result.preciseTargetMapMS = signedTarget;
			// Canonical diagnostic point/deviation; retain preciseTargetMapMS for
			// interval construction so nonzero widths do not suffer cancellation.
			const volatile double targetMapMS = static_cast<double>(signedTarget);
			result.targetMapMS = targetMapMS;
			result.targetMS = targetMapMS / speed;
			const volatile double deviationMS = static_cast<double>((static_cast<long double>(errorMapMS) - targetMapMS) / speed);
			result.deviationMS = deviationMS;
		}
		// Subtract BEFORE conversion: 35/1.5 - 50/1.5 spuriously crosses -10ms.
		result.valid = std::isfinite(result.targetMS) && std::isfinite(result.deviationMS);
		return result;
	}
};

#endif

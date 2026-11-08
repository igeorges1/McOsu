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
	struct Result { bool valid; double targetMapMS, targetMS, deviationMS; };

	static bool truncateWindow(double value, long &edge)
	{
		// Upper bound is exclusive and exactly representable, including on 64-bit long.
		if (!std::isfinite(value) || value < 0.0 || value >= -static_cast<double>(LONG_MIN)) return false;
		edge = static_cast<long>(value);
		return true;
	}

	static Result calculate(long errorMapMS, double speed, long double coordinate, Windows windows)
	{
		Result result = {false, 0.0, 0.0, std::numeric_limits<double>::quiet_NaN()};
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
			result.targetMapMS = static_cast<double>(signedTarget);
			result.targetMS = static_cast<double>(signedTarget / speed);
			// Keep decimal-coordinate precision through subtraction as well.
			const volatile double deviationMS = static_cast<double>((static_cast<long double>(errorMapMS) - signedTarget) / speed);
			result.deviationMS = deviationMS;
		}
		// Subtract BEFORE conversion: 35/1.5 - 50/1.5 spuriously crosses -10ms.
		result.valid = std::isfinite(result.targetMS) && std::isfinite(result.deviationMS);
		return result;
	}
};

#endif

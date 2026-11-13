#ifndef OSUTIMINGCUEPRESENTATION_H
#define OSUTIMINGCUEPRESENTATION_H

#include <algorithm>
#include <cmath>

namespace OsuTimingCuePresentation
{
	inline int side(int direction, bool invert) { return invert ? -direction : direction; }
	inline float pan(int direction, bool split, bool invert) { return split ? side(direction, invert) : 0; }

	struct Pulse
	{
		int direction = 0;
		double excessMS = 0, started = 0;
		unsigned long long generation = 0;

		double opacity(double now, double hold, double fade, double maximum, bool variable, double saturation, double floor) const
		{
			const double age = now - started;
			if (!direction || !std::isfinite(age) || age < 0 || age >= hold + fade || !(fade > 0)) return 0;
			const double strength = variable && std::isfinite(excessMS) && saturation > 0
				? floor + (1.0 - floor) * std::min(1.0, std::max(0.0, excessMS / saturation)) : 1.0;
			return maximum * strength * (1.0 - std::max(0.0, age - hold) / fade);
		}
	};

	struct Rect
	{
		int x = 0, y = 0, width = 0, height = 0;
	};

	inline Rect margin(int side, int width, int height, double playfieldEdge, double widthFraction,
		double heightFraction, double insetFraction, double verticalCenter)
	{
		Rect rect;
		if (!side || width < 1 || height < 1 || !std::isfinite(playfieldEdge)) return rect;
		const double available = side < 0 ? playfieldEdge : width - playfieldEdge;
		const int margin = static_cast<int>(std::max(0.0, std::min<double>(width, available)));
		const int inset = std::min(margin, static_cast<int>(width * insetFraction));
		rect.width = std::min(margin - inset, std::max(1, static_cast<int>(width * widthFraction)));
		rect.height = std::min(height, std::max(1, static_cast<int>(height * heightFraction)));
		rect.x = side < 0 ? inset : width - inset - rect.width;
		rect.y = std::max(0, std::min(height - rect.height, static_cast<int>(height * verticalCenter) - rect.height / 2));
		return rect;
	}
}

#endif

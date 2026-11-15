#ifndef OSUGAMEPLAYCAPTURE_H
#define OSUGAMEPLAYCAPTURE_H

#include <array>
#include <cstdint>
#include <ostream>

namespace OsuGameplayCapture
{
	enum { MAX_DRAWS = 4, MAX_ROWS = 4217 };

	struct Identity
	{
		std::uint64_t creation = 0;
		std::int64_t frequency = 0;
		unsigned pid = 0, tid = 0;
		bool valid() const { return creation && frequency > 0 && pid && tid; }
	};

	struct Config
	{
		bool requested = false, update = true, draws = true, stages = true;
		int drawLimit = MAX_DRAWS, rowLimit = MAX_ROWS;
		bool valid() const
		{
			return drawLimit >= 1 && drawLimit <= MAX_DRAWS && rowLimit >= 1 && rowLimit <= MAX_ROWS;
		}
		bool operator==(const Config &other) const
		{
			return requested == other.requested && update == other.update && draws == other.draws && stages == other.stages
				&& drawLimit == other.drawLimit && rowLimit == other.rowLimit;
		}
	};

	struct Span { std::int64_t start = -1, end = -1; };

	struct Frame
	{
		std::uint64_t epoch = 0;
		Span update;
		std::int64_t next = -1;
		std::array<Span, MAX_DRAWS> draws;
		unsigned observed = 0;

		bool contains(std::int64_t tick) const
		{
			return epoch && update.start >= 0 && update.start <= tick && tick < next;
		}
	};

	struct Mark
	{
		Config config;
		Identity identity;
		std::uint64_t epoch = 0, id = 0;
		std::int64_t tick = -1, snapshotEnd = -1;
		Span readback;
		int historyRequested = 0, history = 0, tailRequested = 0, tail = 0;
		int tailMilliseconds = 2000;
		bool screenshot = false, model = false;
		const char *status = "disabled";
	};

	bool supported();
	Identity identify();
	unsigned thread();
	std::int64_t ticks();
}

#endif

#include "../src/App/Osu/OsuPerformanceHistory.h"
#include <cstdio>

int main()
{
	OsuPerformanceHistory history;
	history.setCapacity(4);
	OsuPerformanceHistory::Frame context;
	context.raw.epoch = 1;
	context.raw.update.start = 9007199254741000LL;
	history.begin(1, context);
	history.endRawUpdate(context.raw.update.start + 2);
	for (int i = 0; i < 5; ++i)
	{
		OsuGameplayCapture::Span draw;
		draw.start = context.raw.update.start + 3 + i;
		draw.end = draw.start + 1;
		history.endRawDraw(draw, 4);
	}
	OsuGameplayCapture::Mark mark;
	mark.epoch = 1;
	mark.tick = context.raw.update.start + 10;
	auto window = history.mark(2, 0, mark.epoch);
	context.raw.update.start = mark.tick;
	const auto *first = history.begin(2, context);
	if (!first || first->raw.observed != 5 || first->raw.draws[3].start != mark.tick - 4
		|| first->raw.next != mark.tick || first->raw.contains(mark.tick)) return 1;
	OsuPerformanceHistory::appendRaw(window, *first, mark);
	if (OsuPerformanceHistory::rawFinished(window, mark)) return 2;
	context.raw.update.start += 10;
	const auto *second = history.begin(3, context);
	OsuPerformanceHistory::appendRaw(window, *second, mark);
	if (!OsuPerformanceHistory::rawFinished(window, mark) || window.rawFrames.size() != 1
		|| window.rawBoundary != second->sequence || window.rawFrames[0].raw.update.start != mark.tick) return 3;
	context.raw.epoch = 2;
	context.raw.update.start += 10;
	const auto *interrupted = history.begin(4, context);
	if (!interrupted || interrupted->raw.next != -1 || history.rawOpen(1, context.raw.update.start)) return 4;
	if (!history.rawOpen(2, context.raw.update.start)) return 5;
	const auto *duplicate = history.begin(4, context);
	if (!duplicate || duplicate->raw.next != -1) return 6;
	std::puts("COMPLETE gameplay raw frame cases");
	return 0;
}

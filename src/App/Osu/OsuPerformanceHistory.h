#ifndef OSUPERFORMANCEHISTORY_H
#define OSUPERFORMANCEHISTORY_H

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>
#include "OsuGameplayCapture.h"

class OsuPerformanceHistory
{
public:
	enum Context { FOCUSED = 1, MINIMIZED = 2, PLAY = 4, PAUSED = 8, LOADING = 16, WAITING = 32, CONTINUE = 64 };
	struct Frame
	{
		uint64_t sequence = 0;
		double start = 0, interval = -1, update = -1, draw = -1;
		unsigned draws = 0, context = 0;
		float foregroundLimit = -1, backgroundLimit = -1;
		int unlimited = -1, vsync = -1;
		OsuGameplayCapture::Frame raw;
	};
	struct Window
	{
		std::vector<Frame> frames;
		uint64_t evicted = 0, discontinuities = 0;
		double mark = 0;
		unsigned postTarget = 0, postCount = 0;
		uint64_t boundarySequence = 0;
		uint64_t rawBoundary = 0;
		unsigned rawPostCount = 0;
		std::vector<Frame> rawFrames;
	};

	void setCapacity(size_t capacity)
	{
		if (capacity == m_ring.size()) return;
		m_ring.resize(capacity);
		m_count = m_next = 0;
		m_evicted = m_discontinuities = 0;
		m_active = false;
	}

	// The interval belongs to the update that started it. An update and any
	// intervening draw calls are only reported once the next update starts.
	const Frame *begin(double now, const Frame &context)
	{
		if (m_ring.empty()) return nullptr;
		const Frame *completed = nullptr;
		const bool valid = validStamp(now);
		if (!valid || (m_active && now < m_current.start))
		{
			m_count = m_next = 0;
			m_evicted = 0;
			++m_discontinuities;
		}
		else if (m_active)
		{
			m_current.interval = now - m_current.start;
			if (m_current.raw.epoch && m_current.raw.epoch == context.raw.epoch
				&& context.raw.update.start > m_current.raw.update.start)
				m_current.raw.next = context.raw.update.start;
			m_ring[m_next] = m_current;
			completed = &m_ring[m_next];
			m_next = (m_next + 1) % m_ring.size();
			if (m_count < m_ring.size()) ++m_count;
			else ++m_evicted;
		}
		m_active = valid;
		m_current = context;
		m_current.sequence = ++m_sequence;
		m_current.start = now;
		return completed;
	}

	void endUpdate(double elapsed) { if (m_active && elapsed >= 0) m_current.update = elapsed; }
	void endRawUpdate(std::int64_t tick)
	{
		if (m_active && m_current.raw.epoch && tick >= m_current.raw.update.start) m_current.raw.update.end = tick;
	}
	void endRawDraw(OsuGameplayCapture::Span span, unsigned limit)
	{
		if (!m_active || !m_current.raw.epoch) return;
		auto &raw = m_current.raw;
		const unsigned index = raw.observed++;
		if (index < limit) raw.draws[index] = span;
	}

	bool rawOpen(std::uint64_t epoch, std::int64_t tick) const
	{
		return m_active && epoch && m_current.raw.epoch == epoch && m_current.raw.update.start >= 0
			&& tick >= m_current.raw.update.start;
	}
	void endDraw(double elapsed)
	{
		if (!m_active || !(elapsed >= 0)) return;
		if (!m_current.draws++) m_current.draw = 0;
		m_current.draw += elapsed;
	}

	Window mark(double now, unsigned post, std::uint64_t rawEpoch = 0) const
	{
		Window result;
		result.mark = now;
		result.evicted = m_evicted;
		result.discontinuities = m_discontinuities;
		result.postTarget = post;
		result.frames.reserve(m_count + post + 1);
		if (rawEpoch) result.rawFrames.reserve(m_count + post + 1);
		for (size_t i = 0; i < m_count; ++i)
		{
			const auto &frame = m_ring[(m_next + m_ring.size() - m_count + i) % m_ring.size()];
			result.frames.push_back(frame);
			if (rawEpoch && frame.raw.epoch == rawEpoch) result.rawFrames.push_back(frame);
		}
		return result;
	}

	static void appendRaw(Window &window, const Frame &frame, const OsuGameplayCapture::Mark &mark)
	{
		if (!mark.epoch || frame.raw.epoch != mark.epoch || frame.raw.next < 0) return;
		if (!window.rawBoundary && frame.raw.contains(mark.tick))
		{
			window.rawBoundary = frame.sequence;
			window.rawFrames.push_back(frame);
		}
		else if (window.rawBoundary && window.rawPostCount < window.postTarget)
		{
			window.rawFrames.push_back(frame);
			++window.rawPostCount;
		}
	}

	static bool rawFinished(const Window &window, const OsuGameplayCapture::Mark &mark)
	{
		return !mark.epoch || (window.rawBoundary && window.rawPostCount >= window.postTarget);
	}

	static void append(Window &window, const Frame &frame)
	{
		if (!window.frames.empty() && frame.sequence <= window.frames.back().sequence) return;
		if (frame.start <= window.mark && frame.start + frame.interval >= window.mark && !window.boundarySequence)
		{
			window.frames.push_back(frame);
			window.boundarySequence = frame.sequence;
			return;
		}
		if (window.postCount >= window.postTarget || frame.start < window.mark) return;
		window.frames.push_back(frame);
		++window.postCount;
	}

	static bool finished(const Window &window)
	{
		return window.boundarySequence && window.postCount >= window.postTarget;
	}

	static bool validStamp(double now) { return std::isfinite(now) && now >= 0; }

	// A pending snapshot keeps its earlier samples but cannot cross a clock reset.
	bool continueWindow(Window &window, double now) const
	{
		const bool sameSegment = window.discontinuities == m_discontinuities;
		window.discontinuities = m_discontinuities;
		return sameSegment && validStamp(now) && now >= window.mark;
	}

	uint64_t discontinuities() const { return m_discontinuities; }

private:
	std::vector<Frame> m_ring;
	Frame m_current;
	size_t m_count = 0, m_next = 0;
	uint64_t m_sequence = 0, m_evicted = 0, m_discontinuities = 0;
	bool m_active = false;
};

#endif

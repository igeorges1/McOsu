#ifndef OSUPERFORMANCEHISTORY_H
#define OSUPERFORMANCEHISTORY_H

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

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
	};
	struct Window
	{
		std::vector<Frame> frames;
		uint64_t evicted = 0, discontinuities = 0;
		double mark = 0;
		unsigned postTarget = 0, postCount = 0;
		uint64_t boundarySequence = 0;
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
	void endDraw(double elapsed)
	{
		if (!m_active || !(elapsed >= 0)) return;
		if (!m_current.draws++) m_current.draw = 0;
		m_current.draw += elapsed;
	}

	Window mark(double now, unsigned post) const
	{
		Window result;
		result.mark = now;
		result.evicted = m_evicted;
		result.discontinuities = m_discontinuities;
		result.postTarget = post;
		result.frames.reserve(m_count + post + 1);
		for (size_t i = 0; i < m_count; ++i)
			result.frames.push_back(m_ring[(m_next + m_ring.size() - m_count + i) % m_ring.size()]);
		return result;
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

#ifndef OSUTIMINGAUDIOPLAYCLOCK_H
#define OSUTIMINGAUDIOPLAYCLOCK_H

#include <cmath>

// Count only intervals bracketed by active gameplay. Keep the high-water mark
// on a backward stamp, so returning to that time never adds the interval twice.
class OsuTimingAudioPlayClock
{
public:
	void advance(double now, bool playing)
	{
		if (!std::isfinite(now))
		{
			m_playing = false;
			return;
		}
		if (!m_haveTime || now >= m_lastTime)
		{
			if (m_haveTime && m_playing && playing) m_playSeconds += now - m_lastTime;
			m_lastTime = now;
			m_haveTime = true;
		}
		m_playing = playing;
	}

	double seconds() const { return m_playSeconds; }

private:
	double m_lastTime = 0, m_playSeconds = 0;
	bool m_haveTime = false, m_playing = false;
};

#endif

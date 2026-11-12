#ifndef OSUTIMINGAUDIOCAPTURE_H
#define OSUTIMINGAUDIOCAPTURE_H

#include "OsuTimingAudioState.h"
#include <array>
#include <cstdint>
#include <iomanip>
#include <initializer_list>
#include <locale>
#include <ostream>
#include <string>

// Wire format shared by the live recorder and the console consumer.
class OsuTimingAudioCapture
{
public:
	enum Event { CLOCK = 1, CONFIG, ACTIVITIES, ACTIVITY, ADVANCE, PAUSE, HIT, OUTPUT, MARK, LIFECYCLE };
	enum Lifecycle { LOADING = 1, CONTINUE, COUNTDOWN, SKIP, RELOAD };
	static constexpr size_t VALUE_LIMIT = 1000000;
	static constexpr size_t METADATA_LIMIT = 32768;
	using ConfigValues = std::array<long double, 19>;

	void sync(bool enabled, bool fromReset)
	{
		if (enabled == m_enabled) return;
		m_enabled = enabled;
		if (enabled) reset(fromReset);
		else m_values.clear();
	}

	void reset(bool fromReset = true)
	{
		m_values.clear();
		m_complete = fromReset;
		m_overflow = false;
		m_haveConfig = false;
		m_hitObserved = false;
		if (m_enabled) m_values.reserve(VALUE_LIMIT);
	}

	bool enabled() const { return m_enabled; }
	bool hasData() const { return m_enabled && !m_values.empty(); }
	bool complete() const { return m_enabled && m_complete && !m_overflow && m_hitObserved; }

	void add(Event event, std::initializer_list<long double> values)
	{
		if (!m_enabled || m_overflow) return;
		if (m_values.size() + 2 + values.size() > VALUE_LIMIT)
		{
			m_overflow = true;
			return;
		}
		m_values.push_back(event);
		m_values.push_back(values.size());
		m_values.insert(m_values.end(), values.begin(), values.end());
	}

	static ConfigValues values(const OsuTimingAudioState::Config &c)
	{
		return {{(long double)c.fixedHits, c.halfLifeSeconds, c.halfLifeHits, c.breakSeconds, c.deadZoneMS,
			(long double)c.bandMode, c.relativeFraction, c.adaptiveScale, c.adaptiveMinFraction, c.adaptiveMaxFraction,
			(long double)c.silentStartup, (long double)c.require300, (long double)c.restartAfterBreak,
			(long double)c.startupAverageHits, (long double)c.silentStartupHits, (long double)c.adaptiveStartupMaximum,
			(long double)c.idleForgiveness, c.idleGraceSeconds, c.idleRampSeconds}};
	}

	void configure(const OsuTimingAudioState::Config &config, double playSeconds)
	{
		if (!m_enabled || m_overflow) return;
		const auto v = values(config);
		if (m_haveConfig && v == m_config && m_recovery == config.idleRecoveryHits) return;
		m_config = v;
		m_recovery = config.idleRecoveryHits;
		m_haveConfig = true;
		add(CONFIG, {playSeconds, v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9],
			v[10], v[11], v[12], v[13], v[14], v[15], v[16], v[17], v[18], (long double)m_recovery});
	}

	void hit(double error, OsuTimingAudioState::Window window, bool recent, double opportunity, long double target,
		const OsuTimingAudioState &state, const OsuTimingAudioState::Result &result)
	{
		const auto &used = state.getLastEvaluation();
		m_hitObserved = m_hitObserved || result.accepted;
		add(HIT, {error, window.mapMS, window.speed, (long double)recent, opportunity, target,
			(long double)result.accepted, (long double)result.cue, result.halfWidthMS,
			(long double)state.getSamples(), state.getBaselineMS(), state.getVarianceMS2(), state.getActiveMS(),
			(long double)used.phase, used.silentMapMS.lower, used.silentMapMS.upper});
	}

	bool write(std::ostream &destination, const std::string &source, const std::string &map, const std::string &metadata) const
	{
		const bool metadataFits = metadata.size() <= METADATA_LIMIT;
		ChecksumBuffer buffer(destination.rdbuf());
		std::ostream out(&buffer);
		out.imbue(std::locale::classic());
		out << "MCOSU_TIMING_CAPTURE 1\nsource " << source << "\nmap " << map
			<< "\nstatus " << (m_overflow ? "overflow" : !m_complete ? "mid-session"
				: !m_hitObserved ? "no-hits" : !metadataFits ? "metadata-overflow"
				: source == "unknown" || map == "unknown" ? "missing-identity" : "complete")
			<< "\nmetadata ";
		const char hex[] = "0123456789abcdef";
		for (size_t i = 0; i < metadata.size() && i < METADATA_LIMIT; ++i)
		{
			const auto byte = static_cast<unsigned char>(metadata[i]);
			out << hex[byte >> 4] << hex[byte & 15];
		}
		out << "\nvalues " << m_values.size() << '\n' << std::setprecision(std::numeric_limits<long double>::max_digits10);
		size_t ordinal = 0;
		for (size_t pos = 0; pos < m_values.size();)
		{
			const auto count = static_cast<size_t>(m_values[pos + 1]);
			out << ++ordinal << ' ' << m_values[pos] << ' ' << count;
			pos += 2;
			for (size_t end = pos + count; pos < end; ++pos) out << ' ' << m_values[pos];
			out << '\n';
		}
		out << "end\n";
		if (!out.good()) return false;
		destination << "checksum " << std::hex << std::setw(16) << std::setfill('0') << buffer.hash << '\n';
		return destination.good();
	}

private:
	class ChecksumBuffer : public std::streambuf
	{
	public:
		explicit ChecksumBuffer(std::streambuf *destination) : m_destination(destination) {}
		uint64_t hash = UINT64_C(14695981039346656037);
	protected:
		std::streamsize xsputn(const char *text, std::streamsize size) override
		{
			const auto written = m_destination->sputn(text, size);
			for (std::streamsize i = 0; i < written; ++i)
			{
				hash ^= static_cast<unsigned char>(text[i]);
				hash *= UINT64_C(1099511628211);
			}
			return written;
		}
		int_type overflow(int_type value) override
		{
			if (traits_type::eq_int_type(value, traits_type::eof())) return traits_type::not_eof(value);
			const char byte = traits_type::to_char_type(value);
			return xsputn(&byte, 1) == 1 ? value : traits_type::eof();
		}
	private:
		std::streambuf *m_destination;
	};
	std::vector<long double> m_values;
	ConfigValues m_config{};
	unsigned int m_recovery = 0;
	bool m_enabled = false, m_complete = false, m_haveConfig = false, m_overflow = false, m_hitObserved = false;
};

#endif

#include "OsuTimingAudioCapture.h"
#include "OsuTimingAudioPlayClock.h"
#include "OsuTimingAudioRecentWindow.h"
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>

using Capture = OsuTimingAudioCapture;
using State = OsuTimingAudioState;

static void require(bool ok, const std::string &reason)
{
	if (!ok) throw std::runtime_error(reason);
}

static void compare(size_t ordinal, const char *field, long double expected, long double actual)
{
	if (expected == actual || (std::isnan(expected) && std::isnan(actual))) return;
	if (std::isfinite(expected) && std::isfinite(actual) &&
		std::abs(expected - actual) <= 1e-10L * std::max(1.0L, std::abs(expected))) return;
	std::ostringstream error;
	error << std::setprecision(std::numeric_limits<long double>::max_digits10)
		<< "DIVERGENCE event=" << ordinal << " field=" << field << " captured=" << expected << " replayed=" << actual;
	throw std::runtime_error(error.str());
}

static bool between(long double value, long double low, long double high)
{
	return std::isfinite(value) && value >= low && value <= high;
}

static size_t integer(long double value, size_t max)
{
	require(between(value, 0, max) && std::floor(value) == value, "Invalid integer event value");
	return static_cast<size_t>(value);
}

static State::Config configFrom(const std::vector<long double> &v)
{
	State::Config c;
	require(between(v[2], 0.001L, 3600) && between(v[3], 0.001L, 100000)
		&& between(v[4], 0.001L, 3600) && between(v[5], 0, 1000)
		&& between(v[7], 0, 10) && between(v[8], 0, 10)
		&& between(v[9], 0, 10) && between(v[10], v[9], 10)
		&& between(v[18], 0, 60) && between(v[19], 0, 60), "Invalid resolved config");
	c.fixedHits = integer(v[1], 1);
	c.halfLifeSeconds = v[2]; c.halfLifeHits = v[3]; c.breakSeconds = v[4]; c.deadZoneMS = v[5];
	c.bandMode = static_cast<State::BandMode>(integer(v[6], 2));
	c.relativeFraction = v[7]; c.adaptiveScale = v[8]; c.adaptiveMinFraction = v[9]; c.adaptiveMaxFraction = v[10];
	c.silentStartup = integer(v[11], 1); c.require300 = integer(v[12], 1); c.restartAfterBreak = integer(v[13], 1);
	c.startupAverageHits = integer(v[14], 128); c.silentStartupHits = integer(v[15], 128);
	c.adaptiveStartupMaximum = integer(v[16], 1); c.idleForgiveness = integer(v[17], 1);
	c.idleGraceSeconds = v[18]; c.idleRampSeconds = v[19]; c.idleRecoveryHits = integer(v[20], 128);
	require(c.startupAverageHits && c.idleRecoveryHits, "Invalid zero config count");
	return c;
}

static std::string line(std::istream &input)
{
	std::string value;
	require(static_cast<bool>(std::getline(input, value)), "Unexpected end of capture");
	if (!value.empty() && value.back() == '\r') value.pop_back();
	return value;
}

static std::string field(std::istream &input, const std::string &name)
{
	const auto value = line(input);
	require(value.compare(0, name.size() + 1, name + ' ') == 0, "Missing " + name);
	return value.substr(name.size() + 1);
}

static long double number(const std::string &text)
{
	require(!text.empty() && text.size() <= 64, "Invalid number token");
	char *end = NULL;
	const auto n = std::strtold(text.c_str(), &end);
	require(end != text.c_str() && *end == 0, "Invalid number token: " + text);
	return n;
}

static bool hash(const std::string &value, size_t length)
{
	return value.size() == length && value.find_first_not_of("0123456789abcdef") == std::string::npos;
}

static void replay(std::istream &input, const std::string &source)
{
	require(line(input) == "MCOSU_TIMING_CAPTURE 1", "Unsupported capture schema");
	const auto captured = field(input, "source");
	const auto map = field(input, "map");
	const auto status = field(input, "status");
	require(status == "complete", "Capture is insufficient: " + status);
	require(hash(captured, 40) && captured == source, "Capture source " + captured + " does not match consumer source " + source);
	require(hash(map, 32), "Missing or invalid map identity");
	const auto metadata = field(input, "metadata");
	require(!metadata.empty() && metadata.size() <= 2 * Capture::METADATA_LIMIT && metadata.size() % 2 == 0
		&& metadata.find_first_not_of("0123456789abcdef") == std::string::npos, "Missing or invalid mark metadata");
	const auto declared = integer(number(field(input, "values")), Capture::VALUE_LIMIT);
	State state;
	OsuTimingAudioPlayClock clock;
	OsuTimingAudioRecentWindow history;
	std::vector<State::Activity> activities;
	size_t total = 0, ordinal = 0, pendingActivities = 0, hits = 0, marks = 0;
	bool configured = false, prepared = false, needsOutput = false;
	int last = 0;
	for (auto text = line(input); text != "end"; text = line(input))
	{
		require(text.size() <= 2048, "Event row exceeds format bound");
		std::istringstream row(text);
		row.imbue(std::locale::classic());
		size_t index = 0, count = 0;
		int event = 0;
		static const size_t arity[] = {0, 3, 21, 1, 2, 2, 1, 16, 5, 7, 2};
		++ordinal;
		require(static_cast<bool>(row >> index >> event >> count) && index == ordinal
			&& event >= Capture::CLOCK && event <= Capture::LIFECYCLE && count == arity[event],
			"Invalid event header or ordering at event " + std::to_string(ordinal));
		total += 2 + count;
		require(total <= declared, "Event count exceeds declared prefix");
		require(!pendingActivities || event == Capture::ACTIVITY, "Missing activity row");
		require(!needsOutput || event == Capture::OUTPUT, "Missing output observation");
		std::vector<long double> v;
		for (size_t i = 0; i < count; ++i)
		{
			std::string token;
			require(static_cast<bool>(row >> token), "Missing event field");
			v.push_back(number(token));
		}
		std::string extra;
		require(!(row >> extra), "Extra event field");
		switch (event)
		{
		case Capture::CLOCK:
			integer(v[2], 5);
			clock.advance(v[0], integer(v[1], 1));
			break;
		case Capture::CONFIG:
			compare(ordinal, "configure.clock", v[0], clock.seconds());
			state.configure(configFrom(v), clock.seconds());
			configured = true;
			break;
		case Capture::ACTIVITIES:
			require(configured, "Activity schedule before configuration");
			pendingActivities = integer(v[0], Capture::VALUE_LIMIT / 4);
			activities.clear();
			prepared = pendingActivities == 0;
			if (prepared) state.setActivities(activities);
			break;
		case Capture::ACTIVITY:
			require(pendingActivities && std::isfinite(v[0]) && std::isfinite(v[1]) && v[1] >= v[0], "Invalid activity");
			activities.push_back({(double)v[0], (double)v[1]});
			if (--pendingActivities == 0)
			{
				state.setActivities(activities);
				prepared = true;
			}
			break;
		case Capture::ADVANCE:
			require(prepared, "Advance before activity preparation");
			state.advance(v[0], v[1]);
			break;
		case Capture::PAUSE:
			state.pause(integer(v[0], 1));
			break;
		case Capture::HIT:
		{
			require(prepared, "Hit before activity preparation");
			const auto result = state.sampleMap(v[0], {(double)v[1], (double)v[2]}, integer(v[3], 1), v[4], v[5], clock.seconds());
			const auto &used = state.getLastEvaluation();
			compare(ordinal, "hit.accepted", integer(v[6], 1), result.accepted);
			compare(ordinal, "hit.cue", v[7], result.cue);
			compare(ordinal, "hit.halfWidthMS", v[8], result.halfWidthMS);
			compare(ordinal, "learner.samples", v[9], state.getSamples());
			compare(ordinal, "learner.meanMS", v[10], state.getBaselineMS());
			compare(ordinal, "learner.varianceMS2", v[11], state.getVarianceMS2());
			compare(ordinal, "learner.activeMS", v[12], state.getActiveMS());
			compare(ordinal, "lastHit.phase", v[13], used.phase);
			compare(ordinal, "lastHit.silentLowerMapMS", v[14], used.silentMapMS.lower);
			compare(ordinal, "lastHit.silentUpperMapMS", v[15], used.silentMapMS.upper);
			if (result.accepted)
			{
				history.recordAcceptedHit(clock.seconds(), static_cast<double>(v[0]) / static_cast<double>(v[2]));
				needsOutput = true;
				++hits;
			}
			break;
		}
		case Capture::OUTPUT:
			require(needsOutput, "Output observation without accepted hit");
			integer(v[0], OsuTimingAudioEvaluation::AUDIO_DISABLED);
			integer(v[3], 1); integer(v[4], 1);
			needsOutput = false;
			break;
		case Capture::MARK:
		{
			require(between(v[2], 0.1L - 1e-8L, 60), "Invalid Recent duration");
			const auto moments = history.getMoments(clock.seconds(), v[2]);
			compare(ordinal, "mark.playSeconds", v[1], clock.seconds());
			compare(ordinal, "mark.recent.count", v[3], moments.count);
			compare(ordinal, "mark.recent.meanMS", v[4], moments.meanMS);
			compare(ordinal, "mark.recent.varianceMS2", v[5], moments.varianceMS2);
			compare(ordinal, "mark.recent.truncated", integer(v[6], 1), history.truncated(clock.seconds(), v[2]));
			++marks;
			break;
		}
		case Capture::LIFECYCLE:
			require(integer(v[0], Capture::RELOAD) >= Capture::LOADING, "Invalid lifecycle annotation");
			break;
		}
		last = event;
	}
	require(hash(field(input, "checksum"), 16) && input.peek() == EOF
		&& total == declared && !needsOutput && !pendingActivities && hits && marks && last == Capture::MARK,
		"Incomplete prefix, trailing data, or no accepted timing observations before final mark");
	std::cout << "REPLAY source=" << source << " map=" << map << " events=" << ordinal << " accepted_hits=" << hits << " marks=" << marks
		<< "\nCOMPLETE capture failures=0\n";
}

int main(int argc, char **argv)
{
	try
	{
		require(argc == 3, "Expected capture file and source revision");
		std::ifstream input(argv[1], std::ios::binary);
		require(input.good(), "Could not open capture");
		replay(input, argv[2]);
		return 0;
	}
	catch (const std::exception &error)
	{
		std::cerr << error.what() << '\n';
		return 1;
	}
}

// Timing-only settings and profile format. No engine or audio dependency.
#ifndef OSUTIMINGAUDIOSETTINGS_H
#define OSUTIMINGAUDIOSETTINGS_H

#include <cmath>
#include <cstdlib>
#include <map>
#include <sstream>
#include <string>
#include <vector>

class OsuTimingAudioSettings
{
public:
	enum Type { BOOLEAN, NUMBER, INTEGER, FILENAME };
	struct Spec { const char *name, *label; Type type; long double min, max; bool restarts; };
	typedef std::map<std::string, std::string> Values;
	typedef std::map<std::string, Values> Profiles;
	static const std::vector<Spec> &specs()
	{
		static const std::vector<Spec> list = {
			{"osu_timing_audio", "Enable timing audio (off resets)", BOOLEAN, 0, 1, true},
			{"osu_timing_audio_muted", "Mute cues (keep learning)", BOOLEAN, 0, 1, false},
			{"osu_timing_audio_recent", "Recent reference (off = Beatmap)", BOOLEAN, 0, 1, false},
			{"osu_timing_audio_target", "Beatmap target (-3..3)", NUMBER, -3, 3, false},
			{"osu_timing_audio_deadzone_mode", "Silent width", INTEGER, 0, 2, false},
			{"osu_timing_audio_deadzone", "Fixed / startup half-width (ms)", NUMBER, 0, 1000, false},
			{"osu_timing_audio_deadzone_fraction", "Map-relative fraction (0.2 = 20%)", NUMBER, 0, 10, false},
			{"osu_timing_audio_deadzone_adaptive_scale", "Adaptive variability multiplier", NUMBER, 0, 10, false},
			{"osu_timing_audio_deadzone_adaptive_min", "Adaptive minimum fraction of 300", NUMBER, 0, 10, false},
			{"osu_timing_audio_deadzone_adaptive_max", "Adaptive maximum fraction of 300", NUMBER, 0, 10, false},
			{"osu_timing_audio_fixed_hits", "Use hit-count adaptation (off = time)", BOOLEAN, 0, 1, true},
			{"osu_timing_audio_half_life_seconds", "Time half-life (active seconds)", NUMBER, 0.001L, 3600, true},
			{"osu_timing_audio_half_life_hits", "Hit-count half-life (hits)", NUMBER, 0.001L, 100000, true},
			{"osu_timing_audio_silent_startup", "Silent eight-hit Recent startup", BOOLEAN, 0, 1, false},
			{"osu_timing_audio_require_300", "Gate: baseline inside actual 300", BOOLEAN, 0, 1, false},
			{"osu_timing_audio_restart", "Restart after breaks (off = retain)", BOOLEAN, 0, 1, false},
			{"osu_timing_audio_exclude_activity", "Long bodies/spinners count as breaks", BOOLEAN, 0, 1, true},
			{"osu_timing_audio_break_seconds", "Break threshold (real-play seconds)", NUMBER, 0.001L, 3600, true},
			{"osu_timing_audio_volume", "Cue gain (0..1)", NUMBER, 0, 1, false},
			{"osu_timing_audio_early_sound", "Early cue filename inside sounds/", FILENAME, 0, 0, false},
			{"osu_timing_audio_late_sound", "Late cue filename inside sounds/", FILENAME, 0, 0, false},
			{"osu_timing_audio_trace", "Diagnostic logging (adds overhead)", BOOLEAN, 0, 1, false}
		};
		return list;
	}

	static bool number(const std::string &text, long double &value)
	{
		if (text.empty()) return false;
		if (text.find_first_not_of("+-0123456789.eE") != std::string::npos) return false;
		char *end = NULL;
		value = std::strtold(text.c_str(), &end);
		return end != text.c_str() && *end == '\0' && std::isfinite(value);
	}
	// Replace standalone timing lines only. Preserve compound lines verbatim:
	// removing a semicolon changes the console's recursive whitespace handling.
	// Current callback-free timing values are written after these retained lines,
	// so authoritative saved values take precedence over old compound assignments.
	static std::string retainOtherConfigStatements(const std::string &line)
	{
		const size_t comment = line.find("//");
		const std::string commands = line.substr(0, comment);
		if (commands.find(';') != std::string::npos) return line;
		const size_t nameStart = !commands.empty() && commands[0] == ' ' ? 1 : 0;
		const size_t space = commands.find(' ', nameStart);
		const std::string name = commands.substr(nameStart, space == std::string::npos ? space : space - nameStart);
		for (const Spec &spec : specs())
			if (name == spec.name) return comment == std::string::npos ? "" : line.substr(comment);
		return line;
	}
	static bool safeText(const std::string &text)
	{
		for (unsigned char c : text) if (c < 32 || c == 127) return false;
		return true;
	}
	static std::string validate(const Values &values)
	{
		if (values.size() != specs().size()) return "Incomplete or unknown timing settings; nothing applied.";
		for (const Spec &spec : specs())
		{
			const auto found = values.find(spec.name);
			if (found == values.end()) return std::string("Missing setting: ") + spec.label;
			const std::string &text = found->second;
			if (text.empty() || text.size() > 1024 || !safeText(text)) return std::string("Invalid value: ") + spec.label;
			if (spec.type == FILENAME)
			{
				// Options save raw name/value config lines. The engine treats these
				// as command/comment delimiters and has no general quote escaping.
				if (text.find(';') != std::string::npos || text.find("//") != std::string::npos)
					return "Cue filenames cannot contain ; or // (config syntax).";
				if (text[0] == '/' || text[0] == '\\' || text.find(':') != std::string::npos) return "Cue filenames must be relative to sounds/.";
				std::string path = text;
				for (char &c : path) if (c == '\\') c = '/';
				if (("/" + path + "/").find("/../") != std::string::npos) return "Cue filenames must stay inside sounds/.";
				continue;
			}
			long double value;
			if (!number(text, value) || value < spec.min || value > spec.max
				|| ((spec.type == BOOLEAN || spec.type == INTEGER) && std::floor(value) != value))
				return std::string("Out of range: ") + spec.label;
		}
		long double low = 0, high = 0;
		number(values.at("osu_timing_audio_deadzone_adaptive_min"), low);
		number(values.at("osu_timing_audio_deadzone_adaptive_max"), high);
		return low <= high ? "" : "Adaptive maximum must be at least its minimum; nothing applied.";
	}

	static bool validProfileName(const std::string &name)
	{
		return !name.empty() && name.size() <= 128 && safeText(name)
			&& name.find_first_of("[]") == std::string::npos
			&& name.find_first_not_of(' ') != std::string::npos;
	}
	static std::string encode(const Profiles &profiles)
	{
		std::ostringstream out;
		out << "timing-audio-profiles 1\n";
		for (const auto &profile : profiles)
		{
			out << '[' << profile.first << "]\n";
			for (const Spec &spec : specs()) out << spec.name << ' ' << profile.second.at(spec.name) << '\n';
		}
		return out.str();
	}
	static std::string decode(const std::string &text, Profiles &output)
	{
		if (text.size() > 1024 * 1024) return "Profile file is too large.";
		std::istringstream in(text);
		std::string line;
		if (!std::getline(in, line)) return "Unknown profile format; nothing applied.";
		if (!line.empty() && line.back() == '\r') line.pop_back();
		if (line != "timing-audio-profiles 1") return "Unknown profile format; nothing applied.";
		Profiles result;
		Values *current = NULL;
		while (std::getline(in, line))
		{
			if (!line.empty() && line.back() == '\r') line.pop_back();
			if (line.empty()) continue;
			if (line[0] == '[' && line.back() == ']')
			{
				const std::string name = line.substr(1, line.size() - 2);
				if (!validProfileName(name) || result.count(name) || result.size() >= 100) return "Invalid or duplicate profile name.";
				current = &result[name];
			}
			else
			{
				const auto split = line.find(' ');
				if (current == NULL || split == std::string::npos) return "Malformed profile entry.";
				if (!current->emplace(line.substr(0, split), line.substr(split + 1)).second) return "Duplicate profile setting.";
			}
		}
		for (const auto &profile : result)
		{
			const std::string error = validate(profile.second);
			if (!error.empty()) return error;
		}
		output.swap(result);
		return "";
	}

	// Engine adapter: capture/apply only these settings, never arbitrary commands.
	static Values capture(bool defaults = false);
	static std::string apply(const Values &values);
	static std::string readProfiles(Profiles &profiles);
	static std::string writeProfiles(const Profiles &profiles);
};

#endif

#include "../src/App/Osu/OsuTimingAudioSettings.h"
#include <cstdio>
#include <cstdlib>
#include <set>

#define CHECK(condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); std::exit(1); } } while (false)
typedef OsuTimingAudioSettings Settings;

static Settings::Values values()
{
	Settings::Values result;
	for (const auto &spec : Settings::specs())
	{
		if (spec.type == Settings::FILENAME) result[spec.name] = "timing-early.wav";
		else if (spec.type == Settings::BOOLEAN) result[spec.name] = "0";
		else if (spec.type == Settings::INTEGER) result[spec.name] = std::to_string((int)spec.min);
		else result[spec.name] = std::to_string((double)spec.min);
	}
	result["osu_timing_audio_target"] = "0.8";
	result["osu_timing_audio_deadzone_fraction"] = "0.2";
	result["osu_timing_audio_deadzone_adaptive_min"] = "0.1";
	result["osu_timing_audio_deadzone_adaptive_max"] = "1";
	result["osu_timing_audio_half_life_seconds"] = "5.123456789012";
	result["osu_timing_audio_early_sound"] = u8"custom/音 cue.wav";
	result["osu_timing_audio_late_sound"] = "custom\\low cue.wav";
	return result;
}

int main()
{
	const auto good = values(); CHECK(Settings::validate(good).empty());
	CHECK(Settings::retainOtherConfigStatements("osu_folder_sub_songs osu_timing_audio_practice/") == "osu_folder_sub_songs osu_timing_audio_practice/");
	for (const char *compound : {"osu_folder_sub_songs Practice/; osu_timing_audio 0",
		"osu_folder_sub_songs Practice/; osu_timing_audio 0 // keep",
		"osu_timing_audio 0; osu_folder_sub_songs Practice/",
		"osu_timing_audio 0; osu_timing_audio_muted 1 // keep this note",
		"  osu_end_delay_time 2000; osu_timing_audio 0"})
		CHECK(Settings::retainOtherConfigStatements(compound) == compound);
	CHECK(Settings::retainOtherConfigStatements("osu_timing_audio 0").empty());
	CHECK(Settings::retainOtherConfigStatements(" osu_timing_audio 0").empty());
	CHECK(Settings::retainOtherConfigStatements("osu_timing_audio 0 // keep; note") == "// keep; note");
	CHECK(Settings::retainOtherConfigStatements("echo cue; osu_timing_audio 0") == "echo cue; osu_timing_audio 0");
	CHECK(Settings::retainOtherConfigStatements("osu_folder_sub_songs echo; osu_timing_audio 0") == "osu_folder_sub_songs echo; osu_timing_audio 0");
	CHECK(Settings::retainOtherConfigStatements("osu_timing_audio_extra 1 // osu_timing_audio 0") == "osu_timing_audio_extra 1 // osu_timing_audio 0");
	CHECK(Settings::retainOtherConfigStatements("  osu_timing_audio 0") == "  osu_timing_audio 0");
	CHECK(Settings::retainOtherConfigStatements("osu_timing_audio 0;osu_skin_random 1; osu_timing_audio_recent 0") == "osu_timing_audio 0;osu_skin_random 1; osu_timing_audio_recent 0");
	CHECK(Settings::timingCompoundCommandNames("osu_end_delay_time 2000; osu_timing_audio_early_sound monitor.wav")
		== std::vector<std::string>({"osu_end_delay_time", "osu_timing_audio_early_sound"}));
	CHECK(Settings::timingCompoundCommandNames("  osu_end_delay_time 2000; osu_timing_audio 0")
		== std::vector<std::string>({"osu_end_delay_time", "osu_timing_audio"}));
	CHECK(Settings::timingCompoundCommandNames("osu_timing_audio 0; monitor 1")
		== std::vector<std::string>({"osu_timing_audio", "monitor"}));
	CHECK(Settings::timingCompoundCommandNames("osu_timing_audio 0 // ; monitor 1").empty());
	CHECK(Settings::timingCompoundCommandNames("echo keep; osu_timing_audio 0") == std::vector<std::string>({"echo"}));
	CHECK(Settings::timingCompoundCommandNames("osu_end_delay_time 2000; osu_timing_audio_early_sound echo monitor.wav")
		== std::vector<std::string>({"osu_end_delay_time"}));
	CHECK(Settings::timingCompoundCommandNames("osu_end_delay_time 2000; osu_timing_audio 0 // echo")
		== std::vector<std::string>({"osu_end_delay_time", "osu_timing_audio"}));
	CHECK(Settings::timingCompoundCommandNames("osu_timing_audio_extra 0; monitor 1").empty());
	std::set<std::string> names;
	for (const auto &spec : Settings::specs())
	{
		CHECK(names.insert(spec.name).second);
		auto invalid = good; invalid.erase(spec.name); CHECK(!Settings::validate(invalid).empty());
		invalid = good; invalid[spec.name] = ""; CHECK(!Settings::validate(invalid).empty());
		invalid = good; invalid[spec.name] = "line\nbreak"; CHECK(!Settings::validate(invalid).empty());
		if (spec.type != Settings::FILENAME)
		{
			for (const char *bad : {"NaN", "inf", "1.0 trailing", "not a number", "100000000000000"})
			{
				invalid = good; invalid[spec.name] = bad; CHECK(!Settings::validate(invalid).empty());
			}
			if (spec.type == Settings::BOOLEAN || spec.type == Settings::INTEGER)
			{
				invalid = good; invalid[spec.name] = "0.5"; CHECK(!Settings::validate(invalid).empty());
			}
		}
	}
	for (const char *path : {"../outside.wav", "sub/../outside.wav", "C:\\outside.wav", "/outside.wav"})
	{
		auto invalid = good; invalid["osu_timing_audio_early_sound"] = path; CHECK(!Settings::validate(invalid).empty());
	}
	// The engine saves these values as unquoted config lines, including while
	// disabled. A profile must not carry filenames that become config syntax.
	for (const char *key : {"osu_timing_audio_early_sound", "osu_timing_audio_late_sound"})
		for (const char *path : {"click;soft.wav", "custom//click.wav", "timing-early.wav;osu_skin_random 1"})
		{
			auto unsafe = good; unsafe["osu_timing_audio"] = "0"; unsafe[key] = path;
			CHECK(!Settings::validate(unsafe).empty());
			Settings::Profiles incoming; incoming["Unsafe filename"] = unsafe;
			Settings::Profiles retained; retained["Keep"] = good; const auto before = retained;
			CHECK(!Settings::decode(Settings::encode(incoming), retained).empty() && retained == before);
		}
	auto invalid = good; invalid["osu_timing_audio_deadzone_adaptive_max"] = "0.09"; CHECK(!Settings::validate(invalid).empty());
	invalid = good; invalid.erase("osu_timing_audio_target"); invalid["osu_folder"] = "elsewhere";
	CHECK(!Settings::validate(invalid).empty());
	CHECK(Settings::validProfileName(u8"Myuzs 対策"));
	CHECK(!Settings::validProfileName("   ") && !Settings::validProfileName("[bad]") && !Settings::validProfileName("bad\nname"));

	Settings::Profiles profiles; profiles[u8"Myuzs 対策"] = good; profiles["Recent quiet"] = good;
	profiles["Recent quiet"]["osu_timing_audio_recent"] = "1";
	profiles["Recent quiet"]["osu_timing_audio_muted"] = "1";
	const auto text = Settings::encode(profiles);
	Settings::Profiles decoded; CHECK(Settings::decode(text, decoded).empty() && decoded == profiles);
	std::string crlf;
	for (char c : text) { if (c == '\n') crlf += '\r'; crlf += c; }
	CHECK(Settings::decode(crlf, decoded).empty() && decoded == profiles);
	for (const auto &bad : {std::string("timing-audio-profiles 9\n"), text + "[Recent quiet]\n", text + "osu_folder private\n",
		std::string("timing-audio-profiles 1\n[partial]\nosu_timing_audio 1\n"), std::string(1024 * 1024 + 1, 'x')})
	{
		const auto before = decoded;
		CHECK(!Settings::decode(bad, decoded).empty() && decoded == before);
	}
	const std::string duplicate = text + "osu_timing_audio_muted 1\n";
	CHECK(!Settings::decode(duplicate, decoded).empty() && decoded == profiles);
	CHECK(decoded.at(u8"Myuzs 対策").at("osu_timing_audio_half_life_seconds") == "5.123456789012");
	std::string legacy = "timing-audio-profiles 1\n[Older]\n";
	for (const auto &spec : Settings::specs())
		if (spec.legacyDefault == NULL) legacy += std::string(spec.name) + " " + good.at(spec.name) + "\n";
	decoded["Older"] = good;
	decoded["Older"]["osu_timing_audio_idle_forgiveness"] = "1";
	decoded["Older"]["osu_timing_audio_adaptive_startup_maximum"] = "1";
	decoded["Older"]["osu_timing_audio_retain_failed_cue"] = "0";
	CHECK(Settings::decode(legacy, decoded).empty());
	const auto &older = decoded.at("Older");
	CHECK(older.at("osu_timing_audio_idle_forgiveness") == "0");
	CHECK(older.at("osu_timing_audio_adaptive_startup_maximum") == "0");
	CHECK(older.at("osu_timing_audio_retain_failed_cue") == "1");
	CHECK(older.at("osu_timing_audio_startup_average_hits") == "8");
	CHECK(older.at("osu_timing_audio_silent_startup_hits") == "8");
	CHECK(older.at("osu_timing_audio_idle_grace_seconds") == "1");
	CHECK(older.at("osu_timing_audio_idle_ramp_seconds") == "3");
	CHECK(older.at("osu_timing_audio_idle_recovery_hits") == "4");
	const auto beforeLegacy = decoded;
	CHECK(!Settings::decode(legacy + "osu_hud_hiterrorbar_timing_audio 1\n", decoded).empty() && decoded == beforeLegacy);
	const auto last = legacy.rfind('\n', legacy.size() - 2);
	CHECK(!Settings::decode(legacy.substr(0, last + 1), decoded).empty() && decoded == beforeLegacy);
	CHECK(Settings::retainOtherConfigStatements("osu_hud_hiterrorbar_timing_audio_recent_seconds 8 // my window") == "// my window");
	CHECK(Settings::retainOtherConfigStatements("osu_draw_hiterrorbar_top 1; osu_folder_sub_songs Practice/")
		== "osu_draw_hiterrorbar_top 1; osu_folder_sub_songs Practice/");
	std::puts("PASS: complete timing settings validation, exact Unicode/decimal profile roundtrip, CRLF and atomic malformed-input rejection");
}

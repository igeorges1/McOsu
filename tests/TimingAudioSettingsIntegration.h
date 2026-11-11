// Optional internal-event fixture extension. Use ONLY a throwaway runtime:
// MCOSU_TIMING_AUDIO_SETTINGS_DRIVER=1 writes cfg/timing-audio-profiles.cfg and
// deliberately tests malformed files/recovery/write failures there. It refuses
// an existing profile file and requires timing-audio-settings-test-scratch.txt
// in the disposable runtime. Normal game builds do not include this driver.
#ifndef TIMINGAUDIOSETTINGSINTEGRATION_H
#define TIMINGAUDIOSETTINGSINTEGRATION_H

#include "OsuTimingAudioSettings.h"
#include "OsuOptionsMenu.h"
#include "Environment.h"
#include "Console.h"
#include <fstream>

static bool timingAudioSettingsIntegration(Osu *osu, size_t index, bool ready)
{
	if (std::getenv("MCOSU_TIMING_AUDIO_SETTINGS_DRIVER") == NULL || !ready) return false;
	typedef OsuTimingAudioSettings Settings;
	static bool probed = false, muted = false, unmuted = false, changedEstimator = false, disabled = false, reenabled = false;
	static double disabledAt = 0;
	static unsigned failures = 0;
	auto check = [](bool condition, const char *label) {
		if (!condition) { ++failures; debugLog("TimingSettings: FAIL %s\n", label); }
	};
	if (!probed)
	{
		probed = true;
		if (!env->fileExists("timing-audio-settings-test-scratch.txt"))
		{
			debugLog("TimingSettings: REFUSE missing explicit scratch marker\n"); engine->shutdown(); return true;
		}
		if (env->fileExists("cfg/timing-audio-profiles.cfg") || env->fileExists("cfg/timing-audio-profiles.cfg.bak"))
		{
			debugLog("TimingSettings: REFUSE existing profiles; use a throwaway runtime\n"); engine->shutdown(); return true;
		}
		const auto original = Settings::capture();
		check(Settings::validate(original).empty() && original.size() == Settings::specs().size(), "actual inventory");
		check(Settings::validate(Settings::capture(true)).empty(), "actual engine defaults");
		for (const auto &setting : Settings::capture(true)) debugLog("TimingSettings: DEFAULT %s=%s\n", setting.first.c_str(), setting.second.c_str());
		const char *untouched[] = {"osu_folder", "osu_skin", "osu_volume_master", "osu_volume_music", "osu_volume_effects"};
		std::vector<std::string> unrelated;
		for (const char *key : untouched) unrelated.push_back(convar->getConVarByName(key)->getString().toUtf8());
		auto values = original;
		values["osu_timing_audio_target"] = "0.8"; values["osu_timing_audio_deadzone_mode"] = "1";
		values["osu_timing_audio_deadzone_fraction"] = "0.2"; values["osu_timing_audio_volume"] = "0.65";
		check(Settings::apply(values).empty() && Settings::capture() == values, "actual apply and exact readback");
		Settings::Profiles profiles; profiles["Trial A"] = values;
		check(Settings::writeProfiles(profiles).empty(), "save profile");
		Settings::Profiles loaded;
		check(Settings::readProfiles(loaded).empty() && loaded == profiles, "disk roundtrip");
		profiles["Trial B"] = original;
		check(Settings::writeProfiles(profiles).empty(), "multiple named profiles");
		check(Settings::apply(original).empty() && Settings::capture() == original, "restore whole timing batch");
		auto invalid = values; invalid["osu_timing_audio_target"] = "4";
		check(!Settings::apply(invalid).empty() && Settings::capture() == original, "invalid batch changes nothing");
		invalid = values; invalid["osu_timing_audio_late_sound"] = "timing-intentionally-missing.wav";
		check(!Settings::apply(invalid).empty() && Settings::capture() == original, "unloadable cue changes nothing");
		const UString skinRandom = convar->getConVarByName("osu_skin_random")->getString();
		for (const char *key : {"osu_timing_audio_early_sound", "osu_timing_audio_late_sound"})
			for (const char *path : {"click;soft.wav", "custom//click.wav", "timing-early.wav;osu_skin_random 1"})
			{
				invalid = values; invalid["osu_timing_audio"] = "0"; invalid[key] = path;
				check(!Settings::apply(invalid).empty() && Settings::capture() == original
					&& convar->getConVarByName("osu_skin_random")->getString() == skinRandom, "config syntax rejected without timing or unrelated changes");
			}
		{
			std::ofstream bad("cfg/timing-audio-profiles.cfg", std::ios::binary | std::ios::trunc); bad << "malformed profile\n";
		}
		const auto beforeRead = loaded;
		check(!Settings::readProfiles(loaded).empty() && loaded == beforeRead && Settings::capture() == original, "malformed file changes nothing");
		check(Settings::writeProfiles(profiles).empty() && Settings::writeProfiles(profiles).empty(), "restore valid file and backup");
		check(env->deleteFile("cfg/timing-audio-profiles.cfg"), "simulate interrupted replace");
		check(Settings::readProfiles(loaded).empty() && loaded == profiles, "recover last good backup");
		check(Settings::writeProfiles(profiles).empty(), "publish after recovery");
		check(env->createDirectory("cfg/timing-audio-profiles.cfg.tmp"), "create write-failure fixture");
		check(!Settings::writeProfiles(profiles).empty(), "report write failure");
		check(Settings::readProfiles(loaded).empty() && loaded == profiles, "write failure keeps previous profiles");
		for (size_t i = 0; i < unrelated.size(); ++i)
			check(unrelated[i] == convar->getConVarByName(untouched[i])->getString().toUtf8(), "unrelated setting preserved");
		// Each independent case starts with only its input. Checking only a final
		// folder value could hide the loss of an earlier, overridden statement.
		struct SaveCase { const char *line, *folder; int delay; };
		const SaveCase saveCases[] = {
			{"osu_folder_sub_songs osu_timing_audio_practice/", "osu_timing_audio_practice/", 750},
			{"osu_folder_sub_songs Practice/; osu_timing_audio 0", "Practice/", 750},
			{"osu_folder_sub_songs Commented/; osu_timing_audio 0 // preserve this note", "Commented/", 750},
			{"  osu_end_delay_time 2000; osu_timing_audio 0", "Songs/", 2000},
			{"osu_end_delay_time 2000; osu_timing_audio_early_sound monitor.wav", "Songs/", 2000},
			{"osu_folder_sub_songs SkinCollision/; osu_timing_audio_early_sound osu_skin.wav", "SkinCollision/", 750},
			{"osu_folder_sub_songs SortingCollision/; osu_timing_audio_early_sound osu_songbrowser_sortingtype.wav", "SortingCollision/", 750}
		};
		ConVar *endDelay = convar->getConVarByName("osu_end_delay_time");
		ConVar *songsFolder = convar->getConVarByName("osu_folder_sub_songs");
		const UString oldDelay = endDelay->getString(), oldSongsFolder = songsFolder->getString();
		for (bool enabled : {false, true})
		{
			auto expected = original; expected["osu_timing_audio"] = enabled ? "1" : "0";
			check(Settings::apply(expected).empty(), "apply before config preservation save");
			for (const SaveCase &test : saveCases)
			{
				{ std::ofstream input("cfg/osu.cfg"); input << test.line << "\n"; }
				for (int round = 0; round < 2; ++round)
				{
					osu->getOptionsMenu()->save();
					// Reload only these callback-free fields from the ACTUAL saved file.
					// Replaying unrelated window/audio/skin callbacks would disturb the
					// fixture. Preserve the statements and their original save order.
					std::ifstream saved("cfg/osu.cfg");
					std::ofstream probe("cfg/timing-settings-save-probe.cfg");
					std::string line;
					while (std::getline(saved, line))
						if (line.find("osu_end_delay_time ") == 0 || line.find("  osu_end_delay_time ") == 0
							|| line.find("osu_folder_sub_songs ") == 0 || line.find("osu_timing_audio ") == 0
							|| line.find("osu_timing_audio_") == 0)
							probe << line << "\n";
					probe.close();
					// Simulate a fresh process with every timing value different. Otherwise
					// an omitted assignment could pass by retaining its pre-save value.
					for (const auto &spec : Settings::specs())
					{
						std::string poison;
						if (spec.type == Settings::BOOLEAN) poison = expected.at(spec.name) == "1" ? "0" : "1";
						else if (spec.type == Settings::FILENAME)
							poison = expected.at(spec.name) == "__reload_unset__.wav" ? "__other_unset__.wav" : "__reload_unset__.wav";
						else
						{
							long double value = 0; Settings::number(expected.at(spec.name), value);
							poison = std::to_string((double)(value == spec.min ? spec.max : spec.min));
						}
						convar->getConVarByName(spec.name)->setValue(UString(poison.c_str()));
					}
					const auto poisoned = Settings::capture();
					for (const auto &spec : Settings::specs()) check(poisoned.at(spec.name) != expected.at(spec.name), "reload precondition changes every timing value");
					endDelay->setValue(750.0f); songsFolder->setValue("Songs/");
					Console::execConfigFile("timing-settings-save-probe");
					check(endDelay->getInt() == test.delay && songsFolder->getString() == UString(test.folder),
						"actual save/parser reload preserves unrelated compound values");
					check(Settings::capture() == expected, "authoritative timing settings win after retained compounds");
					endDelay->setValue(oldDelay); songsFolder->setValue(oldSongsFolder);
				}
			}
		}
		check(Settings::apply(original).empty(), "restore enabled settings after config preservation");
		osu->getOptionsMenu()->save(); // same persistence route used by closing options
		debugLog("TimingSettings: PROBE_DONE fields=%u profiles=%u failures=%u\n", (unsigned)original.size(), (unsigned)profiles.size(), failures);
		if (failures != 0) engine->shutdown();
		return true;
	}
	if (!muted && index >= 2)
	{
		muted = true; auto values = Settings::capture(); values["osu_timing_audio_muted"] = "1";
		check(Settings::apply(values).empty(), "mute apply"); debugLog("TimingSettings: MUTE index=%u\n", (unsigned)index); return true;
	}
	if (!unmuted && index >= 4)
	{
		unmuted = true; auto values = Settings::capture(); values["osu_timing_audio_muted"] = "0";
		check(Settings::apply(values).empty(), "unmute apply"); debugLog("TimingSettings: UNMUTE index=%u\n", (unsigned)index); return true;
	}
	if (!changedEstimator && index >= 6)
	{
		changedEstimator = true; auto values = Settings::capture(); values["osu_timing_audio_half_life_seconds"] = "2";
		check(Settings::apply(values).empty(), "estimator apply"); debugLog("TimingSettings: ESTIMATOR index=%u\n", (unsigned)index); return true;
	}
	if (!disabled && index >= 8)
	{
		disabled = true; disabledAt = engine->getTime(); auto values = Settings::capture(); values["osu_timing_audio"] = "0";
		check(Settings::apply(values).empty(), "disable apply"); debugLog("TimingSettings: DISABLE index=%u\n", (unsigned)index); return true;
	}
	if (disabled && !reenabled && engine->getTime() > disabledAt + .2)
	{
		reenabled = true; auto values = Settings::capture(); values["osu_timing_audio"] = "1";
		check(Settings::apply(values).empty(), "reenable apply"); debugLog("TimingSettings: REENABLE failures=%u\n", failures); return true;
	}
	return false;
}

#endif

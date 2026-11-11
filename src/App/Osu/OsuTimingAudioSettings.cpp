#include "OsuTimingAudioSettings.h"

#include "ConVar.h"
#include "Engine.h"
#include "Environment.h"
#include "ResourceManager.h"
#include "Sound.h"
#include <fstream>
#include <iterator>

OsuTimingAudioSettings::Values OsuTimingAudioSettings::capture(bool defaults)
{
	Values values;
	// Discover actual values instead of silently losing new timing controls.
	// validate()/the coverage check require a matching editor specification.
	static std::vector<ConVar*> timingVars;
	static size_t registrySize = (size_t)-1;
	const auto &registry = convar->getConVarArray();
	if (registrySize != registry.size())
	{
		timingVars.clear();
		for (ConVar *var : registry)
		{
			const std::string name = var->getName().toUtf8();
			if (var->hasValue() && (name == "osu_timing_audio" || name.find("osu_timing_audio_") == 0)) timingVars.push_back(var);
		}
		registrySize = registry.size();
	}
	for (ConVar *var : timingVars)
	{
		const std::string name = var->getName().toUtf8();
		if (var->getType() == ConVar::CONVAR_TYPE::CONVAR_TYPE_BOOL)
			values[name] = (defaults ? var->getDefaultFloat() > 0 : var->getBool()) ? "1" : "0";
		else if (var->getType() == ConVar::CONVAR_TYPE::CONVAR_TYPE_INT)
			values[name] = std::to_string(defaults ? (int)var->getDefaultFloat() : var->getInt());
		else values[name] = (defaults ? var->getDefaultString() : var->getString()).toUtf8();
	}
	return values;
}

std::string OsuTimingAudioSettings::apply(const Values &values)
{
	const std::string error = validate(values);
	if (!error.empty()) return error;
	// Check both resources before changing ANY setting. These short samples are
	// independent probes, never played; normal feedback keeps its own ownership.
	long double enabled = 0;
	number(values.at("osu_timing_audio"), enabled);
	if (enabled > 0)
	{
		for (const char *key : {"osu_timing_audio_early_sound", "osu_timing_audio_late_sound"})
		{
			Sound *sound = engine->getResourceManager()->loadSound(values.at(key).c_str(), "");
			const bool ready = sound != NULL && sound->isReady();
			if (sound != NULL) engine->getResourceManager()->destroyResource(sound);
			if (!ready) return std::string("Cannot load cue; nothing applied: ") + values.at(key);
		}
	}
	for (const Spec &spec : specs())
		if (convar->getConVarByName(spec.name, false) == NULL) return "Timing control is unavailable; nothing applied.";
	// All these ConVars have no callbacks. One UI event completes before the
	// next beatmap update reads the settings, so it observes one complete batch.
	for (const Spec &spec : specs()) convar->getConVarByName(spec.name)->setValue(UString(values.at(spec.name).c_str()));
	return "";
}

static const char *timingProfilesPath = "cfg/timing-audio-profiles.cfg";
static const char *timingProfilesBackup = "cfg/timing-audio-profiles.cfg.bak";
static const char *timingProfilesTemp = "cfg/timing-audio-profiles.cfg.tmp";

std::string OsuTimingAudioSettings::readProfiles(Profiles &profiles)
{
	const char *path = timingProfilesPath;
	if (!env->fileExists(path))
	{
		// A crash between the two rename operations leaves the last good backup.
		if (env->fileExists(timingProfilesBackup)) path = timingProfilesBackup;
		else { profiles.clear(); return ""; }
	}
	std::ifstream in(path, std::ios::binary | std::ios::ate);
	if (!in.good() || in.tellg() < 0 || in.tellg() > 1024 * 1024) return "Cannot read profiles; existing settings kept.";
	in.seekg(0);
	const std::string text((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
	if (in.bad()) return "Profile read failed; existing settings kept.";
	return decode(text, profiles);
}

std::string OsuTimingAudioSettings::writeProfiles(const Profiles &profiles)
{
	if (profiles.size() > 100) return "At most 100 profiles can be saved.";
	for (const auto &profile : profiles)
	{
		if (!validProfileName(profile.first)) return "Use a nonempty name without brackets or control characters.";
		const std::string error = validate(profile.second);
		if (!error.empty()) return error;
	}
	const std::string text = encode(profiles);
	if (text.size() > 1024 * 1024) return "Profile file is too large.";
	{
		std::ofstream out(timingProfilesTemp, std::ios::binary | std::ios::trunc);
		if (!out.good()) return "Cannot save profiles; previous file kept.";
		out.write(text.data(), text.size());
		out.close();
		if (out.fail()) return "Profile write failed; previous file kept.";
	}
	const bool hadOriginal = env->fileExists(timingProfilesPath);
	if (hadOriginal)
	{
		if (env->fileExists(timingProfilesBackup) && !env->deleteFile(timingProfilesBackup)) return "Cannot update profile backup; previous file kept.";
		if (!env->renameFile(timingProfilesPath, timingProfilesBackup)) return "Cannot back up profiles; previous file kept.";
	}
	if (!env->renameFile(timingProfilesTemp, timingProfilesPath))
	{
		if (hadOriginal && !env->renameFile(timingProfilesBackup, timingProfilesPath))
			return "Save failed; last good profiles remain in cfg/timing-audio-profiles.cfg.bak.";
		return "Save failed; previous profiles kept.";
	}
	return "";
}

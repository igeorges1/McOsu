// Optional source-build test driver; not included by the normal game.
// In a development-only Engine.cpp, include this after Osu.h and call
// timingAudioIntegration(static_cast<Osu*>(m_app)) immediately after m_app->update().
// Set MCOSU_TIMING_AUDIO_DRIVER=1 and generate the fixture in the runtime first.
// Uses internal synthetic input, not OS input or Auto/Relax, to exercise the
// actual manual circle/head handlers. This does not prove hardware input latency.
#ifndef MCOSU_TIMING_AUDIO_INTEGRATION_H
#define MCOSU_TIMING_AUDIO_INTEGRATION_H
#include "Osu.h"
#include "OsuBeatmapStandard.h"
#include "OsuDatabaseBeatmap.h"
#include "OsuSongBrowser2.h"
#include "OsuHitObject.h"
#include "OsuSkin.h"
#include "ConVar.h"
#include "Mouse.h"
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <algorithm>

static void timingAudioIntegration(Osu *osu)
{
	if (std::getenv("MCOSU_TIMING_AUDIO_DRIVER") == NULL) return;
	static bool started = false;
	static size_t index = 0;
	static int clicks = 0, consumed = 0, heads = 0;
	static double start = 0;
	static double pausedAt = 0;
	static bool lifecycleDone = false, resumed = false;
	static bool skinRequested = false;
	static bool cuesSwitched = false;
	static int skipFrames = 0;
	static std::vector<double> frameMS;
	static std::vector<double> denseFrameMS;
	if (!started)
	{
		if (engine->getTime() < 1.0 || osu->isSkinLoading()) return;
		const char *skin = std::getenv("MCOSU_TIMING_AUDIO_SKIN");
		if (skin != NULL && !skinRequested)
		{
			skinRequested = true;
			convar->getConVarByName("osu_skin")->setValue(skin);
			osu->reloadSkin();
			return;
		}
		started = true;
		start = engine->getTime();
		frameMS.reserve(20000);
		denseFrameMS.reserve(2000);
		auto diff = new OsuDatabaseBeatmap(osu, "fixture/Songs/TimingAudio/experiment.osu", "fixture/Songs/TimingAudio/");
		if (!OsuDatabaseBeatmap::loadMetadata(diff))
		{
			debugLog("TimingIntegration: ERROR metadata\n");
			engine->shutdown();
			return;
		}
		osu->getSongBrowser()->onDifficultySelected(diff, true);
		debugLog("TimingIntegration: START auto=%i relax=%i skin=%s\n", osu->getModAuto(), osu->getModRelax(), osu->getSkin()->getName().toUtf8());
		return; // Let gameplay establish its clock before sending the first event.
	}
	if (skipFrames > 0) { --skipFrames; return; }
	frameMS.push_back(engine->getFrameTime() * 1000.0);
	auto beatmap = dynamic_cast<OsuBeatmapStandard*>(osu->getSelectedBeatmap());
	if (beatmap != NULL && beatmap->isWaiting() && beatmap->getCurMusicPosWithOffsets() >= 0) return;
	// Optional real resource changes: verify sound selection preserves learning,
	// including a missing replacement. Existing manual hit paths still do sampling.
	if (beatmap != NULL && !cuesSwitched && beatmap->getCurMusicPosWithOffsets() >= 3000)
	{
		const char *early = std::getenv("MCOSU_TIMING_AUDIO_SWITCH_EARLY");
		const char *late = std::getenv("MCOSU_TIMING_AUDIO_SWITCH_LATE");
		if (early != NULL || late != NULL)
		{
			cuesSwitched = true;
			if (early != NULL) convar->getConVarByName("osu_timing_audio_early_sound")->setValue(early);
			if (late != NULL) convar->getConVarByName("osu_timing_audio_late_sound")->setValue(late);
			debugLog("TimingIntegration: CUE_SWITCH\n");
			return;
		}
	}
	if (beatmap != NULL && !lifecycleDone && beatmap->getCurMusicPosWithOffsets() >= 6000)
	{
		if (std::getenv("MCOSU_TIMING_AUDIO_SEEK") != NULL)
		{
			lifecycleDone = true; beatmap->seekMS(31000); index = 0;
			const auto &objects = beatmap->getHitObjectsPointer();
			while (index < objects.size() && objects[index]->getTime() <= 31000) ++index;
			debugLog("TimingIntegration: SEEK index=%u\n", (unsigned)index);
			return;
		}
		if (std::getenv("MCOSU_TIMING_AUDIO_RETRY") != NULL)
		{
			lifecycleDone = true; beatmap->restart(false); index = 0; skipFrames = 2;
			debugLog("TimingIntegration: RETRY\n");
			return;
		}
	}
	if (beatmap != NULL && std::getenv("MCOSU_TIMING_AUDIO_PAUSE") != NULL)
	{
		if (!lifecycleDone && beatmap->getCurMusicPosWithOffsets() >= 5400)
		{
			lifecycleDone = true; pausedAt = engine->getTime(); beatmap->pause(false);
			debugLog("TimingIntegration: PAUSE index=%u\n", (unsigned)index);
		}
		if (pausedAt > 0 && !resumed && engine->getTime() > pausedAt + 0.5)
		{
			resumed = true; beatmap->pause(false);
		}
		if (resumed && beatmap->isContinueScheduled())
		{
			engine->getMouse()->onPosChange(Vector2(-1000, -1000));
			beatmap->keyPressed1(false); beatmap->keyReleased1(false);
		}
	}
	if (beatmap != NULL && beatmap->getCurMusicPosWithOffsets() >= 18000 && beatmap->getCurMusicPosWithOffsets() < 22000)
		denseFrameMS.push_back(engine->getFrameTime() * 1000.0);
	if (beatmap != NULL && beatmap->isPlaying() && !beatmap->isLoading())
	{
		const auto &objects = beatmap->getHitObjectsPointer();
		while (index < objects.size())
		{
			auto object = objects[index];
			if (!object->isCircle() && !object->isSlider()) { ++index; continue; }
			const long error = std::getenv("MCOSU_TIMING_AUDIO_LATE_DEPARTURE") != NULL ? (object->getTime() == 2800 ? 100 : (object->getTime() == 5800 ? 12 : 0))
				: std::getenv("MCOSU_TIMING_AUDIO_EARLY_RETURN") != NULL && object->getTime() == 5700 ? -30
				: (object->getTime() >= 18000 && object->getTime() < 22000 ? 20 : ((int)index % 5 - 2) * 20);
			if (beatmap->getCurMusicPosWithOffsets() < object->getTime() + error) break;
			engine->getMouse()->onPosChange(beatmap->osuCoords2Pixels(object->getRawPosAt(object->getTime())) - engine->getMouse()->getOffset());
			std::vector<OsuBeatmap::CLICK> events(1);
			events[0].musicPos = object->getTime() + error;
			events[0].maniaColumn = 0;
			object->onClickEvent(events);
			++clicks;
			if (events.empty()) ++consumed;
			if (object->isSlider()) ++heads;
			++index;
		}
	}
	const char *durationText = std::getenv("MCOSU_TIMING_AUDIO_SECONDS");
	const double duration = durationText != NULL ? std::max(1.0, std::atof(durationText)) : 39.0;
	if (engine->getTime() - start > duration)
	{
		std::sort(frameMS.begin(), frameMS.end());
		double sum = 0;
		for (double value : frameMS) sum += value;
		debugLog("TimingIntegration: END clicks=%i consumed=%i heads=%i frames=%u mean=%.3fms p95=%.3fms max=%.3fms\n", clicks, consumed, heads, (unsigned)frameMS.size(), sum / frameMS.size(), frameMS[frameMS.size() * 95 / 100], frameMS.back());
		if (!denseFrameMS.empty())
		{
			std::sort(denseFrameMS.begin(), denseFrameMS.end());
			double denseSum = 0;
			for (double value : denseFrameMS) denseSum += value;
			debugLog("TimingIntegration: DENSE frames=%u mean=%.3fms p95=%.3fms max=%.3fms\n", (unsigned)denseFrameMS.size(), denseSum / denseFrameMS.size(), denseFrameMS[denseFrameMS.size() * 95 / 100], denseFrameMS.back());
		}
		debugLog("TimingIntegration: SCORE score=%llu 300=%i 100=%i misses=%i accuracy=%.6f\n", osu->getScore()->getScore(), osu->getScore()->getNum300s(), osu->getScore()->getNum100s(), osu->getScore()->getNumMisses(), osu->getScore()->getAccuracy());
		engine->shutdown();
	}
}

#endif

#ifndef OSUTIMINGAUDIOSETUP_H
#define OSUTIMINGAUDIOSETUP_H

#include "OsuTimingAudioEvaluation.h"
#include "OsuTimingAudioSettings.h"
#include <iomanip>
#include <locale>

namespace OsuTimingAudioSetup
{
	struct Summary { std::string reference, band, spread; };

	inline std::string number(double value)
	{
		if (!std::isfinite(value)) return "unavailable";
		std::ostringstream text;
		text.imbue(std::locale::classic());
		text << std::fixed << std::setprecision(2) << value;
		return text.str();
	}

	inline double spreadMS(const OsuTimingAudioView &view)
	{
		return view.speed > 0 ? (view.evaluation.spreadMapMS.upper - view.evaluation.spreadMapMS.lower) / (2 * view.speed)
			: std::numeric_limits<double>::quiet_NaN();
	}

	inline const char *bandLimit(const OsuTimingAudioView &view)
	{
		using Band = OsuTimingAudioView::BandStatus;
		if (view.evaluation.fixedFallback) return "fixed fallback";
		if (view.band.startupMaximum) return "startup maximum";
		if (view.band.limit == Band::MINIMUM) return "minimum clamp";
		if (view.band.limit == Band::MAXIMUM) return "maximum clamp";
		return "none";
	}

	inline Summary summarize(const OsuTimingAudioSettings::Values &applied, const OsuTimingAudioView &view)
	{
		using Evaluation = OsuTimingAudioEvaluation;
		const auto &evaluation = view.evaluation;
		long double mode = 0;
		OsuTimingAudioSettings::number(applied.at("osu_timing_audio_deadzone_mode"), mode);
		if (view.speed > 0) mode = view.bandMode;
		const char *width = mode >= 2 ? "Adaptive spread" : mode >= 1 ? "Map-relative" : "Fixed";
		const char *reference = applied.at("osu_timing_audio_recent") == "1" ? "Recent" : "Beatmap";
		Summary summary;
		summary.reference = std::string("Applied: ") + reference + " / " + width;
		switch (evaluation.phase)
		{
		case Evaluation::OFF: summary.band = "Silent band: audio off"; break;
		case Evaluation::WAITING: summary.band = "Silent band: waiting for gameplay"; break;
		case Evaluation::INVALID: summary.band = "Silent band: invalid reference or window"; break;
		case Evaluation::WARMUP: summary.band = "Silent band: warming up"; break;
		case Evaluation::GATED: summary.band = "Silent band: 300 gate active"; break;
		case Evaluation::ACTIVE:
			summary.band = "Half-width: " + number(view.band.resolvedHalfWidthMS) + " ms";
			if (view.band.limit != OsuTimingAudioView::BandStatus::NONE || evaluation.fixedFallback || view.band.startupMaximum)
				summary.band += std::string(" (") + bandLimit(view) + ")";
			if (view.band.idleActive && view.band.allowance > 0 && !view.band.startupMaximum)
				summary.band += " | idle " + number(view.band.allowance * 100) + "%";
			break;
		}
		const double spread = spreadMS(view);
		summary.spread = "Learned SD: " + number(spread);
		if (std::isfinite(spread)) summary.spread += " ms";
		if (view.speed > 0) summary.spread += " / " + std::to_string(view.band.learnedHits) + " hits";
		return summary;
	}

	inline const char *phase(OsuTimingAudioEvaluation::Phase value)
	{
		using E = OsuTimingAudioEvaluation;
		switch (value)
		{
		case E::OFF: return "off";
		case E::WAITING: return "waiting";
		case E::INVALID: return "invalid geometry or input";
		case E::WARMUP: return "warming up";
		case E::GATED: return "300 gate";
		case E::ACTIVE: return "active";
		}
		return "unavailable";
	}

	inline const char *output(OsuTimingAudioEvaluation::Output value)
	{
		using E = OsuTimingAudioEvaluation;
		switch (value)
		{
		case E::MUTED: return "muted";
		case E::CUE_UNAVAILABLE: return "cue unavailable";
		case E::PLAY_FAILED: return "playback request failed";
		case E::PLAYED: return "playback request succeeded";
		case E::NO_ISSUE: return "no cue requested";
		}
		return "unavailable";
	}

	inline std::string interval(const OsuTimingAudioEvaluation &evaluation)
	{
		if (!std::isfinite(evaluation.silentMapMS.lower) || !std::isfinite(evaluation.silentMapMS.upper))
			return "unavailable";
		return "[" + number(evaluation.silentMapMS.lower) + ", " + number(evaluation.silentMapMS.upper) + "] map ms";
	}

	inline std::string idleStatus(const OsuTimingAudioView::BandStatus &band)
	{
		if (!band.idleActive) return "inactive";
		if (band.learnedHits < 2) return band.startupMaximum ? "startup maximum" : "fixed startup";
		return number(band.allowance * 100) + "%";
	}

	inline std::string copyText(const OsuTimingAudioSettings::Values &applied, const OsuTimingAudioView &view,
		OsuTimingAudioView::Mode hudMode, bool draftPending)
	{
		const auto summary = summarize(applied, view);
		const auto &evaluation = view.evaluation;
		std::ostringstream text;
		text << "Timing audio setup (applied)\n"
			<< (draftPending ? "Unapplied editor changes are excluded.\n" : "The editor matches these values.\n")
			<< summary.reference << " | Beatmap target setting " << applied.at("osu_timing_audio_target") << " (judgement anchors)\n"
			<< summary.band << "\n"
			<< "Base half-width before limits " << number(view.band.baseHalfWidthMS)
			<< " ms; ordinary " << number(view.band.ordinaryHalfWidthMS)
			<< " ms; cap " << number(view.band.maximumHalfWidthMS)
			<< " ms; resolved before gating " << number(view.band.resolvedHalfWidthMS)
			<< " ms; limit or fallback " << bandLimit(view) << "\n"
			<< "Idle allowance " << idleStatus(view.band)
			<< "; current phase " << phase(evaluation.phase) << "; silent interval " << interval(evaluation) << "\n"
			<< "Playback " << (view.speed > 0 ? number(view.speed) + "x" : "unavailable") << "; 300 half-window "
			<< (view.speed > 0 ? number(view.window300MapMS) : "unavailable") << " map ms; reference "
			<< number(evaluation.referenceMapMS) << " map ms\n"
			<< summary.spread << " | widths and SD in real-play ms\n"
			<< "Learned mean " << number(view.speed > 0 ? evaluation.learnedMeanMapMS / view.speed
				: std::numeric_limits<double>::quiet_NaN()) << " real-play ms\n"
			<< "Counted play " << (view.speed > 0 ? number(view.playSeconds) : "unavailable")
			<< " s; learner clock " << (view.speed > 0 ? number(view.learnerSeconds) : "unavailable")
			<< " s; since last accepted hit in this generation " << number(view.secondsSinceHit) << " s\n"
			<< "Learning generation " << view.generation
			<< (view.pendingReset ? "; settings will reset learning on resume" : "") << "\n"
			<< "Cue mute status " << (evaluation.output == OsuTimingAudioEvaluation::MUTED ? "muted"
				: (view.speed > 0 ? "unmuted" : "unavailable")) << "\n"
			<< "Early active file " << (view.early.activeFile.empty() ? "none" : view.early.activeFile) << " (" << view.early.reason << ")\n"
			<< "Late active file " << (view.late.activeFile.empty() ? "none" : view.late.activeFile) << " (" << view.late.reason << ")\n"
			<< "Last hit evaluation " << phase(view.lastHit.phase) << "; interval " << interval(view.lastHit)
			<< "; cue " << (view.lastHit.classifiedCue < 0 ? "early" : view.lastHit.classifiedCue > 0 ? "late" : "silent")
			<< "; " << output(view.lastHit.output) << "\n"
			<< "HUD view " << OsuTimingAudioView::name(hudMode) << " (selected)"
			<< (view.recentTruncated ? "; Recent history is truncated" : "") << "\n\n";
		for (const auto &entry : applied)
			text << entry.first << " = " << entry.second << '\n';
		return text.str();
	}
}

#endif

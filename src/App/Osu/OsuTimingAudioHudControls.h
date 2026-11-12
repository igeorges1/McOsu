#ifndef OSUTIMINGAUDIOHUDCONTROLS_H
#define OSUTIMINGAUDIOHUDCONTROLS_H

#include <vector>

namespace OsuTimingAudioHudControls
{
	enum Group { TIMING, APPEARANCE, BAR };
	enum Kind { Toggle, View, Decimal, Precise, Integer, BarScale, URScale };
	struct Control { const char *name, *label; Group group; Kind kind; double min, max; const char *help; };

	inline const std::vector<Control> &controls()
	{
		static const std::vector<Control> list = {
			{"osu_hud_hiterrorbar_timing_audio", "Timing audio on hit error bar", TIMING, Toggle, 0, 1, "Needs timing audio and a visible hit error bar."},
			{"osu_hud_hiterrorbar_timing_audio_caption", "Timing status caption", TIMING, Toggle, 0, 1, "Show view, reference and availability above the bar."},
			{"osu_hud_hiterrorbar_timing_audio_markers_only", "Timing markers only", TIMING, Toggle, 0, 1, "Hide both intervals. The mean and reference tick switches still apply."},
			{"osu_hud_hiterrorbar_timing_audio_spread", "Statistics spread bracket", TIMING, Toggle, 0, 1, "Show one population standard deviation on each side of the chosen mean."},
			{"osu_hud_hiterrorbar_timing_audio_silent_band", "Audio silent band strip", TIMING, Toggle, 0, 1, "Show the exact current cue interval. Markers only hides this strip."},
			{"osu_hud_hiterrorbar_timing_audio_mean_tick", "Statistics mean tick", TIMING, Toggle, 0, 1, "Show the chosen view's mean when available and within the bar."},
			{"osu_hud_hiterrorbar_timing_audio_reference_tick", "Audio reference tick", TIMING, Toggle, 0, 1, "Show the actual cue target when available and within the bar."},
			{"osu_hud_hiterrorbar_timing_audio_view", "Timing Audio View", TIMING, View, 0, 3, "Audio estimate, recent observations, or the hypothetical next hit at the average or reference."},
			{"osu_hud_hiterrorbar_timing_audio_recent_seconds", "Recent window duration (s)", TIMING, Decimal, 0.1, 60, "Accepted hits within this many counted-play seconds. The latest 2048 hits are retained."},
			{"osu_hud_hiterrorbar_timing_audio_smooth_seconds", "Statistics animation duration (s)", TIMING, Decimal, 0, 1, "Smooths statistics only. Zero snaps to the latest measurement."},

			{"osu_hud_hiterrorbar_timing_audio_alpha", "Timing overlay opacity", APPEARANCE, Decimal, 0, 1, "Multiplies bar opacity."},
			{"osu_hud_hiterrorbar_timing_audio_caption_scale", "Timing caption scale", APPEARANCE, Decimal, 0.1, 2, "Relative to bar scale and capped to fit the screen."},
			{"osu_hud_hiterrorbar_timing_audio_stroke_scale", "Timing marker thickness scale", APPEARANCE, Decimal, 0.5, 3, "Scales stroke thickness and spacing."},
			{"osu_hud_hiterrorbar_timing_audio_band_r", "Silent band red", APPEARANCE, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_timing_audio_band_g", "Silent band green", APPEARANCE, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_timing_audio_band_b", "Silent band blue", APPEARANCE, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_timing_audio_reference_r", "Reference tick red", APPEARANCE, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_timing_audio_reference_g", "Reference tick green", APPEARANCE, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_timing_audio_reference_b", "Reference tick blue", APPEARANCE, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_timing_audio_statistics_r", "Statistics red", APPEARANCE, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_timing_audio_statistics_g", "Statistics green", APPEARANCE, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_timing_audio_statistics_b", "Statistics blue", APPEARANCE, Integer, 0, 255, "RGB channel (0-255)."},

			{"osu_draw_hiterrorbar", "Draw hit error bar", BAR, Toggle, 0, 1, "Required for the timing overlay."},
			{"osu_draw_hiterrorbar_ur", "Draw unstable rate", BAR, Toggle, 0, 1, "Shows unstable rate at the bottom bar."},
			{"osu_hud_hiterrorbar_showmisswindow", "Show miss window", BAR, Toggle, 0, 1, "Scale the bar to the miss window instead of the 50 window."},
			{"osu_hud_hiterrorbar_hide_during_spinner", "Hide bar during spinners", BAR, Toggle, 0, 1, "Hides the timing overlay with the bar."},
			{"osu_hiterrorbar_misaims", "Draw misaim entries", BAR, Toggle, 0, 1, "Draws misaims on the ordinary bar. Misaims do not enter the timing learner."},
			{"osu_hud_hiterrorbar_scale", "Hit error bar scale", BAR, BarScale, 0.01, 3, "Scales bar and caption."},
			{"osu_hud_hiterrorbar_ur_scale", "Unstable rate scale", BAR, URScale, 0.01, 3, "Scales the unstable-rate text."},
			{"osu_hud_hiterrorbar_alpha", "Whole bar opacity", BAR, Decimal, 0, 1, "Also dims the timing overlay."},
			{"osu_hud_hiterrorbar_bar_alpha", "Bar background opacity", BAR, Decimal, 0, 1, "Background judgement bands."},
			{"osu_hud_hiterrorbar_centerline_alpha", "Bar centerline opacity", BAR, Decimal, 0, 1, "Ordinary zero line."},
			{"osu_hud_hiterrorbar_entry_alpha", "Hit entry opacity", BAR, Decimal, 0, 1, "Ordinary hit and miss marks."},
			{"osu_hud_hiterrorbar_entry_additive", "Additive hit entry blending", BAR, Toggle, 0, 1, "Ordinary hit and miss marks."},
			{"osu_hud_hiterrorbar_ur_alpha", "Unstable rate opacity", BAR, Decimal, 0, 1, "Unstable-rate text."},
			{"osu_hud_hiterrorbar_max_entries", "Maximum hit entries", BAR, Integer, 0, 512, "Ordinary marks only; timing history has its own bound."},
			{"osu_hud_hiterrorbar_entry_hit_fade_time", "Hit entry fade (s)", BAR, Decimal, 0.01, 60, "Fade duration for 300, 100 and 50 marks."},
			{"osu_hud_hiterrorbar_entry_miss_fade_time", "Miss entry fade (s)", BAR, Decimal, 0.01, 60, "Fade duration for miss and misaim marks."},
			{"osu_hud_hiterrorbar_entry_miss_height_multiplier", "Miss entry height multiplier", BAR, Decimal, 0, 10, "Ordinary miss marks."},
			{"osu_hud_hiterrorbar_entry_misaim_height_multiplier", "Misaim entry height multiplier", BAR, Decimal, 0, 10, "Ordinary misaim marks."},
			{"osu_hud_hiterrorbar_width_percent", "Bar width (screen fraction)", BAR, Precise, 0.001, 1, "Used when showing the 50 window."},
			{"osu_hud_hiterrorbar_width_percent_with_misswindow", "Miss-window width (screen fraction)", BAR, Precise, 0.001, 1, "Used when showing the miss window."},
			{"osu_hud_hiterrorbar_height_percent", "Bar height (screen fraction)", BAR, Precise, 0.001, 0.1, "Base height before scaling."},
			{"osu_hud_hiterrorbar_bar_width_scale", "Hit entry width multiplier", BAR, Decimal, 0.01, 10, "Ordinary entry width relative to the base bar height."},
			{"osu_hud_hiterrorbar_bar_height_scale", "Hit entry height multiplier", BAR, Decimal, 0.01, 10, "Ordinary entry height relative to the base bar height."},
			{"osu_hud_hiterrorbar_offset_percent", "Bar inset (screen-height fraction)", BAR, Precise, -1, 1, "Moves all bar placements."},
			{"osu_hud_hiterrorbar_ur_offset_x_percent", "Unstable rate horizontal offset", BAR, Precise, -5, 5, "In scaled font heights."},
			{"osu_hud_hiterrorbar_ur_offset_y_percent", "Unstable rate vertical offset", BAR, Precise, -5, 5, "In scaled font heights."},
			{"osu_hud_hiterrorbar_entry_300_r", "300 red", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_entry_300_g", "300 green", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_entry_300_b", "300 blue", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_entry_100_r", "100 red", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_entry_100_g", "100 green", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_entry_100_b", "100 blue", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_entry_50_r", "50 red", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_entry_50_g", "50 green", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_entry_50_b", "50 blue", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_entry_miss_r", "Miss red", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_entry_miss_g", "Miss green", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_entry_miss_b", "Miss blue", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_centerline_r", "Centerline red", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_centerline_g", "Centerline green", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_hud_hiterrorbar_centerline_b", "Centerline blue", BAR, Integer, 0, 255, "RGB channel (0-255)."},
			{"osu_draw_hiterrorbar_bottom", "Draw bottom bar", BAR, Toggle, 0, 1, "Choose which edges show the bar."},
			{"osu_hud_hiterrorbar_offset_bottom_percent", "Bottom bar inset (screen fraction)", BAR, Precise, -1, 1, "Relative to the axis of motion."},
			{"osu_draw_hiterrorbar_top", "Draw top bar", BAR, Toggle, 0, 1, "Choose which edges show the bar."},
			{"osu_hud_hiterrorbar_offset_top_percent", "Top bar inset (screen fraction)", BAR, Precise, -1, 1, "Relative to the axis of motion."},
			{"osu_draw_hiterrorbar_left", "Draw left bar", BAR, Toggle, 0, 1, "Choose which edges show the bar."},
			{"osu_hud_hiterrorbar_offset_left_percent", "Left bar inset (screen fraction)", BAR, Precise, -1, 1, "Relative to the axis of motion."},
			{"osu_draw_hiterrorbar_right", "Draw right bar", BAR, Toggle, 0, 1, "Choose which edges show the bar."},
			{"osu_hud_hiterrorbar_offset_right_percent", "Right bar inset (screen fraction)", BAR, Precise, -1, 1, "Relative to the axis of motion."},
		};
		return list;
	}
}

#endif

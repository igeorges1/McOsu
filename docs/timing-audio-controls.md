# Timing audio control reference

Generated from the registered defaults, audio schema and HUD control metadata by
`python tests/check-timing-audio-settings.py --write-docs`. See the [system map](timing-audio.md) for lifecycle and dependencies.

## Audio editor

Options → Timing Audio Experiment. Apply commits the draft as a batch. Mute acts immediately.
All rows below save to ordinary config and named audio profiles.

| Control | Key | Default | Accepted range | Applying | Effect |
| --- | --- | --- | --- | --- | --- |
| Enable timing audio (off resets) | `osu_timing_audio` | `false` | On / Off | Off resets timing | Opt-in timing audio experiment for manual circles and slider heads. |
| Mute cues (keep learning) | `osu_timing_audio_muted` | `false` | On / Off | Keeps learner | Mute training cues without changing gain or stopping learning. Feature off still resets learning. |
| Recent reference (off = Beatmap) | `osu_timing_audio_recent` | `true` | On / Off | Keeps learner | Recent timing reference; false selects beatmap timing. Switching preserves the baseline. |
| Beatmap target (-3..3) | `osu_timing_audio_target` | `0` | `-3`–`3` | Keeps learner | Beatmap reference: 0=center, +/-1=300 edge, +/-2=100 edge, +/-3=50 edge. Recent ignores this setting; scores are unchanged. |
| Silent width | `osu_timing_audio_deadzone_mode` | `0` | `0`–`2` | Keeps learner | 0=fixed milliseconds, 1=fraction of current 300 half-window, 2=preceding timing spread. Switching preserves learning. |
| Fixed / startup half-width (ms) | `osu_timing_audio_deadzone` | `10` | `0`–`1000` | Keeps learner | Silent +/- dead zone in real-play milliseconds. |
| Map-relative fraction (0.2 = 20%) | `osu_timing_audio_deadzone_fraction` | `0.2` | `0`–`10` | Keeps learner | Relative half-width as a fraction of the current 300 half-window. |
| Adaptive variability multiplier | `osu_timing_audio_deadzone_adaptive_scale` | `1` | `0`–`10` | Keeps learner | Adaptive half-width in preceding population standard deviations. Uses the selected estimator's weights. |
| Adaptive minimum fraction of 300 | `osu_timing_audio_deadzone_adaptive_min` | `0.1` | `0`–`10` | Keeps learner | Adaptive minimum half-width as a fraction of the current 300 half-window. |
| Adaptive maximum fraction of 300 | `osu_timing_audio_deadzone_adaptive_max` | `1` | `0`–`10` | Keeps learner | Adaptive maximum half-width as a fraction of the current 300 half-window. |
| Adaptive startup uses maximum (off = fixed ms) | `osu_timing_audio_adaptive_startup_maximum` | `false` | On / Off | Keeps learner | Use the adaptive maximum for the first two accepted hits. Off uses fixed width. |
| Widen adaptive band during idle | `osu_timing_audio_idle_forgiveness` | `false` | On / Off | Keeps learner | Widen the learned adaptive band toward its configured maximum during counted play without accepted hits. |
| Idle grace (real-play seconds) | `osu_timing_audio_idle_grace_seconds` | `1` | `0`–`60` | Keeps learner | Counted-play seconds before widening. Zero allows widening as soon as counted time advances. |
| Idle widening ramp (real-play seconds) | `osu_timing_audio_idle_ramp_seconds` | `3` | `0`–`60` | Keeps learner | Counted-play seconds to ramp from zero allowance to the cap (0-60). Zero widens to cap after grace. |
| Idle recovery (accepted hits) | `osu_timing_audio_idle_recovery_hits` | `4` | `1`–`128` | Keeps learner | Accepted hits to remove full idle allowance (1-128). A hit uses the width before its recovery step. |
| Use hit-count adaptation (off = time) | `osu_timing_audio_fixed_hits` | `false` | On / Off | Resets learner | Use hit-count EMA instead of active-play-time EMA. |
| Time half-life (active seconds) | `osu_timing_audio_half_life_seconds` | `5` | `0.001`–`3600` | Resets learner | Active-play half-life in seconds after startup. Used in time adaptation. |
| Hit-count half-life (hits) | `osu_timing_audio_half_life_hits` | `16` | `0.001`–`100000` | Resets learner | Accepted-hit half-life after startup. Used in hit-count adaptation. |
| Startup running average (accepted hits) | `osu_timing_audio_startup_average_hits` | `8` | `1`–`128` | Resets learner | Number of accepted hits using a running average before exponential weighting (1-128). Applying resets learning. |
| Mute Recent during startup | `osu_timing_audio_silent_startup` | `false` | On / Off | Keeps learner | Mute Recent until its warmup count is reached. |
| Recent warmup (accepted hits) | `osu_timing_audio_silent_startup_hits` | `8` | `0`–`128` | Keeps learner | Preceding accepted hits required during silent Recent startup (0-128). Recent always needs at least one. |
| Gate: baseline inside actual 300 | `osu_timing_audio_require_300` | `false` | On / Off | Keeps learner | Mute BOTH references unless the preceding baseline exists and is inside the current 300 window. Muted hits still update. |
| Restart after breaks (off = retain) | `osu_timing_audio_restart` | `false` | On / Off | Keeps learner | Restart startup on pause and after qualifying breaks. Off retains the learner. |
| Long bodies/spinners count as breaks | `osu_timing_audio_exclude_activity` | `false` | On / Off | Resets learner | Also treat long slider-body/spinner spans without circle/head opportunities as breaks. |
| Break threshold (real-play seconds) | `osu_timing_audio_break_seconds` | `3` | `0.001`–`3600` | Resets learner | Real-play seconds; exclude the entire qualifying break from EMA time. |
| Cue gain (0..1) | `osu_timing_audio_volume` | `0.2` | `0`–`1` | Keeps learner | Independent cue gain, multiplied by master volume. Effects/hitsound volume does not mute it. Zero mutes while learning. |
| Early cue filename inside sounds/ | `osu_timing_audio_early_sound` | `timing-early.wav` | Relative file under `sounds/` | Keeps learner | Early cue filename within sounds/. Changing sounds preserves learning; retry reloads the files. |
| Late cue filename inside sounds/ | `osu_timing_audio_late_sound` | `timing-late.wav` | Relative file under `sounds/` | Keeps learner | Late cue filename within sounds/. Supports custom WAVs. |
| Keep last good cue if replacement fails | `osu_timing_audio_retain_failed_cue` | `true` | On / Off | Keeps learner | Keep using the last good cue for a direction after a failed replacement. Off leaves that direction silent. |
| Diagnostic logging (adds overhead) | `osu_timing_audio_trace` | `false` | On / Off | Keeps learner | Log preceding baseline, error, output and actual playback success; diagnostic overhead only when enabled. |

## Live Timing Debug Capture

Applies immediately and saves to ordinary Options config.

| Control | Key | Default | Options range | Effect |
| --- | --- | --- | --- | --- |
| Capture timing debug evidence | `osu_timing_capture_enabled` | `false` | On / Off | Opt-in local recording. Enable before retrying or starting a map for a replayable prefix. |
| Save screenshot when marking a problem | `osu_timing_capture_screenshot` | `true` | On / Off | Saves a separate gameplay frame on the next draw. The timing report can be used without a screenshot. |
| Mark problem key | `osu_timing_capture_mark_key` | `0` | Key binding or 0 (unbound) | Choose an unused key for standard play, or use the Mark problem button. Zero is unbound. |

## Timing Audio HUD

Applies immediately and saves to ordinary Options config.

| Control | Key | Default | Options range | Effect |
| --- | --- | --- | --- | --- |
| Timing audio on hit error bar | `osu_hud_hiterrorbar_timing_audio` | `false` | On / Off | Needs timing audio and a visible hit error bar. |
| Timing status caption | `osu_hud_hiterrorbar_timing_audio_caption` | `true` | On / Off | Show view, reference and availability above the bar. |
| Timing markers only | `osu_hud_hiterrorbar_timing_audio_markers_only` | `false` | On / Off | Hide both intervals. The mean and reference tick switches still apply. |
| Statistics spread bracket | `osu_hud_hiterrorbar_timing_audio_spread` | `true` | On / Off | Show one population standard deviation on each side of the chosen mean. |
| Audio silent band strip | `osu_hud_hiterrorbar_timing_audio_silent_band` | `true` | On / Off | Show the exact current cue interval. Markers only hides this strip. |
| Statistics mean tick | `osu_hud_hiterrorbar_timing_audio_mean_tick` | `true` | On / Off | Show the chosen view's mean when available and within the bar. |
| Audio reference tick | `osu_hud_hiterrorbar_timing_audio_reference_tick` | `true` | On / Off | Show the actual cue target when available and within the bar. |
| Timing Audio View | `osu_hud_hiterrorbar_timing_audio_view` | `0` | 0 Audio, 1 Recent, 2 Projected average, 3 Projected reference | Audio estimate, recent observations, or the hypothetical next hit at the average or reference. |
| Recent window duration (s) | `osu_hud_hiterrorbar_timing_audio_recent_seconds` | `5` | `0.1`–`60` | Accepted hits within this many counted-play seconds. The latest 2048 hits are retained. |
| Statistics animation duration (s) | `osu_hud_hiterrorbar_timing_audio_smooth_seconds` | `0.12` | `0`–`1` | Smooths statistics only. Zero snaps to the latest measurement. |

## Timing Overlay Appearance

Applies immediately and saves to ordinary Options config.

| Control | Key | Default | Options range | Effect |
| --- | --- | --- | --- | --- |
| Timing overlay opacity | `osu_hud_hiterrorbar_timing_audio_alpha` | `1` | `0`–`1` | Multiplies bar opacity. |
| Timing caption scale | `osu_hud_hiterrorbar_timing_audio_caption_scale` | `0.55` | `0.1`–`2` | Relative to bar scale and capped to fit the screen. |
| Timing marker thickness scale | `osu_hud_hiterrorbar_timing_audio_stroke_scale` | `1` | `0.5`–`3` | Scales stroke thickness and spacing. |
| Silent band red | `osu_hud_hiterrorbar_timing_audio_band_r` | `142` | `0`–`255` | RGB channel (0-255). |
| Silent band green | `osu_hud_hiterrorbar_timing_audio_band_g` | `245` | `0`–`255` | RGB channel (0-255). |
| Silent band blue | `osu_hud_hiterrorbar_timing_audio_band_b` | `231` | `0`–`255` | RGB channel (0-255). |
| Reference tick red | `osu_hud_hiterrorbar_timing_audio_reference_r` | `255` | `0`–`255` | RGB channel (0-255). |
| Reference tick green | `osu_hud_hiterrorbar_timing_audio_reference_g` | `224` | `0`–`255` | RGB channel (0-255). |
| Reference tick blue | `osu_hud_hiterrorbar_timing_audio_reference_b` | `151` | `0`–`255` | RGB channel (0-255). |
| Statistics red | `osu_hud_hiterrorbar_timing_audio_statistics_r` | `255` | `0`–`255` | RGB channel (0-255). |
| Statistics green | `osu_hud_hiterrorbar_timing_audio_statistics_g` | `255` | `0`–`255` | RGB channel (0-255). |
| Statistics blue | `osu_hud_hiterrorbar_timing_audio_statistics_b` | `255` | `0`–`255` | RGB channel (0-255). |

## Hit Error Bar Appearance and Layout

Applies immediately and saves to ordinary Options config.

| Control | Key | Default | Options range | Effect |
| --- | --- | --- | --- | --- |
| Draw hit error bar | `osu_draw_hiterrorbar` | `true` | On / Off | Required for the timing overlay. |
| Draw unstable rate | `osu_draw_hiterrorbar_ur` | `true` | On / Off | Shows unstable rate at the bottom bar. |
| Show miss window | `osu_hud_hiterrorbar_showmisswindow` | `false` | On / Off | Scale the bar to the miss window instead of the 50 window. |
| Hide bar during spinners | `osu_hud_hiterrorbar_hide_during_spinner` | `true` | On / Off | Hides the timing overlay with the bar. |
| Draw misaim entries | `osu_hiterrorbar_misaims` | `true` | On / Off | Draws misaims on the ordinary bar. Misaims do not enter the timing learner. |
| Hit error bar scale | `osu_hud_hiterrorbar_scale` | `1` | `0.01`–`3` | Scales bar and caption. |
| Unstable rate scale | `osu_hud_hiterrorbar_ur_scale` | `1` | `0.01`–`3` | Scales the unstable-rate text. |
| Whole bar opacity | `osu_hud_hiterrorbar_alpha` | `1` | `0`–`1` | Also dims the timing overlay. |
| Bar background opacity | `osu_hud_hiterrorbar_bar_alpha` | `1` | `0`–`1` | Background judgement bands. |
| Bar centerline opacity | `osu_hud_hiterrorbar_centerline_alpha` | `1` | `0`–`1` | Ordinary zero line. |
| Hit entry opacity | `osu_hud_hiterrorbar_entry_alpha` | `0.75` | `0`–`1` | Ordinary hit and miss marks. |
| Additive hit entry blending | `osu_hud_hiterrorbar_entry_additive` | `true` | On / Off | Ordinary hit and miss marks. |
| Unstable rate opacity | `osu_hud_hiterrorbar_ur_alpha` | `0.5` | `0`–`1` | Unstable-rate text. |
| Maximum hit entries | `osu_hud_hiterrorbar_max_entries` | `32` | `0`–`512` | Ordinary marks only; timing history has its own bound. |
| Hit entry fade (s) | `osu_hud_hiterrorbar_entry_hit_fade_time` | `6` | `0.01`–`60` | Fade duration for 300, 100 and 50 marks. |
| Miss entry fade (s) | `osu_hud_hiterrorbar_entry_miss_fade_time` | `4` | `0.01`–`60` | Fade duration for miss and misaim marks. |
| Miss entry height multiplier | `osu_hud_hiterrorbar_entry_miss_height_multiplier` | `1.5` | `0`–`10` | Ordinary miss marks. |
| Misaim entry height multiplier | `osu_hud_hiterrorbar_entry_misaim_height_multiplier` | `4` | `0`–`10` | Ordinary misaim marks. |
| Bar width (screen fraction) | `osu_hud_hiterrorbar_width_percent` | `0.15` | `0.001`–`1` | Used when showing the 50 window. |
| Miss-window width (screen fraction) | `osu_hud_hiterrorbar_width_percent_with_misswindow` | `0.4` | `0.001`–`1` | Used when showing the miss window. |
| Bar height (screen fraction) | `osu_hud_hiterrorbar_height_percent` | `0.007` | `0.001`–`0.1` | Base height before scaling. |
| Hit entry width multiplier | `osu_hud_hiterrorbar_bar_width_scale` | `0.6` | `0.01`–`10` | Ordinary entry width relative to the base bar height. |
| Hit entry height multiplier | `osu_hud_hiterrorbar_bar_height_scale` | `3.4` | `0.01`–`10` | Ordinary entry height relative to the base bar height. |
| Bar inset (screen-height fraction) | `osu_hud_hiterrorbar_offset_percent` | `0` | `-1`–`1` | Moves all bar placements. |
| Unstable rate horizontal offset | `osu_hud_hiterrorbar_ur_offset_x_percent` | `0` | `-5`–`5` | In scaled font heights. |
| Unstable rate vertical offset | `osu_hud_hiterrorbar_ur_offset_y_percent` | `0` | `-5`–`5` | In scaled font heights. |
| 300 red | `osu_hud_hiterrorbar_entry_300_r` | `50` | `0`–`255` | RGB channel (0-255). |
| 300 green | `osu_hud_hiterrorbar_entry_300_g` | `188` | `0`–`255` | RGB channel (0-255). |
| 300 blue | `osu_hud_hiterrorbar_entry_300_b` | `231` | `0`–`255` | RGB channel (0-255). |
| 100 red | `osu_hud_hiterrorbar_entry_100_r` | `87` | `0`–`255` | RGB channel (0-255). |
| 100 green | `osu_hud_hiterrorbar_entry_100_g` | `227` | `0`–`255` | RGB channel (0-255). |
| 100 blue | `osu_hud_hiterrorbar_entry_100_b` | `19` | `0`–`255` | RGB channel (0-255). |
| 50 red | `osu_hud_hiterrorbar_entry_50_r` | `218` | `0`–`255` | RGB channel (0-255). |
| 50 green | `osu_hud_hiterrorbar_entry_50_g` | `174` | `0`–`255` | RGB channel (0-255). |
| 50 blue | `osu_hud_hiterrorbar_entry_50_b` | `70` | `0`–`255` | RGB channel (0-255). |
| Miss red | `osu_hud_hiterrorbar_entry_miss_r` | `205` | `0`–`255` | RGB channel (0-255). |
| Miss green | `osu_hud_hiterrorbar_entry_miss_g` | `0` | `0`–`255` | RGB channel (0-255). |
| Miss blue | `osu_hud_hiterrorbar_entry_miss_b` | `0` | `0`–`255` | RGB channel (0-255). |
| Centerline red | `osu_hud_hiterrorbar_centerline_r` | `255` | `0`–`255` | RGB channel (0-255). |
| Centerline green | `osu_hud_hiterrorbar_centerline_g` | `255` | `0`–`255` | RGB channel (0-255). |
| Centerline blue | `osu_hud_hiterrorbar_centerline_b` | `255` | `0`–`255` | RGB channel (0-255). |
| Draw bottom bar | `osu_draw_hiterrorbar_bottom` | `true` | On / Off | Choose which edges show the bar. |
| Bottom bar inset (screen fraction) | `osu_hud_hiterrorbar_offset_bottom_percent` | `0` | `-1`–`1` | Relative to the axis of motion. |
| Draw top bar | `osu_draw_hiterrorbar_top` | `false` | On / Off | Choose which edges show the bar. |
| Top bar inset (screen fraction) | `osu_hud_hiterrorbar_offset_top_percent` | `0` | `-1`–`1` | Relative to the axis of motion. |
| Draw left bar | `osu_draw_hiterrorbar_left` | `false` | On / Off | Choose which edges show the bar. |
| Left bar inset (screen fraction) | `osu_hud_hiterrorbar_offset_left_percent` | `0` | `-1`–`1` | Relative to the axis of motion. |
| Draw right bar | `osu_draw_hiterrorbar_right` | `false` | On / Off | Choose which edges show the bar. |
| Right bar inset (screen fraction) | `osu_hud_hiterrorbar_offset_right_percent` | `0` | `-1`–`1` | Relative to the axis of motion. |

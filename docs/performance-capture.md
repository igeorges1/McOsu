# Performance capture

On Windows, open **Options → Timing Audio Experiment → Live Timing Debug Capture** and enable **Record app frame timing**. It works in menus and during loading, with timing audio on or off. Use the existing **Mark problem** button or bind an unused key. The capture notification reports whether collection was queued and whether it saved. Only one mark can be collecting or saving at a time.

A mark can save three components in the same local folder. `performance.csv` contains measured app cadence. `capture.mct` contains the [existing timing-model prefix](timing-capture.md) when timing capture is active and available. `frame.png` and `screenshot.txt` describe the optional next matching draw. `export.txt` records component outcomes and stage durations. A failed image or missing timing prefix does not prevent a valid performance sidecar. The 12-folder quota counts immediate child directories, including partial and unrelated folders. Capture never deletes files.

## Analyze a mark

```powershell
python tools/verify.py --performance C:/reports/mark-123/performance.csv
```

This command needs Python and the supported tool checkout. It creates an ignored run directory with the exact input, its SHA-256, `summary.json`, and `timeline.svg`. The summary gives sample counts, median, p95, p99 and maximum, worst intervals with context, and unavailable phases. It reports the mark-containing interval separately from earlier and later intervals. The graph keeps raw elapsed values. A frame with no draw contributes cadence but no draw duration. The analyzer validates schema, sizes, values, ordering, count and footer. It accepts explicitly short or empty history and exposes its reason.

## What the samples measure

Each row closes at the next **App update** start and records the previous start, raw start-to-start elapsed seconds, inclusive App update wall time, and the sum and count of App draws before the next update. The clock is the main-thread engine real timer, in seconds since its origin. On the pinned Windows engine it is derived from QueryPerformanceCounter and converted to seconds by the engine. Raw QPC ticks and the process epoch are unavailable in the file. The samples use no gameplay delta, timescale, smoothing, or profiler toggles.

The full Windows loop, actual limiter wait, swap, GPU execution and displayed-frame pacing are unavailable. A skipped draw is visible as zero draws. Time outside the sampled update/draw phases is unattributed. Each row captures context at update start. The context bits from low to high are focus, minimized, play, pause, loading, countdown, and scheduled continue. Foreground/background FPS limit, unlimited FPS and VSync columns are configured values. `-1` denotes an unavailable phase or setting.

The pre-mark ring keeps 120–4096 completed intervals by count, at most 4096 even at high frame rates. Older intervals are evicted and counted within the current clock segment. The interval containing the mark is kept when it closes, including when additional post-mark history is zero. Up to 120 later intervals are collected for at most two seconds, with a shorter tail labelled on deadline, scene/reset, settings change, clock interruption or shutdown. Normal completion requires the mark-containing interval. Backward or invalid clock stamps clear the live ring and increment the discontinuity count. A pending report keeps its existing samples and ends its collection at that clock boundary. Changing history size starts a new ring.

## Export cost and lifecycle

The app copies a bounded timing prefix, metadata and frame history at the mark. The active timing prefix stays intact for later reports. The optional 3840 × 2160 RGB frame still requires synchronous readback on the render thread, which may block. Background export owns only copied data. It reserves the folder, formats and writes reports, encodes PNG and publishes completed files. Report format and write are a combined worker measurement. PNG encoding and write are separate. Main-thread snapshot and readback use the engine clock. Worker durations use a separate monotonic clock and do not have an exact position on the timeline.

The app keeps one timing prefix and at most one copy, each capped at one million long doubles. The recording ring and pending frame window each have a fixed sample bound. Only one RGB frame and its dimension-bounded codec workspace are active in the exporter. The worker has no access to the game, graphics context, or settings. A disabled recorder or map change never waits for a worker. On exit, pending collection is shortened, and the app waits at most 100 ms for export. An unfinished write can be abandoned at process exit. Partial files and missing receipts indicate incomplete output. Existing captures are preserved.

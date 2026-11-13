# Live timing debug capture

Open **Options → Timing Audio Experiment → Live Timing Debug Capture**. Enable **Capture timing debug evidence** and keep **Enable timing audio** applied. Start a map or retry after enabling. Use **Mark problem** or bind an unused key to mark while playing. The key is unbound by default. Known game bindings, Enter, Escape and F1 are unavailable for marking. Holding the key makes one mark. The key leaves normal game dispatch intact.

The notification identifies a folder under `timing-captures/` in this installation. The report is `capture.mct`. A report that starts mid-session remains partial until the next full timing reset. A marker screenshot is independently optional and enabled by default. It captures the next matching standard-gameplay draw, including any UI visible on that frame. The screenshot receipt records the actual frame time, dimensions and status. A missing receipt means the screenshot outcome is unknown, such as when the process exits before the next draw. Share the report alone for model verification, or include `frame.png` and `screenshot.txt` to show what was visible. Captures can contain beatmap metadata, setting values, cue names and a screenshot. Review them before sharing.

## Reproduce a marked sequence

Use the exact clean Git revision listed on the report's `source` line. The supported normal Windows builder injects that revision into the executable. Other builds report unknown unless they supply the corresponding build define. The package ID is available from the separate package manifest, when provided. The report carries a map MD5 from the selected difficulty. Helper replay uses the recorded activity schedule and timing inputs, so it needs neither the beatmap file nor its music. See the [verification setup](verification.md) for the toolchain.

```powershell
python tools/verify.py --toolchain C:/toolchains/mingw32 --capture C:/reports/mark-123/capture.mct
```

The command snapshots and hashes the input, validates its version, integrity, source, bounds and completeness, then compiles the production timing helpers and runs the bounded comparison. It prints the first divergent event, field, captured value and replayed value. The ignored run directory retains the input and logs. A successful replay verifies the timing model at the capture seam, including actual accepted samples, direction, the used band, learner statistics and Recent observations. It does not replay input routing, object judgement, draw interpolation, pixels, scoring, resource calls or audible output.

## Format and causal boundary

Schema 1 is an ASCII stream. The header carries source, map identity, prefix status, hex-encoded UTF-8 mark metadata and the declared scalar count. Event rows contain a sequential ordinal, operation code, arity and classic-locale decimal fields at long-double round-trip precision. Nonfinite values remain explicit. The footer includes an end marker and a 64-bit FNV-1a integrity check over the preceding bytes. The hash detects accidental corruption. It provides no authentication. The accepted run's input SHA-256 is in the verification receipt.

| Input to replay | Recorded observation |
| --- | --- |
| Counted-clock timestamp and active flag, pause and its restart policy | Counted clock and rolling count, mean, variance and truncation at marks |
| Resolved estimator and band config at its actual configure boundary, ordered activities and corrected-clock advances | Learner count, mean, variance and active milliseconds after each sampled observation |
| Raw error and opportunity in map milliseconds, actual truncated 300 half-window, rate, reference mode and resolved target | Acceptance, classified direction, width and frozen pre-update silent endpoints |
| Full timing reset establishes the start of a new prefix | Output status, requested gain, effective Master gain, whether a sample was selected and whether playback returned success |

Config rows are emitted when resolved model configuration changes. Equal repeated configurations are idempotent. Every actual clock and state advance is retained, including duplicate timestamps. Ready pre-roll, loading suspension, pause, scheduled continue and empty-section skips keep their existing behavior. Seek, retry and feature-off clear the complete timing components and start a new prefix. Sound reload and skip annotations are contextual. Mark metadata records the current applied settings and cue identities, map/rate/difficulty/mod information and the selected unsmoothed HUD query. It describes the mark snapshot, which can differ from the last hit and the pixels in the next draw. An active sample may be a retained fallback. Playback returning success is a software observation.

## Bounds and failures

Each active recording reserves at most one million scalar slots. It keeps a complete prefix from the latest full reset until that bound. Overflow exports a diagnostic prefix and cannot replay successfully. Mark metadata is capped at 32 KiB. Reports must contain an accepted timing observation and end at a mark for replay. A report from an unknown build/map, a mid-session start, or an incomplete or corrupted file cannot pass. Subsequent marks preserve the prefix until a reset. The quota counts up to 12 immediate child directories under `timing-captures/`, including partial reports and unrelated folders placed there. Files and sibling directories do not count. Move old reports to make room. Capture never deletes folders. Screenshots are capped at 3840 × 2160 pixels. The game writes a temporary structured report and publishes it before attempting the screenshot. A failed write may leave a partial file. Unmarked in-memory data is lost if the process exits. There is no crash-durability guarantee.

Capture is off by default. There is no capture allocation, formatting or file operation in the disabled judgement path. The enabled path appends numeric values in bounded memory. A mark formats and writes the report synchronously, and reading/encoding an optional frame can cause a visible hitch. Disable screenshots when testing timings around a mark. The diagnostic consumer compares model outputs, so replay success alone establishes neither overhead nor native renderer behavior.

# Gameplay scheduler attribution

This draft includes App instrumentation and offline analysis. Live collection
requires the separately reviewed private Windows route described below; this
checkout is not a complete operator capture installation. See the exact
[publication and validation boundary](validation/gameplay-attribution.md).

Use a separate normal-token Windows diagnostic build with verified disposable
writable state. Under **Timing Audio Experiment → Live Timing Debug Capture →
Advanced Gameplay Attribution**, enable frame timing and the raw QPC companion.
For the first trial disable screenshots, choose an unused Mark binding, and
load a familiar passage. Approve the separate collector prompt and wait for its
readiness instruction. Return to the focused game, let the map finish loading,
and press Mark once to signal readiness. This saved Mark starts the bounded
watchdog/Start sequence and is outside the trace. Stay in the game. Start or
continue playing and use a second Mark promptly after an in-window hitch.
If no hitch occurs, a second Mark can still test the association. The ring
keeps a count of intervals, so 4096 rows cover about
8.5 s at 480 Hz and 1 s at 4000 Hz. Wait for both the app save and verified
collector release. The collector does not launch or terminate the game.

`gameplay.qpc` is a separate integer sidecar. The existing timing capture and
performance CSV retain their schemas. PID, creation FILETIME, OS thread, QPF,
source, capture epoch, update sequence, draw ordinal and Mark identity bind the
scopes. A Mark exactly on a boundary belongs to the next half-open interval.
Optional update, individual draws and Mark stages are recorded independently.
Invalid raw spans, reset, missing boundary, exceeded draw/row capacity and
unfinished post history are visible in partial output. History eviction is
counted. App preferences persist in ordinary config and remain outside the
named audio profiles. The [control reference](timing-audio-controls.md) lists
keys and dependencies. The report quota and tail deadline also apply to legacy
export, with the original defaults.

## Separate gameplay collector

First validate a JSON object of budget overrides with
`python tools/gameplay_collector.py --validate budget.json`. All omitted fields
resolve to defaults. Invalid settings are refused. Durations are integer ms;
size units are MiB except buffer KiB, and `slices` is a count.

The generated [control reference](timing-audio-controls.md#gameplay-collector-and-analyzer-budgets)
lists each key, default, domain and dependency. Elevated child entry starts
setup. After handle, profile and storage checks, the child publishes a
readiness origin and deadline. It polls the diagnostic runtime's existing
Mark folder, bounded by the app's report quota. After the final `export.txt`
reports a saved QPC companion, the complete `gameplay.qpc` must show the
same app identity, a later Mark ID, a QPC strictly
after readiness opened and a focused, loaded gameplay frame at the Mark. A
paused map can signal readiness. The bound baseline can be reused for the
same running process. Reserve two free Mark slots for readiness and evidence.
Timeout ends the attempt before watchdog arm or logger Start. The elapsed
readiness wait is excluded from setup and included in the observer budget.
The observer clock starts when the consent call returns the child handle.
The watchdog clock starts at its arm origin. After Start, privilege restoration
and an owned logger query, the actual active QPC starts the collection clock.
The collection deadline reserves finalization before watchdog intervention.

Disk checks use both output and system volumes and include an additional
200 MiB reserve. Occupancy is the greater of actual file size and written
buffers in bytes, plus a full buffer backlog allowance. Stop early if
occupancy reaches the early threshold. After at least one forecast window
(default 1 s), also stop if the growth rate since the newest sample at least
that old projects threshold crossing over the shorter of remaining target
time and the forecast horizon (default 2 s). The file cap keeps a separate
rundown reserve. Bursts can outrun polls. The stop report distinguishes
observed occupancy, forecast, low disk, loss and the final file cap.
The launcher reports elapsed active QPC time up to Stop request and release
disposition. An early stop leaves the attempt incomplete. Wait for independent
release and report the result to the coordinator before any retry. The
budgets are trial values and the target duration is conditional.

The versioned gameplay entrypoint consumes the previously frozen private
Windows route as an explicit input. A run config contains `budget`, a fresh
`session` UUID, `profile_route` pointing to the frozen 015 directory,
`image` and `image_sha256`, and `identity` with `pid`, `creation`,
`tid`, `qpf` and `source`, plus `baseline_mark` with the saved Mark `id`,
`qpc` and its `folder_limit`. The coordinator must verify the live normal-token
diagnostic process and expected writable paths. The gameplay supervisor
authenticates its original process/thread handles and executable. Its
conditional privilege scope and independent watchdog come from 015; the
original controlled tools and grants remain immutable.

For a separately authorized attempt, the coordinator can obtain exact grant
fields with `python tools/gameplay_record.py run.json grant.json new-run --describe-grant`.
This prints data and performs no recording. Only the exact separately issued
grant permits `python tools/gameplay_record.py run.json grant.json new-run --observe`.
The coordinator records a fresh exact-name QUERY and process absence after
normal release. Stage the companion in the owned run directory and use
`python tools/gameplay_record.py --seal new-run new-run/gameplay.qpc absence.json new-run/bundle.json`.
The absence receipt contains session, name, status 4201, and an empty
remaining_owned_processes array, backed by the coordinator's actual receipts.
Keep the bundle and all source receipts local.

## Offline analysis

The verifier offers two explicit Windows readers. Both join the sealed trace
to the App sidecar and report Running, Waiting, Ready and Unknown in the same
integer frame and scope format.

### Raw classic ETW reader

Use a recording made with the raw-capable collector. The authorized child
retains the original config and recording grant, its identity and the
readiness sidecar. The active receipt records the verified process creation,
image and thread ownership while the collector holds the original handles.
The observer binds the controller's exit to its process identity. The
controller records active and subsequent zero-loss samples. After normal
release, stage the coordinator's original absence and exact name/GUID QUERY
receipts as `independent-absence.json` and `independent-query.json` in the owned
run directory. Before recording, the coordinator sets `owns_app` in the
recording config according to whether this run started and owns the App.
This is part of the exact recording grant. The absence receipt includes `input_guid`, observed owned PIDs
and `query_receipt_sha256`. Its `app_target` object binds the game's `pid`,
creation FILETIME (`creation`) and whether the run owns it (`owned`). The
controller must be in the observed owned set, with no remaining owned
processes. Include an owned diagnostic App in that set and verify its exit.
An already-running player game is a target and can remain open after the
collector releases. The query receipt reports operation
`ControlTraceW QUERY only`, the session name and GUID, status 4201 and false
`trace_mutation` and `etl_read`.

```powershell
python tools/gameplay_record.py --seal-raw C:/owned/run C:/owned/run/gameplay.qpc C:/owned/run/independent-absence.json C:/owned/run/independent-query.json C:/owned/run/bundle.json
```

Build the native reader in a writable build directory with an x64 MSVC and
Windows SDK developer prompt. Use the executable matched to its reviewed reader-pair manifest.
For the versioned reader, add `--gameplay-raw-reader-pair` and the same
manifest path to both commands below. The manifest identifies the reader,
native source, consumer source, wire schema, ambiguity policy and compile
receipt. The review binds those inputs before offline authority is issued. The
manifest uses integer `version` 1 and integer `wire_schema` 2, the
`equal-qpc-or-validated-self-switch-barrier-v2` `ambiguity_policy`, and
SHA-256 fields `reader_sha256`, `native_source_sha256`,
`consumer_source_sha256` and `compile_receipt_sha256`. The source
fingerprints use LF line endings. The compile receipt digest identifies the
reviewed build evidence. Omitting the manifest selects
the legacy I/O/R protocol and requires its compatible reader.

```powershell
cl /nologo /W4 /WX /std:c++17 /EHsc /MT /O2 C:/source/tools/gameplay-raw-reader/witness.cpp /Fe:gameplay-raw-reader.exe tdh.lib advapi32.lib
python tools/verify.py --gameplay C:/owned/run/bundle.json --gameplay-raw-reader C:/owned/bin/gameplay-raw-reader.exe --output C:/owned/analysis --describe-gameplay-raw-grant
python tools/verify.py --gameplay C:/owned/run/bundle.json --gameplay-raw-reader C:/owned/bin/gameplay-raw-reader.exe --output C:/owned/analysis --gameplay-raw-grant C:/owned/raw-grant.json
```

The describe command prints the exact grant request without opening the ETL.
A coordinator issues those fields for a reviewed local capture, producer
grant, toolchain and new output directory before the analysis command.
The capture and reader digests are checked before running the reader.
Keep the sealed directory and receipts local. The seal and grant protect
the integrity of an already trusted producer chain.

Raw admission requires unambiguous classic process and thread rundown pairs,
matching owner and full process key, raw QPC, matching frequency and zero
loss. The reader checks target V4 context switches with their typed Windows
TDH field sizes and full values. The active sample and a following successful
original-handle poll bound observation. The last poll proves continuity
through the preceding sample, which is the upper bound. At least three
ordered samples are required. The reducer uses neighboring witnesses inside
this verified window and reports uncovered edges as Unknown.

The raw command defaults to the whole trusted collection window. To
analyze only the retained App history plus context, add
`--gameplay-raw-window retained` to both the grant description and the
analysis command. Override the per-side context with
`--gameplay-raw-lookaround-ms` in retained mode. The
[control reference](timing-audio-controls.md#raw-gameplay-analyzer-controls)
lists defaults and accepted values. This is a consumer choice. The
collection budget and producer seal remain as recorded.

Retained mode derives its window from all saved App frames, rounds padding
up to QPC ticks, and clips to the verified live interval. It uses a
half-open scheduler window and reads the full trace for the existing
lifecycle, clock and loss checks. All retained frames still appear in the
report. Unavailable witnesses at the selected edges stay Unknown.
Unsupported records inside the selected window still prevent attribution.

When valid scheduler records share a QPC tick, the reducer treats the entire
group as an ordering barrier. With the versioned pair, the reader also
preserves a corroborated same-target classic V4 context-switch record
with the observed state byte 2 as an uninterpreted boundary. Other
same-target forms still cause refusal. A boundary counts against the
ordinary evidence limits and clears prior scheduler evidence. The report
does not assign a state from it. No member supplies a switch, state or Ready
transition. Only later independently supported intervals resume classification.
The raw records remain in encounter order in `reader.stdout`. The summary
includes the selected and trusted bounds, bounded tie-group samples and exact
counts, and Unknown ticks among the written frames. Decreasing timestamps,
invalid records, loss and exceeded evidence caps still cause refusal.

The ETL, Job, report and slice budgets apply to both readers. The raw reader
also caps retained event rows using the report budget and a fixed parser
ceiling. In the raw `summary.json`, `marked_frame` reports availability and
integer totals for the marked frame and its recorded scopes. The detailed
witnesses stay in the capped streams and `frames.jsonl`. Earlier or later
history can be Unknown even when the marked frame is complete. Inspect
`marked_frame` and the coverage window before deciding whether the report
answers the marked-hitch question.

### SDK reader

Build `tools/gameplay-reader/GameplayReader.csproj` with SDK 9.0.203,
the existing local 1.12.10 package cache, `dotnet restore --locked-mode
--source <cache> --packages <cache>`, then `dotnet build --no-restore -c Release`.
Use the reviewed binary and explicit .NET host.

```powershell
python tools/verify.py --gameplay C:/owned/run/bundle.json --gameplay-reader C:/owned/reader/GameplayReader.dll --dotnet 'C:/Program Files/dotnet/dotnet.exe' --output C:/owned/analysis
```

The SDK reader uses raw classic process and thread boundaries, an authenticated
same-run receipt, clock and loss checks, and actual raw switch/Ready witnesses.
Capture rundown identifies censored presence of an already-running game.
The decoder report includes target-only identity diagnostics for process and
thread model counts, managed creation timestamp availability and provenance,
raw boundary agreement, clock, loss, and individual admission checks.
It distinguishes an absent process model, a zero managed process key, a
full-width match and a nonzero mismatch without reporting kernel addresses.
Raw boundary evidence includes event kind, QPC, version and pointer width.
Intervals without enough evidence are Unknown. Wait and Ready remain distinct.
The Windows Job bounds decoder memory and time; pinned TraceProcessing may
materialize internal data up to that process limit. Reports retain raw
contributing slices and their clipped endpoints. Frame totals and nested
scope totals each reconcile independently. Do not add parent and child totals.
Decoder streams and frame output share one retained byte budget, with 64 KiB
reserved for the request, process receipt and summary. Stream excess is
discarded while the owned process remains subject to its deadline. Either
stream or frame truncation makes the result inconclusive.
Exit 0 means complete association, 3 means inconclusive or partial, and 1
means a tool/input failure. None identifies the function, resource, GPU,
input latency or root cause of a gameplay stutter.

A controlled saved rehearsal qualified the raw reader's witness layout
and independent reduction for one known stall. The SDK analysis for that
capture remains inconclusive. A separate controlled rehearsal verified the raw-capable producer and
seal. Its original whole-window analysis was inconclusive. The revised
retained-window consumer and ambiguity policy have been checked against
the exported scheduler evidence. The legacy reader and retained-window command were checked on the sealed
fixture. The versioned pair's supported whole-window command was subsequently
qualified on the same manual controlled fixture at tools source `be9da43d`:
native exit 0 and CLI exit 3 accompanied a complete marked frame and 23 partial
history frames. Original fixture App, producer and consumer source identities
remain separate. This is not automated-launch or arbitrary-player qualification.
Gameplay overhead and general representativeness remain pending.
Compare matched capture-off, legacy, raw companion, and companion with ETW
runs before interpreting representativeness.

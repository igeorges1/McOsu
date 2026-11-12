# Timing/HUD verification and regression reproduction

Run from a **Windows source checkout containing this guide**, with Python 3.13+,
Git on PATH, and an explicitly supplied extracted GCC **8.1.0 i686 / Win32
threads / DWARF2** distribution (`mingw32/bin/g++.exe`). The distribution name is
`i686-8.1.0-release-win32-dwarf-rt_v6-rev0.7z`, as used by McEngine's Windows build.
There are no Python packages, engine checkout, release assets, BASS device, game
installation, or private scripts to supply. No dependency download is implicit.
Use a committed checkout for a reviewable receipt. This workflow was introduced
on combined source `24da0eec695b581a00d57a25043b3d447783c27b`, which contains the
required unpublished timing/HUD helpers; an older master checkout is insufficient.

```powershell
python tools/verify.py --toolchain C:/dependencies/mingw32
```

Replace the dependency path with your extracted toolchain root. This is the one
supported entrypoint. It runs the `timing` profile by default: **all eight C++
suites, the settings inventory, and the named regression**. The script locates
source relative to itself; you can invoke its absolute path from another cwd.
Compiler `bin` is prepended to the child's PATH, including for test DLL loading.
Keep the complete toolchain, including its runtime DLLs. Caller compiler include/
library injection variables are removed. Flags are C++11, `-O2 -Wall -Wextra
-Werror -pedantic -UNDEBUG`; compiler version/target/thread/exception probes are
required and bounded. Python `-O` is refused; inventory assertions must execute.

Preflight requires exactly the eight registered nonempty suite files, inventory,
control reference, production header dependencies and complete historical fixture
manifest. New `OsuTimingAudio*Test.cpp` files require explicit registration in
`tools/verify.py`; they cannot silently escape the profile. Missing inputs and
unsupported dependencies fail. No test is skipped to obtain a green result.

## Repeat the known case

```powershell
python tools/verify.py --toolchain C:/dependencies/mingw32 --case preroll-history
```

This selects **only three case compile/run pairs**, after common input/dependency
preflight. It does not run the eight suites or settings inventory. Both commands
return zero only after every selected check completes successfully. A successful
full profile records 26 direct child checks (3 compiler probes, 16 suite compile/
run checks, 1 inventory, 6 case compile/run checks). A selected case records 9.

`preroll-history` reproduces the historical **accepted ready pre-roll omitted**
regression. The fixture injects an already accepted −50 ms observation before
playback, waits through ten countdown seconds, then injects an accepted 0 ms
observation. Expected history: waiting count 1/mean −50; final count 2/mean −25.

| Input | Exact production revision | Observed history | Required outcome |
| --- | --- | --- | --- |
| Historical old helper | `2f5d88bab2f89d33e50ab9ddde014ceac480505d` | waiting 0/0; final 1/0 | Intentional RED, direct exit 1 and the exact missing-pre-roll assertion |
| Historical fixed helper | `5f2289edce8c4060d0e9f314c945fd5701d09d46` | waiting 1/−50; final 2/−25 | GREEN, direct exit 0 and completion |
| Current checkout helper | actual snapshotted input hashes in receipt | waiting 1/−50; final 2/−25 | GREEN, direct exit 0 and completion |

The old and fixed headers are exact Git blobs under
`tests/verification/preroll-history/{old,fixed}`. Their `manifest.json` records
revision, original path, Git blob and SHA256; preflight checks both content hashes.
Git attributes preserve their exact bytes on Windows. No historical Git objects
are needed, so a shallow checkout can run the case. The single fixture
`tests/verification/PrerollHistory.cpp` bridges the old `record`, fixed
`recordAcceptedHit(error)` and current `recordAcceptedHit(playSeconds,error)` APIs.
It does not reimplement history arithmetic. In the current API counted-play time
remains zero through countdown. An unrelated assertion, compile error, missing
DLL, nonzero exit or timeout never qualifies as the expected RED: the runner also
requires exact observed count/mean text and the specific assertion expression.

This proves the **production history helper** at an accepted-observation boundary.
Acceptance/routing of natural input, beatmap loading and adapter callbacks are
bypassed. It is not a captured session, game replay, renderer check or audio test.
The historical software fix also changed adapter routing; this smaller reusable
case deliberately claims only the history seam.

## Coverage map

| Selected check | Real production boundary | Evidence and limits |
| --- | --- | --- |
| `OsuTimingAudioReferenceTest` | Reference normalization | Numeric references, input rejection and ranges |
| `OsuTimingAudioStateTest` | Learner and activity clock | State contracts, resets, gap handling and million-sample loop |
| `OsuTimingAudioBandTest` | Pre-hit classification/band policy | Weighted spread, startup, switches, gating and variance correction |
| `OsuTimingAudioBoundaryTest` | Map/real timing endpoints | Fractional target/rate/width endpoints and outward neighbors |
| `OsuTimingAudioHUDTest` | Live evaluations, recent history, projections and HUD geometry | State and geometry; no native pixels |
| `OsuTimingAudioSettingsTest` | Schema, config retention and profile parser | Validation, exact decimal/Unicode roundtrip and negative inputs |
| `OsuTimingAudioSetupTest` | Applied setup formatting | State/readout text; executable renamed `Readout` to avoid installer detection |
| `OsuTimingAudioIdleTest` | Idle/startup/recovery policy and shared clock | Numeric/state policy, not player usefulness |
| `settings-inventory` | Registration ↔ metadata ↔ generated reference | Exact 30 audio/71 HUD registration, defaults/ranges/reference correspondence |
| `preroll-history` | Frozen/current production RecentWindow | Exact RED/fixed/current GREEN as above |

The [timing system map](timing-audio.md) and [generated controls](timing-audio-controls.md)
remain authoritative for behavior/settings. Update this coverage map and runner
registration together when adding/removing tests. Product behavior is unchanged.
Other boundaries, including production adapters, framebuffer probes, device/audio
and human play, retain their separate evidence and limits.

The independent [runtime tooling workflow](../tools/runtime/README.md) already has
its own supported tests: `python -m unittest discover -s tools/runtime/tests -v`.
It is separate from this profile and is not rerun here. Profiles are a small
explicit dispatch in `tools/verify.py`, not automatic discovery of arbitrary code.

## Results, deadlines and failures

Every invocation creates a new `.verification-runs/<UTC>-<unique>/` **inside this
checkout**, ignored by Git. No output destination/overwrite option exists; linked
or redirected output roots are refused. Original historical evidence is preserved.
Generated source and binaries belong to that run; stale executables/logs cannot
be reused. Retain failed runs as well as successful ones.

`run.json` is written incrementally, including before a compile. It records actual
source HEAD/tree/branch/dirty status, hashes of snapshotted source/test/inventory
inputs, full toolchain file inventory/tree hash, Python identity, effective PATH,
flags, invocation, selected profile/case, generated test identities, direct child
PID/argv/cwd/executable hash, elapsed time, actual exit and unsigned hex code,
timeout/error, separate stdout/stderr logs, expectations and first failure.
Tests and inventory run from the snapshot, avoiding edits halfway through a run;
the runner also rejects changed source inputs before marking success.

Assertions remain enabled. Generated suite copies preserve original test bodies:
only `cassert` includes are replaced by the portable guard **after all includes**,
`main` is renamed, its implicit successful return is made explicit, and a wrapper
emits completion after it returns zero. Original and generated hashes/files are
retained. Existing custom CHECK/negative checks remain enabled. Exit zero without
the required completion is failure; a marker with a failed exit is also failure.

Windows error reporting is nonmodal. Each direct process starts suspended, joins
an owned kill-on-close Windows job, then resumes; its descendants are cleaned up
on completion, timeout or Python interruption. No kill-by-name or foreign PID is
used. Default external deadlines: 15 seconds per compiler probe/test/inventory,
60 seconds per compile. `--test-timeout` and `--compile-timeout` accept finite
positive seconds up to 300; overrides are recorded per process. Tree hashing and
file copying are synchronous preflight work, not child processes. A host crash or
forced controller kill can leave an incomplete receipt; `complete:false` is never
acceptance. The OS closes the job handle and kills owned descendants on exit.

On first failure the runner stops, flushes `VERIFICATION_FAULT <JSON>` with detail
and prints the log/receipt location. **The supervising agent must immediately send
the assigned parent/coordinator that fault, before diagnosing or retrying**: source,
EXE/path/hash/PID, expected versus observed, exit/timeout, log path and whether an
owned process remains. Do not wait for final reporting or user discovery. Transport
belongs to the supervisor; the supported source does not embed T3/chat APIs.
Predeclared historical RED and contract-negative probes are intentional evidence,
not unexpected faults. Keep failed attempts separate from corrected runs.

## Check the runner itself

```powershell
python tools/verify.py --toolchain C:/dependencies/mingw32 --profile runner-contract
```

This bounded profile reuses the actual process/result seam for six intentional
negative checks: independent streams/exit 7, real compile failure, nonmodal enabled
assertion exit 1, deadline plus spawned-descendant cleanup, missing completion,
and misleading completion with exit 7. It records nested process receipts under
`contract/`; internal negative `VERIFICATION_FAULT` lines are expected. The outer
profile must exit zero with `COMPLETE runner-contract failures=0 tests=6`.
Common preflight still verifies the complete registered input set. No game is built.

To check missing-dependency handling, supply a nonexistent `--toolchain` directory:
expect exit 1, an incomplete/failed receipt and no suite/test launch. Bench acceptance
also challenges missing/empty/added inputs in disposable source copies.

This supported command replaces private feature-specific compile/copy/guard
recipes **for the coverage in this map**. Those original experiments and logs
remain historical evidence. Reuse is established by independent clean-checkout
execution from this guide plus the explicit compiler input; no time-savings or
general gameplay reproducibility claim follows.

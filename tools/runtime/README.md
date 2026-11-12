# Reusable Windows builds and runtimes

For queued preview updates, see the [lifecycle, command reference and migration
recipe](QUEUED-PREVIEW.md). A managed preview can stage a verified package while
the game runs and promote it at a launcher boundary.

Python 3.13+, Git, and GCC **8.1.0 i686 / Win32 threads / DWARF2** are required.
These tools do not change gameplay. They do not choose channels or install into
Steam. Every build, package and runtime destination is an explicit caller input.
Run commands below from the McOsu checkout in PowerShell.

## Build and package

Use a clean, committed source checkout. Obtain McEngine from
<https://github.com/McKay42/McEngine>; the local repository must contain commit
`f2f5721409c17ce4decc20eaf2a1827ce9aafd87`. The builder exports that exact Git
tree, ignoring local engine edits and source junctions. Its only engine changes
are selecting the Osu include/constructor and disabling FrameworkTest's
constructor, inside the build output. It copies this checkout's Osu source there.
No sibling checkout binding is reused or modified.

`--toolchain` names the extracted `mingw32` directory, containing `bin/g++.exe`.
The builder verifies version, target, threading and exception model and hashes
the complete toolchain tree. McEngine's README describes obtaining the
`i686-8.1.0-release-win32-dwarf-rt_v6-rev0.7z` distribution. No dependency
downloads occur implicitly.

`--assets` names a trusted normal McOsu release directory containing
`materials`, `fonts`, `shaders`, and `models`, plus optional `sounds` (normal skin
audio lives under `materials`). The game repository does
not contain the full release assets. Only those five directories are copied;
revision-specific files from this checkout's `build/` overlay them. Supply a
normal release baseline, never a synthetic/instrumented test asset tree. The
baseline content hash and every resulting file hash are recorded. Existing
installations can be read as asset inputs; they are never build outputs.

```powershell
python tools/runtime/build.py build --source . --engine C:/deps/McEngine --toolchain C:/deps/mingw32 --assets C:/deps/McOsu-release --out tools/runtime/out/build-001
python tools/runtime/build.py package --build tools/runtime/out/build-001 --out tools/runtime/out/package-001
python tools/runtime/runtime.py validate --package tools/runtime/out/package-001
```

Use fresh output paths. Build output inside the source checkout must be
Git-ignored, such as `tools/runtime/out/`; otherwise choose a path outside the
checkout. The builder refuses an unignored in-tree output before compiling.
Existing builds/evidence are never erased. Builds are
full builds (four compiler workers by default, `--jobs 1..32`). Per-unit compiler
arguments/logs, private engine/game snapshots, link log, PE imports and
`build.json` remain in the output. Packaging refuses a changed build payload.
Copy the **entire package directory** to transport it; no build checkout is
needed at the runtime. Keep this CLI and Python available separately.

Each package's `manifest.json` identifies the clean source commit, engine pin,
toolchain fingerprint, build flags and each payload file's size/SHA-256. The
package ID hashes the canonical manifest contents. SHA-256 detects corruption
and mismatched identity; it is **not a publisher signature**. Use trusted inputs.
Cross-machine bit-for-bit compiler reproducibility is not claimed.

## Initialize once, reuse for later builds

Initialization accepts a nonexistent or **empty** destination only. It never
adopts an existing installation or a source checkout. A competing initializer
cannot claim the same destination or overwrite a runtime initialized while its
import plan was being prepared. If an import fails after copying some files,
inspect the partial destination and use a fresh empty path for a retry; the
tool leaves copied state intact.

```powershell
python tools/runtime/runtime.py init --runtime C:/Games/McOsu-managed
# Optional instead of the line above: explicitly COPY existing writable state.
# python tools/runtime/runtime.py init --runtime C:/Games/McOsu-managed --import-from C:/Games/old-private-runtime
python tools/runtime/runtime.py update --runtime C:/Games/McOsu-managed --package tools/runtime/out/package-001 --dry-run
python tools/runtime/runtime.py update --runtime C:/Games/McOsu-managed --package tools/runtime/out/package-001
python tools/runtime/runtime.py inspect --runtime C:/Games/McOsu-managed
python tools/runtime/runtime.py launch --runtime C:/Games/McOsu-managed
```

`--import-from` copies `cfg/` (including profiles/backups/temp files), scores,
collections, optional star cache, screenshots and `version.txt`; it does not
share writable directories or import executables/launchers. It is only available
at initialization. Shut down the source runtime yourself before copying for a
consistent state snapshot. Config contents, including absolute external map/skin
paths, are copied verbatim: review them before launch. The CLI never imports or
rewrites settings implicitly. No defaults for pending channel/settings decisions
are implied by these commands.

Launch uses the absolute executable path and **explicit runtime cwd**, waits for
exit, returns its exit code, and holds the deployment lock throughout. Keep the
launcher console open. If it is closed/killed, the process-image guard still
protects a surviving game. It never stops an existing game. Additional game
arguments follow `--`; `launch --dry-run` prints the command/cwd without starting
it. `init`, `update`, `rollback`, and `recover` also accept `--dry-run`.

## Ownership, recovery and rollback

The game currently resolves assets and writes data relative to cwd. Deployment
therefore separates them **by file ownership** inside that flat layout:

- Owned: `McOsu.exe`, seven explicitly listed DLLs in `runtime.py`, and the exact
  manifest leaf files under the five asset directories. No directory mirroring.
- Preserved: every other file, including all `cfg/`, scores, collections, cache,
  screenshots, backups, unknown files and custom unowned asset neighbours.
  `version.txt` is writable game state (`OsuMainMenu::writeVersionFile`), so it is
  deliberately excluded from immutable payloads.
- Private metadata: `.mcosu-runtime/` stores the ownership marker, exclusive
  locks, the current and previous immutable bundles, queue/pin references,
  and a transaction journal. Do not edit this directory. Each distinct pending
  and pinned bundle adds at most one retained image; identical IDs share storage.

Updates validate the entire package before writes; refuse unmanaged destinations,
active images, modified managed files, unowned-file conflicts, links/junctions,
and concurrent operations; stage and revalidate a private package copy; journal
the pre-update pointers; replace/delete only owned leaves; then switch metadata
atomically. No user state is moved into a rollback bundle. If a payload or state
write fails after journaling, the tool attempts to restore the pre-update bundle,
leaving already correct files in place. The error reports whether restoration
finished; use `inspect` to check for pending recovery if it did not. An abrupt interruption blocks launch
and further updates until explicit recovery:

```powershell
python tools/runtime/runtime.py inspect --runtime C:/Games/McOsu-managed
python tools/runtime/runtime.py recover --runtime C:/Games/McOsu-managed
python tools/runtime/runtime.py rollback --runtime C:/Games/McOsu-managed --dry-run
python tools/runtime/runtime.py rollback --runtime C:/Games/McOsu-managed --acknowledge-state-risk
```

Recovery always restores the pre-transaction executable/assets, even if the
interruption occurred just before the commit point. It is retryable after a
second interruption. Rollback swaps current/previous bundles and retains the
newer writable state. **Cross-build preferences/database compatibility is
unverified**: back up writable state yourself before trying an older executable.
The acknowledgement makes that risk explicit; the tools neither migrate nor
silently revert scores or preferences. The same caution applies to any update
whose game revision changes a data format.

Use a local Windows filesystem and enough free space for staging, up to four
retained bundles, and the saved-state backup. This is a single-user CLI, not a security boundary against
concurrent manual file edits or a service enforcing immutable permissions.
Do not manually launch or edit a runtime during deployment. Windows image
enumeration plus image write checks protect externally started executables;
protected processes cannot all be enumerated. Recovery requires readable intact
bundles and a writable disk; physical disk loss/power-loss durability beyond OS
atomic rename/metadata flush guarantees is not promised. Abandoned pre-journal
staging is safe and reused/cleaned on the next update. Empty asset directories
may remain after removal of owned files.

## Integration tests

```powershell
$env:MCOSU_TEST_CC = 'C:/deps/mingw32/bin/gcc.exe'
python tools/runtime/tests/test_runtime.py
```

The suite compiles a tiny test-only console executable, exercises the real
deployment functions/CLI in disposable runtimes (including paths with spaces),
and never starts McOsu. It checks state bytes through update/rollback/recovery,
malformed/hash-mismatched packages, active images launched both through and
outside the CLI, locks, junctions, import copies, failed writes, hard process
interruption, bounded history and package-build integrity. Fixture code lives
only under `tests/`; normal packages contain only the verified payload allowlist.

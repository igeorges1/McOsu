# Verification — Windows, 2026-11-11

Implementation verified at `b772af3ae466bba6f87b10cba2b8a8bb4bcc340d`.
Subsequent evidence documentation does not change the build/deployment code or
game source. No gameplay/source behavior changes are part of this work.

- **13 Windows integration tests passed** in 12.770 seconds. They use the real
  deployment functions and a CLI-launched native fixture, not a game executable.
  Update, rollback and failure recovery preserve byte sentinels in configs,
  timing profiles, backup/temp files, both score databases, collections, cache,
  screenshots, `version.txt`, unrelated files and unowned asset neighbours.
- Rejected corrupt/invalid manifests, hashes, source/toolchain identity,
  unmanifested files, unmanaged destinations, active images, locks, junctions,
  changed owned files and conflicting unowned files before payload mutation.
  Explicit initial state import produces independent file copies.
- Injected write failure restored the original bundle automatically. Hard child
  process exit during update required recovery. Exit after the metadata switch,
  followed by another exit during recovery, restored the pre-update current and
  previous bundles; subsequent explicit rollback still worked.
- **Normal 208-unit Windows build and link passed** using GCC 8.1.0 i686,
  Win32 threads/DWARF2, C++11/O2, ordinary BASS, and the documented engine pin.
  Private engine/game snapshots were used. The engine entrypoint differs from
  the pin only in the three documented app-selection substitutions.
- **Normal package validated: 566 files**, with all payload hashes and the
  i686 executable/DLL dependency closure checked. It includes seven specified
  DLLs and normal release assets with revision-specific shader/model overlays.
  No fixtures, instrumentation drivers, settings, databases or private test
  cues are included. The package deployed into a disposable runtime; static
  inspection, state sentinel preservation and launch command/cwd dry-run passed.

Package ID:
`2ee82ccde518806522fd2ac1b93afc3a15521d5ea67ac8c5fb332c6186936e0c`

Normal executable SHA-256:
`25be5e8ee8e3e7156e27c8a0f98b8cc3c37e42012abb979befc5958f6867796e`

Local ignored evidence relative to `tools/runtime/`:

- `out/integration-tests.log`
- `out/normal-build-002.log`, `out/normal-build-002/build.json`, compiler/link logs
- `out/normal-package-002/manifest.json` and `payload/`
- `out/normal-verification.json`, `out/verify_normal.py`
- `out/disposable-normal-runtime/` (contains artificial sentinel data; do not play)

The earlier build `out/normal-build-001/` also compiled/linked successfully but
stopped at static validation because the system-DLL allowlist omitted BASS's
`MSACM32.dll` dependency. That classification was corrected and the clean build
was repeated; the earlier evidence was retained.

**Limits:** no actual playable game was launched. Tests prove launch mechanics
with the controlled native fixture; normal startup/gameplay/acoustics and
cross-build writable-state compatibility are unverified. No production runtime,
channel policy, auto-update service or merged-master installation was rolled out.
Personal installations, their settings, the original osu! library, sibling
feature checkouts and the user's running game were not modified or operated.

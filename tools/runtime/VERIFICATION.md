# Verification — Windows, 2026-11-11

## PR #3 correction: RT3-REVIEW-001

**19 Windows integration tests passed** in 19.260 seconds on the correction
code. The suite includes the original cases and six regressions:

- **SUP-002:** Read-only package assets no longer block rollback or collection.
  Staging copies file bytes without source attributes; legacy read-only leaves
  are cleared only inside private trees selected for removal.
- **SUP-003:** A blocked replacement restores the pre-update bundle without
  rewriting a read-only live file whose bytes are already correct. Recovery
  removes `replace.tmp` and reports whether restoration finished.
- **SUP-004:** A competing initializer cannot overwrite the winner's runtime.
  Failed first copies release an empty claim and leave partial imports intact.
  The supervisor's separate locked `scores.db` CLI reproduction recorded a
  successful retry after the fix, exact copied bytes, and unchanged source.
- **SUP-005:** The builder rejects an unignored output inside the checkout
  before dependency checks or compilation. The regression also confirms an
  ignored path passes the gate. The supervisor's pre-fix reproduction compiled
  208 units before failing the final clean-source check.

The supervisor also repackaged and validated the saved 566-file normal payload,
then ran init, update, inspect and launch dry-run in a disposable path with
spaces. The config sentinel was unchanged. No new normal executable was linked;
the build and binary identities below still describe the original artifact.

Local correction evidence: `out/rt3-review-001-final-tests.log`,
`out/supervisor-regressions-{red,green}.log`,
`out/supervisor-recheck-{red,green}.log`,
`out/supervisor-init-lock-{red,green}-001/result.json`,
`out/supervisor-unignored-build-red.log`, and `out/supervisor-cli-validation.json`.

## Original normal build and baseline

The normal build and baseline suite were verified at
`b772af3ae466bba6f87b10cba2b8a8bb4bcc340d`. No gameplay or game source changes
are part of this work.

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

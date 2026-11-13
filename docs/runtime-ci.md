# Runtime CI only

This additive branch is based on exact queued-updater PR5 source
`f10a6bdef405089eb7ef9389016da0d6569f430b`. Runtime product and test bytes are
unchanged. It does not import the timing/game stack. The separately proposed
capture-source builder change is not included in this CI-only branch.

The hosted job uses `windows-2022`, Python3.13 and the exact GCC8.1 i686/Win32/
DWARF2 distribution from the [official MinGW-w64 archive](https://sourceforge.net/projects/mingw-w64/files/Toolchains%20targetting%20Win32/Personal%20Builds/mingw-builds/8.1.0/threads-win32/dwarf/).
The archive is45077278bytes, SHA256
`28d0a0608d9524868f7feaf9f9ec5daf69669076eafc9e776af02d60ebfba93c`.
Provisioning also checks exact gcc/g++ hashes and version/target/thread/exception
identity. It uses the existing7-Zip from the runner image; no global installation
or silent fallback occurs. The script sets `MCOSU_TEST_CC` to this exact gcc.exe.

The same official action pins and byte-exact accepted Windows job guard are used
by the independent timing CI. Actions: [checkout](https://github.com/actions/checkout/commit/11d5960a326750d5838078e36cf38b85af677262),
[setup-python](https://github.com/actions/setup-python/commit/a26af69be951a213d495a4c3e4e4022e16d87065),
[upload-artifact](https://github.com/actions/upload-artifact/commit/ea165f8d65b6e75b540449e92b4886f43607fa02).
PR-head checkout has read-only contents permission and no persisted credentials.
There is no `pull_request_target`, deployment or repository-settings change.

The existing test file's main runs all28 Windows integration tests and emits
`COMPLETE failures=0 tests=28`. It compiles inert test-only console fixtures, not
McOsu. The supervisor requires both actual exit0 and that completion string:

```powershell
$env:MCOSU_TEST_CC = 'C:/dependencies/mingw32/bin/gcc.exe'
python .github/scripts/run_guarded.py --label runtime --timeout 240 --contains "COMPLETE failures=0 tests=28" -- python tools/runtime/tests/test_runtime.py
```

This is independent of helper verification. It exercises disposable migration,
queue/hold, backups, recovery, retention and rollback/process semantics without
personal runtime/library/config or game/UI/input. [Runtime CLI](../tools/runtime/README.md)
and [queue contract](../tools/runtime/QUEUED-PREVIEW.md) describe product behavior.
It does not prove saved-data format compatibility with later games or acoustics.

Nonmodal reporting, owned kill-on-close process jobs, actual exit/stdout/stderr/
source identities and a240s outer test deadline are recorded under `.ci-runs`.
Provisioning has its own transfer/extraction/probe bounds; the job ceiling is15min.
Readable artifacts upload on success/failure for14days; cancellation/host or
artifact-service loss can prevent upload. Missing/incomplete records are not green.
No test is intentionally skipped to pass. Local preparation is not hosted success
or independent acceptance; the publisher must inspect the actual workflow run.

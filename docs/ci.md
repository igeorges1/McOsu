# Bounded hosted software verification

The timing workflow runs the existing supported full helper profile and its
runner-contract profile on `windows-2022`, Python3.13, and a complete extracted
GCC8.1 i686/Win32-thread/DWARF2 toolchain. It does not build or run McOsu or claim
backend, pixel, physical input, acoustic or player acceptance. Later capture and
performance layers may add explicit synthetic consumer checks.

Actions are pinned to official immutable commits:

- [checkout v4.4.0](https://github.com/actions/checkout/commit/11d5960a326750d5838078e36cf38b85af677262)
- [setup-python v5.6.0](https://github.com/actions/setup-python/commit/a26af69be951a213d495a4c3e4e4022e16d87065)
- [upload-artifact v4.6.2](https://github.com/actions/upload-artifact/commit/ea165f8d65b6e75b540449e92b4886f43607fa02)

Checkout tests the explicit PR head with read-only contents permission and does
not persist credentials. There is no `pull_request_target`, deployment, secret,
repository-settings mutation or executable downloaded from a PR artifact.

## Provisioning identity

The [official MinGW-w64 distribution directory](https://sourceforge.net/projects/mingw-w64/files/Toolchains%20targetting%20Win32/Personal%20Builds/mingw-builds/8.1.0/threads-win32/dwarf/)
contains `i686-8.1.0-release-win32-dwarf-rt_v6-rev0.7z`. The provisioning script
uses its explicit HTTPS download URL, exact45077278byte size and SHA256
`28d0a0608d9524868f7feaf9f9ec5daf69669076eafc9e776af02d60ebfba93c`.
This locks the previously used archive, not a publisher signature. Extraction
uses the image's existing7-Zip and a fresh explicit output directory. Nothing is
installed globally. Extracted gcc/g++ hashes and compiler version/target/thread/
exception probes must also match. A missing tool, failed download, HTML response,
changed hash, timeout or compiler mismatch fails the job; no fallback/skip is green.
The [runner image inventory](https://github.com/actions/runner-images/blob/main/images/windows/Windows2022-Readme.md)
documents the image dependencies. Exact observed versions are retained in receipts.

An offline copy can be supplied explicitly for local reproduction, with the same
size/hash checks. From Windows with Python3.13 and7-Zip:

```powershell
python .github/scripts/provision_mingw.py --out C:/temporary/fresh-gcc8 --archive C:/dependencies/i686-8.1.0-release-win32-dwarf-rt_v6-rev0.7z
python .github/scripts/run_guarded.py --label timing --timeout 180 --contains "COMPLETE failures=0 checks=" -- python tools/verify.py --toolchain C:/temporary/fresh-gcc8/mingw32
python .github/scripts/run_guarded.py --label runner-contract --timeout 120 --contains "PASS runner-contract: exit=0x00000000 timeout=False" --contains "COMPLETE failures=0 checks=4" -- python tools/verify.py --toolchain C:/temporary/fresh-gcc8/mingw32 --profile runner-contract
```

## Failure and evidence boundaries

The CI process guard is an exact copy of the accepted
`tools/verification_process.py` from original2c9; it exists in `.github/scripts`
so the independent runtime-CI branch can use the same guard without importing
game product code. The supervisor records source/tree, actual executable/PID/
exit, streams and completion requirements. It uses nonmodal Windows reporting,
owned kill-on-close jobs and external deadlines. Existing runner assertions and
first-failure semantics stay enabled. Contract negatives are expected only inside
the named contract profile; an unexpected failure stops subsequent checks.

The job has a15minute ceiling. Download has30s socket and180s transfer budgets;
extraction120s, compiler probes15s, outer timing180s and contract120s bounds apply.
Cancellation, host loss or artifact-service failure may prevent final upload;
an incomplete receipt is not success. The `always()` artifact step retains only
`.ci-runs` and `.verification-runs`, including readable stdout/stderr and exact
inputs/receipts, for14days. No personal maps/config/captures or entire workspace
is uploaded. Expected red regression and contract cases remain labelled.

Local preparation is not hosted success or independent acceptance. The publisher
must inspect actual workflow results after pushing; no hosted result exists
merely because YAML and the same commands passed locally. Runtime updater tests
belong to their independent tooling branch, not a duplicate product in this stack.

## Gameplay offline job

The additive `gameplay-verification.yml` job keeps the timing helper job intact.
It runs on Windows 2022 with the same pinned Python action and exact GCC8.1
archive. The hosted image supplies x64 MSVC and the Windows SDK through its
Visual Studio developer environment. Compiler paths and executable hashes are
recorded per run; this is not a claim that MSVC image contents are immutable.

`.github/scripts/gameplay_smoke.py` compiles and executes the actual App raw-frame
helper and native reader predicate fixture. The latter covers the existing
shape, strict typed V4 and uninterpreted-boundary cases, plus actual synthetic
JSON emission and declared loss/lifecycle/overflow/sticky-failure refusals.
It also runs the gameplay attribution and raw-contract Python suites and the
generated settings/reference inventory. Native refusal exit 3 is expected only
for the named synthetic negative cases, with withheld Events and explicit flags.
No trace is opened by those fixture modes.

Each compiler has a 60-second bound; each helper or Python suite has a 15-second
bound. Every child uses an owned Job, 1 GiB memory and a shared 1 MiB stdout/stderr
allowance. Actual PID, executable hash, exit, timeout, stream and completion checks
are retained before interpreting the result. The entire smoke command has a
240-second external bound. Source/tree, input hashes and individual unittest
counts are recorded; any unexpected failure stops the remaining checks.
Readable `.ci-runs` evidence uploads on success or failure for 14 days.

This job does not build or start the game, use private route015, query tokens,
request UAC, start or stop ETW, inspect devices, play a sound, open a real ETL or
deploy a package. SDK/.NET reader predicates retain their separate local evidence;
this job does not restore or build that alternative reader. Offline CI success
does not qualify operator installation, live recording, physical latency,
representative overhead or a player's stutter cause. Actual hosted execution
must be observed at the published commit before reporting it as passed.

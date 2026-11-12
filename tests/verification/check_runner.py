"""Small controlled negative probes for the real process/result seam (all intentional)."""
import argparse
import json
import os
from pathlib import Path
import sys

# This script runs from the runner's immutable source snapshot.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from verify import Failure, FLAGS, Run
from verification_process import execute


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir()
    receipts = []

    def process(label, argv, timeout=15):
        result = execute(argv, args.out, os.environ.copy(), timeout,
                         args.out / (label + ".stdout"), args.out / (label + ".stderr"))
        result["label"] = label
        result["intentional_contract_probe"] = True
        receipts.append(result)
        (args.out / "processes.json").write_text(json.dumps(receipts, indent=2), encoding="utf-8")
        return result

    def contents(result, stream):
        return Path(result[stream]).read_text(encoding="utf-8", errors="replace")

    # 1: independent streams and actual exit, even with a misleading marker.
    result = process("exit7", [sys.executable, "-c", "import sys; print('COMPLETE false failures=0'); print('detail', file=sys.stderr); sys.exit(7)"])
    assert result["exit"] == 7 and not result["timeout"]
    assert "COMPLETE" in contents(result, "stdout") and "detail" in contents(result, "stderr")

    # 2: a real compile failure is not a historical RED.
    bad = args.out / "invalid.cpp"
    bad.write_text('#include "deliberately-missing-verification-header.h"\n', encoding="utf-8")
    result = process("compile-failure", [args.compiler, *FLAGS, bad, "-o", args.out / "invalid.exe"], 30)
    assert result["exit"] != 0 and not result["timeout"] and not (args.out / "invalid.exe").exists()
    assert "deliberately-missing-verification-header.h" in contents(result, "stderr")

    # 3: the promoted assertion guard really exits nonmodally with enabled assert.
    guard = Path(__file__).resolve().parent / "ConsoleCheckAssertions.h"
    assertion = args.out / "assertion.cpp"
    assertion.write_text('#include <vector>\n#include <cassert>\n#include "' + guard.as_posix() + '"\nint main() { assert(false); }\n', encoding="utf-8")
    binary = args.out / "assertion-probe.exe"
    result = process("assert-compile", [args.compiler, *FLAGS, assertion, "-o", binary], 30)
    assert result["exit"] == 0 and not result["timeout"]
    result = process("assert-run", [binary])
    assert result["exit"] == 1 and not result["timeout"] and "VERIFICATION_ASSERT" in contents(result, "stderr")

    # 4: deadline bounds a spawned descendant too. Job cleanup is handle-owned.
    pidfile = args.out / "descendant.pid"
    script = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); open(sys.argv[1],'w').write(str(p.pid)); time.sleep(60)"
    result = process("timeout", [sys.executable, "-c", script, str(pidfile)], 1)
    assert result["timeout"] and result["exit"] is not None and not result["owned_process_remaining"]
    assert pidfile.is_file()
    import ctypes
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    api.OpenProcess.restype = ctypes.c_void_p
    api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = api.OpenProcess(0x100000, False, int(pidfile.read_text()))
    if handle:
        try:
            assert api.WaitForSingleObject(handle, 3000) == 0, "Owned descendant survived deadline"
        finally:
            api.CloseHandle(handle)

    # 5/6: use the actual Run.command acceptance function, not a parallel model.
    class Probe:
        command = Run.command
        def __init__(self):
            self.out = args.out
            self.env = os.environ.copy()
            self.record = {"checks": []}
        def save(self):
            (self.out / "classification.json").write_text(json.dumps(self.record, indent=2), encoding="utf-8")

    probe = Probe()
    for label, script in (("missing-completion", "pass"),
                          ("misleading-completion", "import sys; print('COMPLETE probe failures=0'); sys.exit(7)")):
        try:
            probe.command(label, [sys.executable, "-c", script], 15,
                          marker="COMPLETE probe failures=0", intentional=True)
        except Failure:
            assert probe.record["first_failure"]["label"] == label
        else:
            raise AssertionError(label + " was incorrectly accepted")
    print("COMPLETE runner-contract failures=0 tests=6", flush=True)


if __name__ == "__main__":
    main()

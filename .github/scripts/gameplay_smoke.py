"""Bounded offline gameplay checks; no capture, game, token or ETL inputs."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from gameplay_process import execute

MIB = 1024 * 1024


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    if os.name != "nt":
        raise ValueError("Windows compiler and owned Job guard required")
    output = ROOT / ".ci-runs" / ("gameplay-offline-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                                 + "-" + uuid.uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    record = dict(complete=False, scope="offline production helpers and synthetic predicates only",
                  source=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                                 text=True, timeout=15).strip(),
                  tree=subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT,
                                               text=True, timeout=15).strip(),
                  processes=[], inputs={})
    receipt = output / "result.json"

    def save():
        receipt.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    save()
    try:
        gcc = Path(os.environ["MCOSU_TOOLCHAIN"]) / "bin" / "g++.exe"
        cl = shutil.which("cl.exe")
        if not gcc.is_file() or not cl:
            raise ValueError("Explicit provisioned GCC and x64 MSVC developer environment required")
        cl = Path(cl).resolve(strict=True)
        paths = ["tests/OsuGameplayCaptureTest.cpp", "tests/gameplay_raw_reader_test.cpp",
                 "tests/gameplay_attribution_test.py", "tests/gameplay_raw_test.py",
                 "tests/check-timing-audio-settings.py", "docs/timing-audio-controls.md",
                 "tools/gameplay-raw-reader/witness.cpp", "tools/gameplay_attribution.py",
                 "tools/gameplay_budget.py", "tools/gameplay_collector.py", "tools/gameplay_raw.py",
                 "tools/gameplay_record.py", "tools/gameplay_process.py", "tools/verification_process.py",
                 ".github/scripts/gameplay_smoke.py", ".github/scripts/gameplay_smoke.cmd",
                 ".github/workflows/gameplay-verification.yml"]
        paths += [str(p.relative_to(ROOT)).replace("\\", "/")
                  for p in (ROOT / "src/App/Osu").glob("OsuGameplay*.h")]
        paths += ["src/App/Osu/OsuPerformanceHistory.h"]
        record["inputs"] = {p: sha(ROOT / p) for p in sorted(set(paths))}
        record["compilers"] = {str(p): sha(p) for p in (gcc, cl)}
        save()
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUTF8"] = "1"
        for key in ("CPATH", "CPLUS_INCLUDE_PATH", "C_INCLUDE_PATH", "LIBRARY_PATH",
                    "GCC_EXEC_PREFIX", "COMPILER_PATH"):
            env.pop(key, None)
        env["PATH"] = str(gcc.parent) + os.pathsep + env.get("PATH", "")

        def run(label, argv, seconds, markers=(), unittest=False, expected_exit=0, negative_reason=None):
            if expected_exit and (not negative_reason or not markers):
                raise ValueError("An expected refusal needs a declared reason and completion marker")
            out, err = output / (label + ".stdout.log"), output / (label + ".stderr.log")
            process = execute([str(a) for a in argv], output, env, seconds, out, err,
                              memory_limit=MIB * 1024, stream_limit=MIB)
            process["label"] = label
            process["expected_exit"] = expected_exit
            process["intentional_negative"] = negative_reason
            record["processes"].append(process)
            save()  # retain actual status before interpreting completion
            stdout, stderr = out.read_text(errors="replace"), err.read_text(errors="replace")
            text = (stdout + "\n" + stderr).replace("\r\n", "\n")
            ok = (process["exit"] == expected_exit and not process["timeout"] and not process["error"]
                  and not process["owned_process_remaining"] and not process.get("stream_truncated")
                  and all(marker in text for marker in markers))
            if unittest:
                count = re.search(r"(?m)^Ran ([1-9][0-9]*) tests? in ", text)
                ok = ok and count is not None and re.search(r"(?m)^OK$", text) is not None
                process["test_count"] = int(count.group(1)) if count else None
                save()
            if not ok:
                print("TEST-FAULT gameplay offline " + label + " receipt=" + str(receipt), flush=True)
                print(stdout, end="", flush=True)
                print(stderr, end="", file=sys.stderr, flush=True)
                raise ValueError(label + " failed exit/deadline/stream/completion checks")
            print("PASS gameplay offline " + label + " pid=" + str(process["pid"])
                  + " exit=" + str(process["exit"]), flush=True)
            return stdout

        frame = output / "frame.exe"
        run("frame-compile", [gcc, "-std=c++11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
                              "-UNDEBUG", ROOT / "tests/OsuGameplayCaptureTest.cpp", "-o", frame], 60)
        record["frame_executable_sha256"] = sha(frame)
        save()
        run("frame", [frame], 15, ["COMPLETE gameplay raw frame cases"])
        native = output / "raw-predicates.exe"
        run("native-compile", [cl, "/nologo", "/W4", "/WX", "/std:c++17", "/EHsc", "/MT", "/O2",
                               "/UNDEBUG", "/DUNICODE", "/D_UNICODE", ROOT / "tests/gameplay_raw_reader_test.cpp",
                               "/Fo:" + str(output / "raw-predicates.obj"), "/Fe:" + str(native),
                               "tdh.lib", "advapi32.lib"], 60)
        record["native_predicates_sha256"] = sha(native)
        save()
        run("native", [native], 15, ["COMPLETE raw witness shape predicates cases=11",
                                    "COMPLETE strict CSwitch v4 predicates cases=26",
                                    "COMPLETE private boundary native predicates"])
        for mode, rejected_field in (("emit", None), ("loss", "Loss"), ("lifecycle", "ThreadPair"),
                                     ("overflow", "Overflow"), ("sticky", "InvalidScheduler")):
            expected = 0 if mode == "emit" else 3
            marker = ("COMPLETE" if expected == 0 else "INCONCLUSIVE") + " raw gameplay scheduler evidence"
            stdout = run("native-" + mode, [native, "--" + mode], 15, [marker], expected_exit=expected,
                         negative_reason=None if mode == "emit" else "synthetic " + mode + " must withhold Events")
            lines = stdout.splitlines()
            if len(lines) != 2 or lines[1] != marker:
                raise ValueError("Unexpected native fixture output envelope")
            payload = json.loads(lines[0])
            if type(payload.get("WireSchema")) is not int or payload["WireSchema"] != 2:
                raise ValueError("Native fixture wire schema changed")
            if mode == "emit":
                events = payload.get("Events")
                if (payload.get("BoundaryRecords") != 1 or not isinstance(events, list) or len(events) != 1
                        or events[0].get("Kind") != "B" or events[0].get("Detail") != 2):
                    raise ValueError("Native fixture did not retain its uninterpreted boundary")
            elif (payload.get("Events") != []
                  or payload.get(rejected_field) is not (False if mode == "lifecycle" else True)):
                raise ValueError("Native refusal fixture did not preserve rejection and withhold Events")
        run("policy", [sys.executable, "-I", "-B", ROOT / "tests/gameplay_attribution_test.py"],
            15, unittest=True)
        run("raw-contract", [sys.executable, "-I", "-B", ROOT / "tests/gameplay_raw_test.py"],
            15, unittest=True)
        run("metadata", [sys.executable, "-I", "-B", ROOT / "tests/check-timing-audio-settings.py"],
            15, ["PASS:", "settings plus raw analyzer controls match source and tracked reference"])
        record.update(complete=True, result="PASS", checks=5)
        save()
        print("COMPLETE gameplay offline failures=0 checks=5 receipt=" + str(receipt), flush=True)
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        record.update(complete=True, result="FAIL", error=str(error))
        save()
        print("TEST-FAULT gameplay offline " + str(error) + " receipt=" + str(receipt), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

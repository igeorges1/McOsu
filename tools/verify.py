"""Supported timing/HUD verification. See docs/verification.md. No third-party Python packages."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from verification_process import digest, execute, nonmodal

ROOT = Path(__file__).resolve().parents[1]
SUITES = tuple("OsuTimingAudio" + name + "Test" for name in
               ("Band", "Boundary", "HUD", "Idle", "Reference", "Settings", "Setup", "State"))
FLAGS = ["-std=c++11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic", "-UNDEBUG"]
CASE = "preroll-history"


class Failure(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Failure(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def read(path):
    return path.read_text(encoding="utf-8", errors="replace")


class Run:
    def __init__(self, args):
        self.args = args
        # A caller cannot select a destructive destination or reuse another run.
        parent = ROOT / ".verification-runs"
        require(not parent.is_symlink() and not (parent.exists() and parent.resolve() != parent),
                "Output root must be a normal checkout-owned .verification-runs directory")
        parent.mkdir(exist_ok=True)
        self.out = parent / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8])
        self.out.mkdir()
        self.env = os.environ.copy()
        self.env.pop("PYTHONOPTIMIZE", None)
        # Avoid compiler include/library injection from an unrelated shell.
        for key in ("CPATH", "CPLUS_INCLUDE_PATH", "C_INCLUDE_PATH", "LIBRARY_PATH", "GCC_EXEC_PREFIX", "COMPILER_PATH"):
            self.env.pop(key, None)
        self.record = {"schema": "mcosu-verification-v1", "complete": False, "result": "RUNNING",
                       "profile": args.profile, "case": args.case, "checks": [], "first_failure": None,
                       "output": str(self.out), "flags": FLAGS, "engine_dependency": None,
                       "python": {"executable": sys.executable, "version": sys.version,
                                  "sha256": digest(sys.executable)}, "platform": sys.platform,
                       "invocation": sys.argv, "caller_cwd": os.getcwd()}
        self.save()

    def save(self):
        temporary = self.out / "run.json.tmp"
        temporary.write_text(json.dumps(self.record, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.out / "run.json")

    def command(self, label, argv, seconds, expected=0, marker=None, observed=None, intentional=False):
        self.record["pending_check"] = label
        self.save()
        check = execute(argv, self.out, self.env, seconds,
                        self.out / (label + ".stdout.log"), self.out / (label + ".stderr.log"))
        check.update(label=label, expected_exit=expected, required_stdout=marker,
                     required_observed=observed, intentional_negative=intentional)
        out, err = read(Path(check["stdout"])), read(Path(check["stderr"]))
        passed = (not check["error"] and not check["timeout"] and check["exit"] == expected
                  and (marker is None or marker in out)
                  and (observed is None or observed in out)
                  and not check["owned_process_remaining"])
        # RED must be the exact intended assertion, never an arbitrary exit 1.
        if label == "preroll-history-old":
            passed = passed and "VERIFICATION_ASSERT" in err and "waiting.count == 1 && waiting.meanMS == -50" in err
        check["result"] = "PASS" if passed else "FAIL"
        self.record["checks"].append(check)
        self.record.pop("pending_check", None)
        if not passed:
            self.record["first_failure"] = check
        self.save()
        print(f"{check['result']} {label}: exit={check['exit_hex']} timeout={check['timeout']}", flush=True)
        if not passed:
            print("VERIFICATION_FAULT " + json.dumps(check, separators=(",", ":")), flush=True)
            raise Failure("Failed " + label + "; see " + check["stderr"])
        return out, err

    def git(self, *args):
        return subprocess.check_output(["git", "-c", "safe.directory=" + str(ROOT), "-C", str(ROOT), *args],
                                       timeout=10, text=True, stderr=subprocess.STDOUT).strip()

    def preflight(self):
        require(sys.version_info >= (3, 13), "Requires Python 3.13+")
        require(os.name == "nt", "Supported profile requires Windows and GCC8.1 i686 Win32/DWARF2")
        require(not sys.flags.optimize, "Run Python without -O: inventory assertions are mandatory")
        self.record["source"] = {"root": str(ROOT), "head": self.git("rev-parse", "HEAD"),
                                 "tree": self.git("rev-parse", "HEAD^{tree}"),
                                 "branch": self.git("branch", "--show-current"),
                                 "status": self.git("status", "--porcelain=v1", "--untracked-files=all")}
        actual = {p.stem for p in (ROOT / "tests").glob("OsuTimingAudio*Test.cpp")}
        require(actual == set(SUITES), f"Expected exactly eight registered suites; missing={set(SUITES)-actual}, unregistered={actual-set(SUITES)}")
        inputs = list((ROOT / "src/App/Osu").glob("OsuTimingAudio*.h"))
        for name in ("Evaluation", "RecentWindow", "PlayClock", "HUD", "Reference", "Settings", "HudControls", "Setup", "State"):
            require((ROOT / "src/App/Osu" / ("OsuTimingAudio" + name + ".h")).is_file(), "Missing production header: " + name)
        inputs += [ROOT / "tests" / (suite + ".cpp") for suite in SUITES]
        inputs += [ROOT / "tests/check-timing-audio-settings.py", ROOT / "docs/timing-audio-controls.md"]
        inputs += [ROOT / "src/App/Osu" / name for name in
                   ("OsuTimingAudioFeedback.cpp", "OsuHUD.cpp", "OsuBeatmap.cpp", "OsuTimingAudioOptions.cpp", "OsuOptionsMenu.cpp")]
        inputs += [p for p in (ROOT / "tests/verification").rglob("*") if p.is_file()]
        inputs += [ROOT / "tools/verify.py", ROOT / "tools/verification_process.py"]
        required = ["ConsoleCheckAssertions.h", "PrerollHistory.cpp", "preroll-history/manifest.json"]
        require(all((ROOT / "tests/verification" / p).is_file() for p in required), "Missing verification fixture/support")
        self.hashes = {}
        self.snapshot = self.out / "source"
        for path in sorted(set(inputs)):
            require(path.is_file() and path.stat().st_size > 0, "Missing or empty input: " + str(path))
            relative = path.relative_to(ROOT).as_posix()
            target = self.snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            self.hashes[relative] = digest(target)
        fixture = self.snapshot / "tests/verification/preroll-history"
        manifest = json.loads(read(fixture / "manifest.json"))
        require(manifest["case"] == CASE and set(manifest["sources"]) == {"old", "fixed"}, "Incomplete case manifest")
        revisions = {"old": "2f5d88bab2f89d33e50ab9ddde014ceac480505d", "fixed": "5f2289edce8c4060d0e9f314c945fd5701d09d46"}
        for label, source in manifest["sources"].items():
            require(source["revision"] == revisions[label], "Wrong historical revision")
            require(set(source["files"]) == {"OsuTimingAudioEvaluation.h", "OsuTimingAudioRecentWindow.h"}, "Incomplete historical dependencies")
            for name, identity in source["files"].items():
                path = fixture / label / name
                require(path.is_file() and digest(path) == identity["sha256"], "Historical hash mismatch: " + str(path))
                data = path.read_bytes()
                blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
                require(blob == identity["blob"] and identity["path"] == "src/App/Osu/" + name, "Historical Git provenance mismatch")
        self.record["input_sha256"] = self.hashes
        self.record["input_tree_sha256"] = hashlib.sha256(canonical(self.hashes)).hexdigest()
        self.record["regression"] = manifest
        # Legacy MinGW resolves include paths through MAX_PATH-limited APIs even
        # when argv is relative. Keep native compilation in a shallow staging
        # layout; the full immutable source snapshot remains the evidence.
        require(len(str(self.out)) <= 220, "GCC8 path limit: use a shallower source checkout (run cwd must be <=220 characters)")
        stages = {"h": self.snapshot / "src/App/Osu",
                  "o": fixture / "old", "f": fixture / "fixed"}
        self.record["staged_headers"] = {}
        for folder, origin in stages.items():
            target = self.out / folder
            target.mkdir()
            for header in origin.glob("*.h"):
                shutil.copyfile(header, target / header.name)
                self.record["staged_headers"][folder + "/" + header.name] = digest(target / header.name)
        (self.out / "g").mkdir()
        shutil.copyfile(self.snapshot / "tests/verification/ConsoleCheckAssertions.h", self.out / "g/ConsoleCheckAssertions.h")
        shutil.copyfile(self.snapshot / "tests/verification/PrerollHistory.cpp", self.out / "case.cpp")
        for name in ("g/ConsoleCheckAssertions.h", "case.cpp"):
            self.record["staged_headers"][name] = digest(self.out / name)
        self.save()
        toolchain = Path(self.args.toolchain).resolve()
        self.compiler = toolchain / "bin/g++.exe"
        require(self.compiler.is_file(), "Missing compiler: " + str(self.compiler))
        self.env["PATH"] = str(toolchain / "bin") + os.pathsep + self.env.get("PATH", "")
        self.record["effective_PATH"] = self.env["PATH"]
        for option in ("-dumpversion", "-dumpmachine", "-v"):
            out, err = self.command("compiler" + option, [self.compiler, option], 15)
            if option == "-dumpversion":
                require(out.strip() == "8.1.0", "Requires GCC 8.1.0")
            elif option == "-dumpmachine":
                require(out.strip() == "i686-w64-mingw32", "Requires i686-w64-mingw32")
            else:
                require("Thread model: win32" in err and "--with-dwarf2" in err, "Requires Win32 threads/DWARF2")
        inventory = {p.relative_to(toolchain).as_posix(): digest(p) for p in sorted(toolchain.rglob("*")) if p.is_file()}
        self.record["toolchain"] = {"root": str(toolchain), "version": "8.1.0", "target": "i686-w64-mingw32",
                                    "threads": "win32", "exceptions": "dwarf2", "files": inventory,
                                    "tree_sha256": hashlib.sha256(canonical(inventory)).hexdigest()}
        self.save()

    def compile(self, label, source, extra=()):
        # Neutral name avoids Windows Setup/installer detection heuristics.
        executable = self.out / (label.replace("Setup", "Readout") + ".exe")
        # GCC8's Win32 file APIs reject long absolute include paths. Every owned
        # compile input/output is below cwd; keep compiler arguments relative.
        def relative(value):
            return str(value.relative_to(self.out)) if isinstance(value, Path) else value
        self.command(label + "-compile", [self.compiler, *FLAGS, *map(relative, extra),
                                         relative(source), "-o", relative(executable)], self.args.compile_timeout)
        require(executable.is_file() and executable.stat().st_size > 0, "Compiler produced no executable")
        return executable

    def timing(self):
        for suite in SUITES:
            path = self.snapshot / "tests" / (suite + ".cpp")
            text = read(path)
            # Keep original bytes on disk; transformation is recorded separately.
            require(text.count("int main()") == 1 and text.rstrip().endswith("}"), "Unsupported test entry: " + suite)
            text = text.replace("int main()", "int verification_test_body()", 1)
            # Replace cassert only; custom CHECK macros stay exactly as authored.
            text = text.replace("#include <cassert>", "")
            text = text.replace('"../src/App/Osu/', '"../h/')
            include_end = max(m.end() for m in re.finditer(r'^#include[^\n]*', text, re.MULTILINE))
            guard = '\n#include "../g/ConsoleCheckAssertions.h"\n'
            text = text[:include_end] + guard + text[include_end:]
            end = text.rfind("}")
            text = text[:end] + "\nreturn 0;\n" + text[end:]
            text += f'\nint main() {{ const int result = verification_test_body(); if (result == 0) std::puts("COMPLETE {suite} failures=0"); return result; }}\n'
            generated = self.out / "t" / (suite.removeprefix("OsuTimingAudio").removesuffix("Test") + ".cpp")
            generated.parent.mkdir(exist_ok=True)
            # Relative original product paths are resolved using the original tests cwd include directory.
            generated.write_text(text, encoding="utf-8", newline="\n")
            self.record.setdefault("generated_tests", {})[suite] = {
                "original_sha256": self.hashes["tests/" + suite + ".cpp"],
                "generated_sha256": digest(generated), "path": str(generated),
                "transformation": "Relocate product includes; remove cassert include; guard after all includes; rename main; append return 0 and completion wrapper"}
            self.save()
            executable = self.compile(suite, generated)
            self.command(suite, [executable], self.args.test_timeout, marker=f"COMPLETE {suite} failures=0")
        self.command("settings-inventory", [sys.executable, "-B", self.snapshot / "tests/check-timing-audio-settings.py"],
                     self.args.test_timeout, marker="capture settings match registration and tracked reference")

    def capture(self):
        require(not self.record["source"]["status"], "Replay requires a clean checkout of the captured source")
        origin = Path(self.args.capture).resolve()
        limit = 40 * 1024 * 1024
        require(origin.is_file() and 0 < origin.stat().st_size <= limit, "Capture missing, empty or over 40 MiB")
        with origin.open("rb") as stream:
            data = stream.read(limit + 1)
        require(0 < len(data) <= limit, "Capture missing, empty or over 40 MiB")
        target = self.out / "capture.mct"
        target.write_bytes(data)
        self.record["capture"] = {"origin": str(origin), "bytes": len(data), "sha256": digest(target)}
        self.save()
        trailer = re.search(rb"\nchecksum ([0-9a-f]{16})\n\Z", data[-27:])
        require(trailer is not None, "Missing capture checksum; report may be truncated")
        value = 14695981039346656037
        for byte in memoryview(data)[:-26]:
            value = ((value ^ byte) * 1099511628211) & 0xffffffffffffffff
        require(f"{value:016x}".encode() == trailer.group(1), "Capture checksum mismatch; report may be corrupt")
        source = self.out / "capture.cpp"
        shutil.copyfile(self.snapshot / "tests/verification/TimingCapture.cpp", source)
        self.record["staged_headers"]["capture.cpp"] = digest(source)
        self.record["staged_headers"]["capture.mct"] = digest(target)
        self.save()
        executable = self.compile("timing-capture", source, ("-I", self.out / "h"))
        try:
            self.command("capture-replay", [executable, target.name, self.record["source"]["head"]],
                         self.args.test_timeout, marker="COMPLETE capture failures=0")
        except Failure:
            print(read(self.out / "capture-replay.stderr.log").rstrip(), flush=True)
            raise

    def regression(self):
        for label in ("old", "fixed", "current"):
            include = self.out / {"old": "o", "fixed": "f", "current": "h"}[label]
            flags = ["-I", include, "-I", self.out / "g"]
            if label == "old":
                flags += ["-DHISTORICAL_API"]
            elif label == "fixed":
                flags += ["-DFIXED_API"]
            name = CASE + "-" + label
            executable = self.compile(name, self.out / "case.cpp", flags)
            self.command(name, [executable], self.args.test_timeout,
                         expected=1 if label == "old" else 0,
                         marker=None if label == "old" else "COMPLETE preroll-history failures=0",
                         observed="waiting_count=0 waiting_mean=0 final_count=1 final_mean=0 expected=1,-50,2,-25" if label == "old"
                         else "waiting_count=1 waiting_mean=-50 final_count=2 final_mean=-25 expected=1,-50,2,-25",
                         intentional=label == "old")

    def finish(self):
        require(all(digest(ROOT / path) == value for path, value in self.hashes.items()), "Source inputs changed during run")
        require(all(digest(self.out / path) == value for path, value in self.record["staged_headers"].items()), "Staged compile inputs changed during run")
        require(self.record["checks"], "No executed checks")
        self.record.update(complete=True, result="PASS")
        self.save()


def positive(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0 or result > 300:
        raise argparse.ArgumentTypeError("Deadline must be finite, >0 and <=300 seconds")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", help="Explicit extracted GCC8.1 mingw32 directory for timing checks and replay")
    parser.add_argument("--profile", choices=["timing", "runner-contract"], default="timing")
    parser.add_argument("--case", choices=[CASE], help="Run only the named historical/current case, after common preflight")
    parser.add_argument("--capture", help="Replay an exported timing capture from this exact clean source revision")
    parser.add_argument("--performance", help="Analyze an exported performance.csv and produce a timeline")
    parser.add_argument("--compile-timeout", type=positive, default=60)
    parser.add_argument("--test-timeout", type=positive, default=15)
    args = parser.parse_args()
    if args.performance:
        if args.capture or args.case or args.profile != "timing":
            parser.error("--performance is separate from timing verification and replay")
        from performance_capture import analyze
        try:
            analyze(args.performance, ROOT)
        except (OSError, ValueError, OverflowError) as error:
            print("FAIL " + str(error), flush=True)
            return 1
        return 0
    if not args.toolchain:
        parser.error("--toolchain is required for timing checks and replay")
    parser.error("--case requires --profile timing") if args.case and args.profile != "timing" else None
    if args.capture and (args.case or args.profile != "timing"):
        parser.error("--capture is a separate run from --case or --profile runner-contract")
    nonmodal()
    run = None
    try:
        run = Run(args)
        print("RUN " + str(run.out), flush=True)
        run.preflight()
        if args.capture:
            run.capture()
        elif args.profile == "runner-contract":
            run.command("runner-contract", [sys.executable, "-B", run.snapshot / "tests/verification/check_runner.py",
                                            "--compiler", run.compiler, "--out", run.out / "contract"],
                        60, marker="COMPLETE runner-contract failures=0 tests=6")
        else:
            if not args.case:
                run.timing()
            run.regression()
        run.finish()
    except (Failure, OSError, ValueError, KeyError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        if run:
            run.record.update(result="FAIL", error=str(error))
            if not run.record["first_failure"]:
                run.record["first_failure"] = {"stage": run.record.get("pending_check", "preflight/finalize"), "error": str(error)}
            run.save()
            print("VERIFICATION_FAULT " + json.dumps(run.record["first_failure"], separators=(",", ":")), flush=True)
        print("FAIL " + str(error), flush=True)
        return 1
    print(f"COMPLETE failures=0 checks={len(run.record['checks'])} receipt={run.out / 'run.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

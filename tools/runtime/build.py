"""Build a clean McOsu revision against a private snapshot of the pinned McEngine."""
import argparse
import concurrent.futures
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import zipfile

from runtime import (ASSETS, DLLS, ENGINE_PIN, Refusal, canonical, digest, files,
                     make_package, no_links, require, write_json)
import hashlib


LIBRARIES = ("freetype", "opengl32", "glew32", "glu32", "gdi32", "bass", "bass_fx",
             "comctl32", "Dwmapi", "Comdlg32", "psapi", "ws2_32", "winmm", "pthread",
             "libjpeg", "atomic")
FLAGS = ["-O2", "-Wall", "-c", "-fmessage-length=0", "-Wno-sign-compare",
         "-Wno-unused-local-typedefs", "-Wno-reorder", "-Wno-switch"]
SYSTEM_DLLS = {"kernel32.dll", "user32.dll", "gdi32.dll", "msvcrt.dll", "advapi32.dll",
               "shell32.dll", "ole32.dll", "oleaut32.dll", "comdlg32.dll", "comctl32.dll",
               "dwmapi.dll", "psapi.dll", "ws2_32.dll", "winmm.dll", "opengl32.dll",
               "glu32.dll", "version.dll", "imm32.dll", "ntdll.dll", "shlwapi.dll", "msacm32.dll"}


def run(args, **kwargs):
    return subprocess.check_output([str(a) for a in args], text=True, errors="replace", **kwargs).strip()


def git(repo, *args):
    # Trust this explicit caller-selected read-only input, without changing Git configuration.
    return ["git", "-c", "safe.directory=" + str(repo), "-C", str(repo), *args]


def export(repo, revision, paths, destination):
    data = subprocess.check_output(git(repo, "archive", "--format=zip", revision, *paths))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            p = Path(entry.filename)
            require(not p.is_absolute() and ".." not in p.parts and "\\" not in entry.filename,
                    "Unsafe archive member")
            require((entry.external_attr >> 16) & 0o170000 != 0o120000, "Git symlink input refused")
        archive.extractall(destination)


def toolchain_identity(toolchain):
    compiler = toolchain / "bin/g++.exe"
    version = run([compiler, "-dumpversion"])
    target = run([compiler, "-dumpmachine"])
    verbose = subprocess.run([str(compiler), "-v"], capture_output=True, text=True, check=True).stderr
    require(version == "8.1.0" and target == "i686-w64-mingw32"
            and "Thread model: win32" in verbose and "--with-dwarf2" in verbose,
            "Requires GCC 8.1.0 i686 Win32/DWARF toolchain")
    inventory = {n: digest(p) for n, p in sorted(files(toolchain).items())}
    return {"version": version, "target": target, "threads": "win32", "exceptions": "dwarf2",
            "gxx_sha256": digest(compiler), "tree_sha256": hashlib.sha256(canonical(inventory)).hexdigest()}


def package_build(build_dir, destination):
    """Package only a completed, hash-verified build; never an arbitrary sibling executable."""
    build_dir = no_links(build_dir)
    record = json.loads((build_dir / "build.json").read_text(encoding="utf-8"))
    require(record["complete"] is True, "Build is incomplete")
    payload = build_dir / "payload"
    actual = {n: digest(p) for n, p in sorted(files(payload).items())}
    require(actual == record["payload_hashes"], "Build payload changed since compilation")
    return make_package(payload, record["identity"], no_links(destination))


def asset_inventory(assets):
    result = {}
    for name in ASSETS:
        if name == "sounds" and not (assets / name).exists():
            continue  # Normal McOsu releases keep skin sounds in materials/.
        require((assets / name).is_dir(), "Asset input needs " + name + "/")
        result.update({name + "/" + n: digest(p) for n, p in sorted(files(assets / name).items())})
    return result


def build(source, engine, toolchain, assets, out, jobs):
    require(os.name == "nt", "This builder targets Windows")
    source, engine, toolchain, assets, out = [no_links(p) for p in (source, engine, toolchain, assets, out)]
    require(not out.exists(), "Use a fresh output directory (existing evidence is never deleted)")
    for input_path in (source, engine, toolchain, assets):
        require(not input_path.is_relative_to(out), "Output contains an input")
    require(not out.is_relative_to(engine) and not out.is_relative_to(toolchain)
            and not out.is_relative_to(assets), "Output overlaps a dependency input")
    if out.is_relative_to(source):
        relative_output = out.relative_to(source).as_posix() + "/"
        ignored = subprocess.run(git(source, "check-ignore", "-q", "--", relative_output), check=False)
        require(ignored.returncode == 0,
                "Build output inside the source checkout must be Git-ignored; use tools/runtime/out/ or an external path")
    require(not run(git(source, "status", "--porcelain", "--untracked-files=all")),
            "Source must be clean; commit changes before building")
    head = run(git(source, "rev-parse", "HEAD"))
    require(run(git(engine, "rev-parse", ENGINE_PIN + "^{commit}")) == ENGINE_PIN, "Engine pin unavailable")
    tc = toolchain_identity(toolchain)
    baseline = asset_inventory(assets)
    out.mkdir(parents=True)
    started = time.monotonic()
    export(engine, ENGINE_PIN, ["McEngine/src", "McEngine/libraries", "LICENSE"], out / "engine")
    export(source, head, ["src", "build", "LICENSE"], out / "game")
    engine_root = out / "engine/McEngine"
    src = engine_root / "src"
    # Bind the game only inside our owned snapshot; no junctions or sibling source edits.
    require(not (src / "App/Osu").exists(), "Pinned engine unexpectedly includes Osu")
    shutil.copytree(out / "game/src/App/Osu", src / "App/Osu")
    entry = src / "Engine/Engine.cpp"
    text = entry.read_text(encoding="utf-8")
    substitutions = [("//#include \"Osu.h\"", "#include \"Osu.h\""),
                     ("//m_app = new Osu();", "m_app = new Osu();"),
                     ("\t\tm_app = new FrameworkTest();", "\t\t//m_app = new FrameworkTest();")]
    for old, new in substitutions:
        require(text.count(old) == 1, "Pinned engine app binding changed: " + old)
        text = text.replace(old, new)
    entry.write_text(text, encoding="utf-8")
    includes = [src] + sorted(p for p in src.rglob("*") if p.is_dir())
    libraries = sorted((engine_root / "libraries").iterdir())
    includes += [p / "include" for p in libraries if (p / "include").is_dir()]
    sources = sorted(p for p in src.rglob("*") if p.suffix in (".c", ".cpp"))
    objects = out / "objects"
    objects.mkdir()
    environment = dict(os.environ, PATH=str(toolchain / "bin") + os.pathsep + os.environ["PATH"])
    # GCC environment overrides must not inject headers/libraries into the declared build.
    for key in ("CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "LIBRARY_PATH", "GCC_EXEC_PREFIX", "COMPILER_PATH"):
        environment.pop(key, None)

    def compile_one(pair):
        index, path = pair
        obj = objects / (str(index) + ".o")
        compiler = toolchain / ("bin/g++.exe" if path.suffix == ".cpp" else "bin/gcc.exe")
        args = [str(compiler)] + (["-std=c++11"] if path.suffix == ".cpp" else []) + FLAGS
        if path == src / "App/Osu/Osu.cpp":
            args.append("-DMCOSU_CAPTURE_SOURCE=" + head)
        args += ["-I" + p.as_posix() for p in includes] + ["-o", obj.as_posix(), path.as_posix()]
        # Response files also work with spaces in every caller-selected path.
        response = objects / (str(index) + ".args")
        response.write_text("\n".join('"' + a.replace("\\", "/") + '"' for a in args[1:]), encoding="utf-8")
        result = subprocess.run([str(compiler), "@" + response.as_posix()], env=environment,
                                capture_output=True, text=True, errors="replace")
        (objects / (str(index) + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        require(result.returncode == 0, "Compile failed: " + str(path) + "; see " + str(objects / (str(index) + ".log")))
        return obj

    print(f"Building {len(sources)} translation units from {head}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        output = []
        for index, obj in enumerate(pool.map(compile_one, enumerate(sources)), 1):
            output.append(obj)
            if index % 25 == 0:
                print(f"Compiled {index}/{len(sources)}", flush=True)
    payload = out / "payload"
    payload.mkdir()
    args = ["-o", (payload / "McOsu.exe").as_posix()] + [p.as_posix() for p in output]
    args += ["-L" + (p / "lib/windows").as_posix() for p in libraries if (p / "lib/windows").is_dir()]
    args += ["-l" + n for n in LIBRARIES]
    response = out / "link.args"
    response.write_text("\n".join('"' + a + '"' for a in args), encoding="utf-8")
    result = subprocess.run([str(toolchain / "bin/g++.exe"), "@" + response.as_posix()], env=environment,
                            capture_output=True, text=True, errors="replace")
    (out / "link.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    require(result.returncode == 0, "Link failed; see link.log")
    for name in ASSETS:
        if (assets / name).is_dir():
            shutil.copytree(assets / name, payload / name)
        # Revision-specific shaders/models override the supplied release asset baseline.
        overlay = out / "game/build" / name
        if overlay.is_dir():
            shutil.copytree(overlay, payload / name, dirs_exist_ok=True)
    # Engine DLLs come from the exact archived pin, compiler DLLs from the verified toolchain.
    export(engine, ENGINE_PIN, ["McEngine/build/" + n for n in DLLS[:3]], out / "engine-dlls")
    for name in DLLS:
        origin = (out / "engine-dlls/McEngine/build" / name if name in DLLS[:3] else toolchain / "bin" / name)
        shutil.copyfile(origin, payload / name)
    imports = {}
    for name in ("McOsu.exe", *DLLS):
        info = run([toolchain / "bin/objdump.exe", "-p", payload / name], env=environment)
        require("file format pei-i386" in info, "Non-i686 PE image: " + name)
        dependencies = re.findall(r"DLL Name:\s*(\S+)", info)
        require(dependencies, "Cannot read PE imports: " + name)
        missing = {n.lower() for n in dependencies} - SYSTEM_DLLS - set(DLLS)
        require(not missing, "Unpackaged PE imports: " + str(missing))
        imports[name] = dependencies
    require(run(git(source, "rev-parse", "HEAD")) == head
            and not run(git(source, "status", "--porcelain", "--untracked-files=all")),
            "Source changed during build")
    require(toolchain_identity(toolchain) == tc, "Toolchain changed during build")
    require(asset_inventory(assets) == baseline, "Asset baseline changed during build")
    identity = {"source": head, "dirty": False, "engine": ENGINE_PIN, "toolchain": tc,
                "compiler_flags": ["-std=c++11", *FLAGS], "libraries": list(LIBRARIES),
                "capture_source_define": "MCOSU_CAPTURE_SOURCE=" + head,
                "engine_binding": "Osu include/constructor; disable FrameworkTest constructor",
                "asset_baseline_sha256": hashlib.sha256(canonical(baseline)).hexdigest()}
    record = {"complete": True, "identity": identity, "translation_units": len(sources),
              "elapsed_seconds": round(time.monotonic() - started, 2), "pe_imports": imports,
              "payload_hashes": {n: digest(p) for n, p in sorted(files(payload).items())}}
    write_json(out / "build.json", record)
    print(json.dumps({"build": str(out), "source": head, "units": len(sources),
                      "elapsed_seconds": record["elapsed_seconds"]}), flush=True)
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    b = sub.add_parser("build")
    for name in ("source", "engine", "toolchain", "assets", "out"):
        b.add_argument("--" + name, required=True, type=Path)
    b.add_argument("--jobs", type=int, choices=range(1, 33), default=4)
    b = sub.add_parser("package")
    b.add_argument("--build", required=True, type=Path)
    b.add_argument("--out", required=True, type=Path)
    args = vars(p.parse_args())
    try:
        if args.pop("action") == "build":
            build(**args)
        else:
            m = package_build(args["build"], args["out"])
            print(json.dumps({"package": str(args["out"]), "id": m["id"], "files": len(m["files"])}))
    except (Refusal, OSError, ValueError, subprocess.CalledProcessError) as error:
        print("BUILD REFUSED: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

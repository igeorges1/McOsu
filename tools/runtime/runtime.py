"""Managed flat Windows runtimes. Standard library only; no game/source changes."""
import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


ENGINE_PIN = "f2f5721409c17ce4decc20eaf2a1827ce9aafd87"
ASSETS = ("materials", "fonts", "sounds", "shaders", "models")
DLLS = ("bass.dll", "bass_fx.dll", "glew32.dll", "libgcc_s_dw2-1.dll",
        "libstdc++-6.dll", "libwinpthread-1.dll", "libatomic-1.dll")
PERSISTENT = ("cfg", "scores.db", "scoresvr.db", "collections.db", "stars.cache",
              "screenshots", "version.txt")
CONTROL = ".mcosu-runtime"
KIND = "mcosu-flat-runtime-v1"


class Refusal(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def identity(manifest):
    return hashlib.sha256(canonical({k: v for k, v in manifest.items() if k != "id"})).hexdigest()


def hex_string(value, length):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{" + str(length) + "}", value)


def read_json(path):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, "Duplicate JSON key: " + k)
            result[k] = v
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def write_json(path, data):
    # Metadata switches are atomic. Payload writes use the same-volume staging area.
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, sort_keys=True, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def no_links(path):
    """Reject symlinks/junctions, including ancestors, before reading or writing."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        require(not part.is_symlink() and not part.is_junction(), "Link/junction refused: " + str(part))
    return path


def files(root):
    no_links(root)
    require(root.is_dir(), "Missing directory: " + str(root))
    result = {}
    for base, dirs, names in os.walk(root):
        for name in dirs + names:
            no_links(Path(base) / name)
        for name in names:
            p = Path(base) / name
            require(p.is_file(), "Not a regular file: " + str(p))
            result[p.relative_to(root).as_posix()] = p
    return result


def allowed(name):
    # Windows aliases, ADS, traversal, case collisions and reserved names are rejected.
    parts = name.split("/")
    if any(not re.fullmatch(r"[A-Za-z0-9_ .+()@!%&=,;\[\]{}~-]+", p)
           or p in (".", "..") or p.endswith((".", " "))
           or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p)
           for p in parts):
        return False
    return name == "McOsu.exe" or name in DLLS or (len(parts) > 1 and parts[0] in ASSETS)


def validate(package):
    package = no_links(package)
    inventory = files(package)
    require("manifest.json" in inventory, "Missing package manifest")
    m = read_json(package / "manifest.json")
    require(isinstance(m, dict) and set(m) == {"format", "id", "build", "files"}
            and type(m["format"]) is int and m["format"] == 1,
            "Unknown package format")
    require(m["id"] == identity(m), "Package identity mismatch")
    b = m["build"]
    require(isinstance(b, dict) and b.get("engine") == ENGINE_PIN
            and hex_string(b.get("source"), 40)
            and b.get("dirty") is False and isinstance(b.get("toolchain"), dict),
            "Missing/invalid source, clean status, engine pin or toolchain identity")
    tc = b["toolchain"]
    require(tc.get("version") == "8.1.0" and tc.get("target") == "i686-w64-mingw32"
            and tc.get("threads") == "win32" and tc.get("exceptions") == "dwarf2"
            and hex_string(tc.get("gxx_sha256"), 64) and hex_string(tc.get("tree_sha256"), 64),
            "Invalid toolchain fingerprint")
    require(isinstance(m["files"], dict) and "McOsu.exe" in m["files"], "Missing executable")
    seen = set()
    for name, record in m["files"].items():
        require(allowed(name), "Outside immutable allowlist: " + name)
        require(name.lower() not in seen, "Case-colliding package path: " + name)
        seen.add(name.lower())
        require(isinstance(record, dict) and set(record) == {"sha256", "size"}
                and type(record["size"]) is int and record["size"] >= 0
                and hex_string(record["sha256"], 64), "Invalid file record")
        p = package / "payload" / name
        require("payload/" + name in inventory, "Missing payload: " + name)
        require(p.stat().st_size == record["size"] and digest(p) == record["sha256"],
                "Payload hash/size mismatch: " + name)
    require(set(inventory) == {"manifest.json"} | {"payload/" + n for n in m["files"]},
            "Unmanifested package files")
    return m


def make_package(payload, build, destination):
    """Internal packager shared with build.py and test-only fixtures."""
    require(not destination.exists(), "Package destination already exists")
    inventory = files(payload)
    require(all(allowed(n) for n in inventory), "Payload outside immutable allowlist")
    m = {"format": 1, "build": build, "files": {
        n: {"size": p.stat().st_size, "sha256": digest(p)} for n, p in sorted(inventory.items())}}
    m["id"] = identity(m)
    destination.mkdir(parents=True)
    shutil.copytree(payload, destination / "payload")
    write_json(destination / "manifest.json", m)
    validate(destination)
    return m


def active_processes(root):
    """Enumerate executable image paths, including games started outside this CLI."""
    require(os.name == "nt", "Runtime operations require Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    pids = (wintypes.DWORD * 65536)()
    used = wintypes.DWORD()
    require(psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(used)), "Cannot enumerate processes")
    found = []
    for pid in pids[:used.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            continue  # System/protected processes; image write checks below cover target images.
        try:
            buf = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buf))
            if kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(length)):
                image = Path(buf.value).resolve()
                if image.is_relative_to(root):
                    found.append({"pid": pid, "image": str(image)})
        finally:
            kernel.CloseHandle(handle)
    return found


def idle(root):
    require(not active_processes(root), "Runtime has an active executable; close it yourself")
    # Opening images for write is refused by Windows even when a process path is inaccessible.
    for name in files(root):
        if name.lower().endswith((".exe", ".dll")) and not name.startswith(CONTROL + "/"):
            try:
                with (root / name).open("r+b"):
                    pass
            except OSError as error:
                raise Refusal("Runtime image is busy/read-only: " + name) from error


def managed(root):
    root = no_links(root)
    require((root / CONTROL / "state.json").is_file(), "Unmanaged destination; initialize an empty directory first")
    files(root / CONTROL)
    state = read_json(root / CONTROL / "state.json")
    require(set(state) == {"kind", "current", "previous"} and state["kind"] == KIND,
            "Invalid managed runtime marker")
    for key in ("current", "previous"):
        require(state[key] is None or re.fullmatch(r"[0-9a-f]{64}", state[key]), "Invalid bundle pointer")
    return root, state


@contextmanager
def locked(root):
    import msvcrt
    lock = no_links(root / CONTROL / "lock")
    with lock.open("r+b") as f:
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise Refusal("Runtime is locked by another operation/launch") from error
        try:
            idle(root)
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def bundle(root, package_id):
    p = root / CONTROL / "bundles" / package_id
    require(validate(p)["id"] == package_id, "Stored bundle identity mismatch")
    return p


def current_manifest(root, state):
    return validate(bundle(root, state["current"])) if state["current"] else {"files": {}}


def verify_live(root, manifest):
    for name, record in manifest["files"].items():
        p = no_links(root / name)
        require(p.is_file() and digest(p) == record["sha256"], "Managed file changed/missing: " + name)


def check_plan(root, before, after):
    for name in set(before["files"]) | set(after["files"]):
        p = no_links(root / name)
        require(not p.exists() or p.is_file(), "File/directory conflict: " + name)
        require(name in before["files"] or not p.exists(), "Unowned file conflict: " + name)
        for parent in p.parents:
            if parent == root:
                break
            require(not parent.exists() or parent.is_dir(), "Parent file conflict: " + str(parent))


def install_files(root, target, remove):
    # Only manifest leaves are replaced/deleted. Unknown neighbours and directories survive.
    manifest = validate(target) if target else {"files": {}}
    for name in sorted(set(remove) - set(manifest["files"])):
        p = no_links(root / name)
        if p.exists():
            require(p.is_file(), "Recovery file conflict: " + name)
            p.unlink()
    for name in sorted(manifest["files"]):
        p = no_links(root / name)
        p.parent.mkdir(parents=True, exist_ok=True)
        temporary = root / CONTROL / "replace.tmp"
        shutil.copyfile(target / "payload" / name, temporary)
        os.replace(temporary, p)


def collect(root, state):
    keep = {state["current"], state["previous"]}
    for p in (root / CONTROL / "bundles").iterdir():
        require(p.is_dir() and re.fullmatch(r"[0-9a-f]{64}", p.name), "Unexpected bundle entry")
        if p.name not in keep:
            shutil.rmtree(p)


def recover_locked(root):
    journal = root / CONTROL / "transaction.json"
    require(journal.is_file(), "No interrupted transaction")
    tx = read_json(journal)
    require(set(tx) == {"before", "after"}, "Invalid transaction journal")
    before = tx["before"]
    require(before.get("kind") == KIND and set(before) == {"kind", "current", "previous"}, "Invalid recovery state")
    for value in (before["current"], before["previous"], tx["after"]):
        require(value is None or re.fullmatch(r"[0-9a-f]{64}", value), "Invalid recovery pointer")
        if value:
            bundle(root, value)
    after = validate(bundle(root, tx["after"]))
    target = bundle(root, before["current"]) if before["current"] else None
    install_files(root, target, after["files"])
    write_json(root / CONTROL / "state.json", before)
    journal.unlink()
    collect(root, before)
    return before


def transact(root, state, package):
    control = root / CONTROL
    after = validate(package)
    before = current_manifest(root, state)
    verify_live(root, before)
    check_plan(root, before, after)
    if after["id"] == state["current"]:
        collect(root, state)  # Also finish any interrupted post-commit garbage collection.
        return state
    destination = control / "bundles" / after["id"]
    # Stage fully before publishing the journal. Leftover staging is safe to discard.
    stage = control / "stage"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(package, stage)
    require(validate(stage) == after, "Package changed during staging")
    if destination.exists():
        require(validate(destination) == after, "Stored bundle differs")
        shutil.rmtree(stage)
    else:
        os.replace(stage, destination)
    write_json(control / "transaction.json", {"before": state, "after": after["id"]})
    try:
        install_files(root, destination, before["files"])
        verify_live(root, after)
        new = {"kind": KIND, "current": after["id"], "previous": state["current"]}
        write_json(control / "state.json", new)
    except Exception:
        recover_locked(root)
        raise
    # Commit point: recovery before this removal always restores the pre-update bundle.
    (control / "transaction.json").unlink()
    collect(root, new)
    return new


def initialize(root, import_from=None, dry_run=False):
    root = no_links(root)
    require(not root.exists() or (root.is_dir() and not any(root.iterdir())), "Initialization requires an empty destination")
    imports = {}
    if import_from:
        source = no_links(import_from)
        require(not root.is_relative_to(source) and not source.is_relative_to(root), "Import/runtime paths overlap")
        require(source.is_dir(), "Missing import source")
        for name in PERSISTENT:
            p = no_links(source / name)
            if p.is_dir():
                imports.update({name + "/" + n: f for n, f in files(p).items()})
            elif p.exists():
                require(p.is_file(), "Invalid import file")
                imports[name] = p
    plan = {"runtime": str(root), "copy_state_files": sorted(imports), "dry_run": dry_run}
    if dry_run:
        return plan
    root.mkdir(parents=True, exist_ok=True)
    for name, source in imports.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for name in ("cfg", "screenshots", CONTROL + "/bundles"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / CONTROL / "lock").write_bytes(b"0")
    write_json(root / CONTROL / "state.json", {"kind": KIND, "current": None, "previous": None})
    return plan


def operate(action, runtime, package=None, dry_run=False, acknowledge_state_risk=False, arguments=()):
    # Invalid packages and unmanaged/running destinations fail before any writes.
    incoming = validate(Path(package)) if package else None
    root, initial = managed(runtime)
    if package:
        package_path = no_links(package)
        require(not package_path.is_relative_to(root) and not root.is_relative_to(package_path),
                "Update package and runtime must not overlap")
    idle(root)
    with locked(root):
        root, state = managed(root)
        pending = (root / CONTROL / "transaction.json").exists()
        if action == "inspect":
            if not pending:
                verify_live(root, current_manifest(root, state))
            return {**state, "runtime": str(root), "recovery_required": pending}
        if action == "recover":
            require(pending, "No interrupted transaction")
            return {"recovery_required": True} if dry_run else recover_locked(root)
        require(not pending, "Interrupted transaction; run recover before update/rollback/launch")
        if action == "launch":
            require(state["current"], "No package deployed")
            manifest = current_manifest(root, state)
            verify_live(root, manifest)
            command = [str(root / "McOsu.exe"), *arguments]
            if dry_run:
                return {"command": command, "cwd": str(root)}
            # Keep the runtime lock for the entire child lifetime. KeyboardInterrupt doesn't kill it.
            with subprocess.Popen(command, cwd=root, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP) as child:
                while True:
                    try:
                        return {"exit_code": child.wait()}
                    except KeyboardInterrupt:
                        continue
        if action == "rollback":
            require(state["previous"], "No previous bundle retained")
            require(acknowledge_state_risk or dry_run,
                    "Rollback keeps current preferences/scores/cache. Compatibility is unverified; "
                    "back up state and pass --acknowledge-state-risk")
            package = bundle(root, state["previous"])
            incoming = validate(package)
        require(incoming is not None, "Update requires --package")
        before = current_manifest(root, state)
        verify_live(root, before)
        check_plan(root, before, incoming)
        plan = {"from": state["current"], "to": incoming["id"], "files": len(incoming["files"]),
                "persistent_state": "unchanged; cross-build compatibility unverified", "dry_run": dry_run}
        if not dry_run:
            transact(root, state, Path(package))
        return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("validate", help="Verify a package and print its manifest")
    p.add_argument("--package", required=True, type=Path)
    p = sub.add_parser("init", help="Initialize an empty runtime, optionally copying state")
    p.add_argument("--runtime", required=True, type=Path)
    p.add_argument("--import-from", type=Path)
    p.add_argument("--dry-run", action="store_true")
    for action in ("inspect", "update", "rollback", "launch", "recover"):
        p = sub.add_parser(action)
        p.add_argument("--runtime", required=True, type=Path)
        p.add_argument("--dry-run", action="store_true")
        if action == "update":
            p.add_argument("--package", required=True, type=Path)
        if action == "rollback":
            p.add_argument("--acknowledge-state-risk", action="store_true")
        if action == "launch":
            p.add_argument("arguments", nargs=argparse.REMAINDER, help="Optional game arguments after --")
    args = vars(parser.parse_args())
    action = args.pop("action")
    try:
        if action == "validate":
            result = validate(args["package"])
        elif action == "init":
            result = initialize(args.pop("runtime"), **args)
        else:
            if args.get("arguments", [])[:1] == ["--"]:
                args["arguments"] = args["arguments"][1:]
            result = operate(action, **args)
        print(json.dumps(result, indent=2))
        return result.get("exit_code", 0)
    except (Refusal, OSError, ValueError, TypeError, KeyError) as error:
        print("REFUSED: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

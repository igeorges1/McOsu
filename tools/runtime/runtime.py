"""Managed flat Windows runtimes. Standard library only; no game/source changes."""
import argparse
from contextlib import contextmanager, suppress
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid
import zipfile


ENGINE_PIN = "f2f5721409c17ce4decc20eaf2a1827ce9aafd87"
ASSETS = ("materials", "fonts", "sounds", "shaders", "models")
DLLS = ("bass.dll", "bass_fx.dll", "glew32.dll", "libgcc_s_dw2-1.dll",
        "libstdc++-6.dll", "libwinpthread-1.dll", "libatomic-1.dll")
PERSISTENT = ("cfg", "scores.db", "scoresvr.db", "collections.db", "stars.cache",
              "screenshots", "version.txt")
CONTROL = ".mcosu-runtime"
LEGACY_KIND = "mcosu-flat-runtime-v1"
KIND = "mcosu-flat-runtime-v2"
TOOLING_VERSION = "queued-preview-v1"
QUEUE_FORMAT = 1
BACKUP_NAME = "last-saved-state.zip"
EXIT_HOLD = "exit-hold.json"
BACKUP_LIMIT = 512 * 1024 * 1024
BACKUP_PATHS = tuple(p for p in PERSISTENT if p != "screenshots")


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
    no_links(path)
    temporary = no_links(path.with_name(path.name + ".tmp"))
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


def files(root, skip_control=False):
    no_links(root)
    require(root.is_dir(), "Missing directory: " + str(root))
    result = {}
    for base, dirs, names in os.walk(root):
        if skip_control and Path(base) == root and CONTROL in dirs:
            dirs.remove(CONTROL)
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
           or p in (".", "..") or p.endswith((".", " ")) or re.search(r"~[0-9]", p)
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
    for path in files(root, skip_control=True).values():
        if path.suffix.lower() in (".exe", ".dll"):
            try:
                with no_links(path).open("r+b"):
                    pass
            except OSError as error:
                raise Refusal("Runtime image is busy/read-only: " + path.name) from error


def managed(root, scan=False):
    root = no_links(root)
    marker = no_links(root / CONTROL / "state.json")
    require(marker.is_file(), "Unmanaged destination; initialize an empty directory first")
    if scan:
        files(root / CONTROL)
    state = read_json(marker)
    require(set(state) == {"kind", "current", "previous"} and state["kind"] in (LEGACY_KIND, KIND),
            "Invalid managed runtime marker")
    for key in ("current", "previous"):
        require(state[key] is None or re.fullmatch(r"[0-9a-f]{64}", state[key]), "Invalid bundle pointer")
    return root, state


@contextmanager
def runtime_lock(root, byte, message):
    import msvcrt
    lock = no_links(root / CONTROL / "lock")
    with lock.open("r+b") as f:
        f.seek(byte)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise Refusal(message) from error
        try:
            yield
        finally:
            f.seek(byte)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def locked(root):
    with runtime_lock(root, 0, "Runtime is locked by another operation/launch"):
        idle(root)
        yield


def queue_lock(root):
    # Windows permits locking past EOF: legacy runtimes already have this file.
    return runtime_lock(root, 1, "Queue is busy; retry this command when the current operation finishes")


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
        # A blocked replacement can leave the old bytes intact. Recovery must
        # not attempt the same blocked write when those bytes are already right.
        if p.is_file() and digest(p) == manifest["files"][name]["sha256"]:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        temporary = root / CONTROL / "replace.tmp"
        shutil.copyfile(target / "payload" / name, temporary)
        os.replace(temporary, p)


def discard_private_tree(path):
    # Earlier staging copies may carry Windows read-only attributes. Clear
    # those only on private files already selected for deletion, never live
    # files or the source package. Other deletion failures still propagate.
    def retry_readonly(operation, name, error):
        if operation != os.unlink or not isinstance(error, PermissionError):
            raise error
        leaf = no_links(Path(name))
        if not leaf.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY:
            raise error
        leaf.chmod(stat.S_IREAD | stat.S_IWRITE)
        operation(leaf)

    shutil.rmtree(path, onexc=retry_readonly)


def collect(root, state):
    keep = {state["current"], state["previous"]}
    q = read_queue(root)
    keep.add(q["known_good"])
    if q["pending"]:
        keep.add(q["pending"]["id"])
    if has_transaction(root):
        return  # The journal can still need any pre-transaction bundle.
    active = None
    for p in no_links(root / CONTROL / "bundles").iterdir():
        if p.name in keep or not hex_string(p.name, 64):
            continue
        try:
            if active is None:
                active = [Path(item["image"]) for item in active_processes(root)]
            if any(image.is_relative_to(p.resolve()) for image in active):
                continue
            manifest = validate(bundle(root, p.name))  # Never delete unverifiable contents.
            directories = {Path("payload") / parent for name in manifest["files"] for parent in Path(name).parents}
            require(all(Path(base, name).relative_to(p) in directories
                        for base, dirs, _ in os.walk(p) for name in dirs), "Unknown directory in bundle")
            discard_private_tree(no_links(p))
        except (Refusal, OSError, ValueError, TypeError, KeyError) as error:
            print(f"Retained private entry {p.name}: {error}", file=sys.stderr)


def recover_locked(root):
    journal = root / CONTROL / "transaction.json"
    require(journal.is_file(), "No interrupted transaction")
    tx = read_json(journal)
    require(set(tx) in ({"before", "after"}, {"before", "after", "files"}), "Invalid transaction journal")
    before = tx["before"]
    require(before.get("kind") in (LEGACY_KIND, KIND) and set(before) == {"kind", "current", "previous"}, "Invalid recovery state")
    for value in (before["current"], before["previous"]):
        require(value is None or re.fullmatch(r"[0-9a-f]{64}", value), "Invalid recovery pointer")
        if value:
            bundle(root, value)
    require(hex_string(tx["after"], 64), "Invalid recovery candidate")
    names = tx.get("files")
    if names is None:  # Older journals lack a removal inventory.
        names = list(validate(bundle(root, tx["after"]))["files"])
    require(isinstance(names, list) and all(isinstance(n, str) and allowed(n) for n in names),
            "Invalid recovery inventory")
    target = bundle(root, before["current"]) if before["current"] else None
    install_files(root, target, names)
    (root / CONTROL / "replace.tmp").unlink(missing_ok=True)
    write_json(root / CONTROL / "state.json", before)
    journal.unlink()
    collect(root, before)
    return before


def store_bundle(root, package, after):
    control = root / CONTROL
    destination = no_links(control / "bundles" / after["id"])
    # Stage fully before publishing the journal. Leftover staging is safe to discard.
    stage = no_links(control / "stage")
    if stage.exists():
        # The fixed stage is private; refuse unknown contents even after a crash.
        require(all(n in ("manifest.json", "manifest.json.tmp") or (n.startswith("payload/") and allowed(n[8:]))
                    for n in files(stage)), "Unknown file in private stage; inspect it before retrying")
        require(all((p := Path(base, name).relative_to(stage)).as_posix() == "payload"
                    or (p.parts[0] == "payload" and allowed("/".join(p.parts[1:]) + "/leaf"))
                    for base, dirs, _ in os.walk(stage) for name in dirs), "Unknown directory in private stage")
        discard_private_tree(stage)
    if destination.exists():
        require(validate(destination) == after, "Stored bundle differs")
    else:
        # Copy only validated leaves, without inheriting read-only flags.
        stage.mkdir()
        for name in after["files"]:
            p = stage / "payload" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(no_links(Path(package) / "payload" / name), p)
        write_json(stage / "manifest.json", after)
        require(validate(stage) == after, "Package changed during staging")
        os.replace(stage, destination)
    return destination


def transact(root, state, package):
    control = root / CONTROL
    after = validate(package)
    before = current_manifest(root, state)
    verify_live(root, before)
    check_plan(root, before, after)
    if after["id"] == state["current"]:
        collect(root, state)  # Also finish any interrupted post-commit garbage collection.
        return state
    destination = store_bundle(root, package, after)
    write_json(control / "transaction.json", {"before": state, "after": after["id"], "files": sorted(after["files"])})
    try:
        install_files(root, destination, before["files"])
        verify_live(root, after)
        new = {"kind": state["kind"], "current": after["id"], "previous": state["current"]}
        write_json(control / "state.json", new)
    except Exception as error:
        try:
            recover_locked(root)
        except Exception as recovery_error:
            raise Refusal(f"Update failed: {error}; automatic recovery did not finish: "
                          f"{recovery_error}. Use inspect to check whether recover is needed.") from recovery_error
        raise Refusal(f"Update failed; pre-update bundle restored: {error}") from error
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
    # The source scan can take time. Recheck, then claim the control directory
    # exclusively before any copy; a competing initializer must lose the claim.
    require(not any(root.iterdir()), "Initialization requires an empty destination")
    control = root / CONTROL
    try:
        control.mkdir()
    except FileExistsError as error:
        raise Refusal("Initialization already started in this destination") from error
    try:
        for name, source in imports.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        for name in ("cfg", "screenshots", CONTROL + "/bundles"):
            (root / name).mkdir(parents=True, exist_ok=True)
        (control / "lock").write_bytes(b"0")
        write_json(control / "state.json", {"kind": KIND, "current": None, "previous": None})
    except Exception:
        # Relinquish an empty claim; never delete partly copied user state.
        with suppress(OSError):
            control.rmdir()
        raise
    return plan


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def has_transaction(root):
    return no_links(root / CONTROL / "transaction.json").exists()


def read_queue(root):
    p = no_links(root / CONTROL / "queue.json")
    if not p.exists():
        return {"format": QUEUE_FORMAT, "pending": None, "known_good": None, "last": None}
    q = read_json(p)
    require(set(q) == {"format", "pending", "known_good", "last"} and q["format"] == QUEUE_FORMAT,
            "Invalid queue format")
    require(q["known_good"] is None or hex_string(q["known_good"], 64), "Invalid known-good ID")
    p = q["pending"]
    require(p is None or (isinstance(p, dict) and hex_string(p.get("id"), 64)
                          and hex_string(p.get("source"), 40) and hex_string(p.get("exe_sha256"), 64)
                          and hex_string(p.get("stage_token"), 32)
                          and p.get("phase") in ("queued", "applying", "held")), "Invalid pending release")
    return q


def write_queue(root, q):
    write_json(root / CONTROL / "queue.json", q)


def release_identity(manifest):
    return {"id": manifest["id"], "source": manifest["build"]["source"],
            "exe_sha256": manifest["files"]["McOsu.exe"]["sha256"]}


def outcome(q, result, reason, detail=None):
    p = q["pending"]
    q["last"] = {"result": result, "reason": reason, "time_utc": stamp(),
                 "candidate": p.copy() if p else None, "detail": detail}


def reconcile(root, state, q, save):
    p = q["pending"]
    changed = False
    if p and p["phase"] == "applying":
        if not has_transaction(root) and state["current"] == p["id"]:
            outcome(q, "promoted", "reconciled committed attempt")
            q["pending"] = None
        else:
            p["phase"] = "held"
            outcome(q, "interrupted", "promotion", "Inspect recovery state; then retry or cancel explicitly")
        changed = True
    receipt = no_links(root / CONTROL / EXIT_HOLD)
    held = read_json(receipt) if receipt.exists() else None
    if held is not None:
        p = q["pending"]
        if p and p["phase"] == "queued" and p["stage_token"] == held["stage_token"]:
            p["phase"] = "held"
            outcome(q, "held", "nonzero game exit", str(held["exit_code"]))
            q["last"]["time_utc"] = held["time_utc"]
            changed = True
    if save:
        if changed:
            write_queue(root, q)
        if held is not None:
            receipt.unlink()
    return q


def saved_backup(root, state, candidate):
    inventory = {}
    for name in BACKUP_PATHS:
        p = no_links(root / name)
        if name == "cfg" and p.is_dir():
            inventory.update({"cfg/" + n: f for n, f in files(p).items()})
        elif p.exists():
            require(p.is_file(), "Invalid saved-state file: " + name)
            inventory[name] = p
    require(sum(p.stat().st_size for p in inventory.values()) <= BACKUP_LIMIT,
            "Saved state exceeds the backup size limit; no promotion performed")
    path = no_links(root / CONTROL / BACKUP_NAME)
    temporary = no_links(path.with_suffix(".tmp"))
    result = {"created_utc": stamp(), "installed_before": state["current"], "candidate": candidate,
              "files": {n: digest(p) for n, p in sorted(inventory.items())}}
    with temporary.open("wb") as f:
        with zipfile.ZipFile(f, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for n, p in sorted(inventory.items()):
                z.write(p, "state/" + n)
            z.writestr("backup.json", canonical(result))
        f.flush()
        os.fsync(f.fileno())
    with zipfile.ZipFile(temporary) as z:
        for name, sha in result["files"].items():
            with z.open("state/" + name) as f:
                require(hashlib.file_digest(f, "sha256").hexdigest() == sha and digest(inventory[name]) == sha,
                        "Saved state changed while making backup: " + name)
    os.replace(temporary, path)
    return result


def promote(root, state, q, reason):
    """Caller owns install and queue locks; a zero game exit is only a timing edge."""
    p = q["pending"]
    if not p or p["phase"] != "queued":
        return None
    if p["id"] == state["current"]:
        outcome(q, "already-installed", reason)
        q["pending"] = None
        write_queue(root, q)
        return q["last"]
    p["phase"] = "applying"
    outcome(q, "applying", reason)
    write_queue(root, q)
    try:
        package = bundle(root, p["id"])
        after = validate(package)
        require(all(p[k] == v for k, v in release_identity(after).items()), "Queued provenance differs")
        before = current_manifest(root, state)
        verify_live(root, before)
        check_plan(root, before, after)
        idle(root)
        saved_backup(root, state, p["id"])
        idle(root)
        state = transact(root, state, package)
    except (Refusal, OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as error:
        p["phase"] = "held"
        outcome(q, "failed", reason, str(error))
        write_queue(root, q)
        return q["last"]
    outcome(q, "promoted", reason)
    q["pending"] = None
    write_queue(root, q)
    collect(root, state)
    return q["last"]


def status(root, state, q):
    def describe(id):
        if id is None:
            return None
        try:
            return release_identity(validate(bundle(root, id)))
        except (Refusal, OSError, ValueError, TypeError, KeyError) as error:
            return {"id": id, "error": str(error)}

    path = no_links(root / CONTROL / BACKUP_NAME)
    backup = None
    if path.exists():
        try:
            with zipfile.ZipFile(path) as z:
                backup = json.loads(z.read("backup.json"))
            backup = {k: v for k, v in backup.items() if k != "files"} | {"path": str(path)}
        except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
            backup = {"path": str(path), "error": str(error)}
    recovery = has_transaction(root)
    installed = describe(state["current"])
    if installed and not recovery and "error" not in installed:
        try:
            verify_live(root, current_manifest(root, state))
        except (Refusal, OSError) as error:
            installed["error"] = str(error)
    if installed:
        installed["verified_live"] = not recovery and "error" not in installed
    queued = q["pending"]
    if queued:
        queued = queued | {"stored_bundle": describe(queued["id"])}
    return {"tooling": TOOLING_VERSION, "queue_enabled": state["kind"] == KIND,
            "runtime": str(root), "installed": installed, "previous": describe(state["previous"]),
            "known_good": describe(q["known_good"]), "queued": queued, "last": q["last"],
            "outcome_log": str(root / CONTROL / "queue.json"), "backup": backup,
            "recovery_required": recovery, "active_images": active_processes(root),
            "policy": {"promote": ["before-launch", "after-zero-exit"], "failed": "explicit-retry",
                       "backup_count": 1, "backup_max_bytes": BACKUP_LIMIT, "backup_paths": BACKUP_PATHS}}


def queue_action(action, root, package, incoming, replace):
    with queue_lock(root):
        root, state = managed(root)
        q = reconcile(root, state, read_queue(root), save=action != "status")
        if action == "status":
            return status(root, state, q)
        require(state["kind"] == KIND, "Enable the queue with the new controller while idle first")
        require(not has_transaction(root), "Interrupted transaction; recover before changing the queue")
        if action == "stage":
            require(incoming is not None, "Stage requires --package")
            if incoming["id"] == state["current"]:
                return {"result": "already-installed", "id": incoming["id"], "queued": q["pending"]}
            p = q["pending"]
            if p and p["id"] == incoming["id"]:
                # Refill a missing copy without resetting a failure/hold.
                if no_links(root / CONTROL / "bundles" / p["id"]).exists():
                    bundle(root, p["id"])
                else:
                    store_bundle(root, package, incoming)
                return {"result": "already-queued", "queued": p}
            require(not p or replace, "A release is queued; pass --replace or cancel it explicitly")
            store_bundle(root, package, incoming)
            q["pending"] = release_identity(incoming) | {"phase": "queued", "staged_utc": stamp(),
                                                         "origin": str(no_links(package)),
                                                         "stage_token": uuid.uuid4().hex}
            outcome(q, "staged", "explicit replacement" if p else "stage")
        else:
            if not q["pending"]:
                return {"result": "nothing-queued"}
            outcome(q, "cancelled", "cancel")
            q["pending"] = None
        write_queue(root, q)
        collect(root, state)
        return {"result": q["last"]["result"], "queued": q["pending"]}


def game_launch(root, arguments, defer):
    command = [str(root / "McOsu.exe"), *arguments]
    with queue_lock(root):
        _, state = managed(root)
        q = reconcile(root, state, read_queue(root), save=True)
        require(not has_transaction(root), "Interrupted transaction; run recover before launch")
        result = None if defer else promote(root, state, q, "before-launch")
        if result and result["result"] == "failed":
            print(f"Queued promotion held: {result['detail']}", file=sys.stderr)
        require(not has_transaction(root), "Interrupted transaction; run recover before launch")
        _, state = managed(root)
        require(state["current"], "No package deployed")
        verify_live(root, current_manifest(root, state))
        idle(root)
        child = subprocess.Popen(command, cwd=root, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    with child:
        while True:
            try:
                code = child.wait()
                break
            except KeyboardInterrupt:
                continue
    after = None
    if not defer:
        try:
            if code != 0:
                # queue.json is atomic. The install lock keeps launchers from
                # overlapping, so the exit receipt has its own single writer.
                # A concurrent replacement gets a fresh token and is not held.
                pending = read_queue(root)["pending"]
                if pending and pending["phase"] == "queued":
                    write_json(root / CONTROL / EXIT_HOLD, {"stage_token": pending["stage_token"],
                               "exit_code": code, "time_utc": stamp()})
                    after = {"result": "held", "reason": "nonzero game exit", "candidate": pending}
            with queue_lock(root):
                _, state = managed(root)
                q = reconcile(root, state, read_queue(root), save=True)
                if code == 0:
                    after = promote(root, state, q, "after-zero-exit")
        except (Refusal, OSError, ValueError, TypeError, KeyError) as error:
            # Do not replace the game's actual exit code with an updater error.
            after = (after or {"result": "not-promoted"}) | {"detail": str(error)}
            print(f"Post-exit queue: {error}", file=sys.stderr)
    return {"exit_code": code, "before_launch": result, "after_exit": after}


def operate(action, runtime, package=None, dry_run=False, acknowledge_state_risk=False, arguments=(),
            replace=False, to="previous", defer_queue=False):
    # Invalid packages and unmanaged/running destinations fail before any writes.
    incoming = validate(Path(package)) if package else None
    root, _ = managed(runtime)
    if package:
        package_path = no_links(package)
        require(not package_path.is_relative_to(root) and not root.is_relative_to(package_path),
                "Update package and runtime must not overlap")
    if action in ("stage", "status", "cancel"):
        return queue_action(action, root, package, incoming, replace)
    idle(root)
    with locked(root):
        if action == "launch" and not dry_run:
            return game_launch(root, arguments, defer_queue)
        with queue_lock(root):
            return operate_idle(action, root, package, incoming, dry_run, acknowledge_state_risk, arguments, to)


def operate_idle(action, root, package, incoming, dry_run, acknowledge_state_risk, arguments, to):
    root, state = managed(root, scan=True)
    pending = has_transaction(root)
    q = reconcile(root, state, read_queue(root), save=not dry_run and action != "inspect")
    if action == "inspect":
        if not pending:
            verify_live(root, current_manifest(root, state))
        return {**state, "runtime": str(root), "recovery_required": pending}
    if action == "recover":
        require(pending, "No interrupted transaction")
        return {"recovery_required": True} if dry_run else recover_locked(root)
    require(not pending, "Interrupted transaction; run recover before update/rollback/launch")
    if action in ("enable-queue", "disable-queue"):
        kind = KIND if action == "enable-queue" else LEGACY_KIND
        if kind == LEGACY_KIND:
            require(not q["pending"] and not q["known_good"], "Cancel the queue and unpin before downgrade")
            collect(root, state)
        state["kind"] = kind
        write_json(root / CONTROL / "state.json", state)
        return {"queue_enabled": kind == KIND}
    if action in ("retry", "pin", "unpin"):
        require(state["kind"] == KIND, "Enable the queue while idle first")
        if action == "retry":
            require(q["pending"], "No candidate to retry")
            q["pending"]["phase"] = "queued"
            result = promote(root, state, q, "explicit-retry")
            return result | {"exit_code": int(result["result"] == "failed")}
        if action == "pin":
            require(state["current"], "No installed package to pin")
            verify_live(root, current_manifest(root, state))
        q["known_good"] = state["current"] if action == "pin" else None
        write_queue(root, q)
        collect(root, state)
        return {"known_good": q["known_good"]}
    if action == "launch":
        require(state["current"], "No package deployed")
        manifest = current_manifest(root, state)
        verify_live(root, manifest)
        command = [str(root / "McOsu.exe"), *arguments]
        return {"command": command, "cwd": str(root), "queued": q["pending"]}
    if action == "rollback":
        selected = state["previous"] if to == "previous" else q["known_good"]
        require(selected, "No " + to + " bundle retained")
        require(acknowledge_state_risk or dry_run,
                "Rollback keeps current preferences/scores/cache. Compatibility is unverified; "
                "back up state and pass --acknowledge-state-risk")
        package = bundle(root, selected)
        incoming = validate(package)
    require(incoming is not None, "Update requires --package")
    require(not q["pending"] or (action == "update" and incoming["id"] == state["current"]),
            "Cancel the queued release before direct update or rollback")
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
    for action in ("inspect", "update", "rollback", "launch", "recover", "stage", "status", "cancel",
                   "retry", "pin", "unpin", "enable-queue", "disable-queue"):
        p = sub.add_parser(action)
        p.add_argument("--runtime", required=True, type=Path)
        if action in ("inspect", "update", "rollback", "launch", "recover"):
            p.add_argument("--dry-run", action="store_true")
        if action in ("update", "stage"):
            p.add_argument("--package", required=True, type=Path)
        if action == "stage":
            p.add_argument("--replace", action="store_true")
        if action == "rollback":
            p.add_argument("--acknowledge-state-risk", action="store_true")
            p.add_argument("--to", choices=("previous", "known-good"), default="previous")
        if action == "launch":
            p.add_argument("--defer-queue", action="store_true")
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

"""Assemble capture payloads offline and gate the fixed loader on observations."""

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import stat
import sys

from gameplay_budget import MIB
from gameplay_operator_package import (GIT_ID, PACKAGE_LIMIT, ROOT_ROLES, canonical, digest, exact_keys,
                                       fields_from_json, is_sha, member_path, validate_graph, validate_package,
                                       validate_pair)

CLOSURE = "route/runtime-closure.json"
REQUIRED_RUNTIME = {"python/python313.dll", "python/python313.zip", "python/python313._pth"}
ISOLATED_PATHS = ("python313.zip", ".", "../tools", "../route")
OS_DLLS = frozenset({"advapi32.dll", "bcrypt.dll", "kernel32.dll", "ntdll.dll", "ole32.dll", "shell32.dll",
                     "tdh.dll", "ucrtbase.dll", "user32.dll", "winmm.dll", "ws2_32.dll"})
IMPORT = re.compile(r"[a-zA-Z_][a-zA-Z0-9_.]{0,119}\Z")
DLL = re.compile(r"[a-z0-9_][a-z0-9_.-]{0,78}\.dll\Z")
MAX_FILES, MAX_BYTES = 4096, 512 * MIB
REPARSE = 0x400


def ordinary(path):
    attributes = path.lstat()
    if stat.S_ISLNK(attributes.st_mode) or getattr(attributes, "st_file_attributes", 0) & REPARSE:
        raise ValueError("Package path contains a redirect")
    return attributes


def ordinary_ancestry(path):
    if not path.is_absolute() or ".." in path.parts or path.drive.startswith("\\\\"):
        raise ValueError("Expected an absolute local package path")
    for ancestor in (path, *path.parents):
        if not stat.S_ISDIR(ordinary(ancestor).st_mode):
            raise ValueError("Package parent is not a directory")


def read_data(path, limit):
    info = ordinary(path)
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
        raise ValueError("Expected bounded regular package data")
    with path.open("rb") as source:
        raw = source.read(limit + 1)
    if not 0 < len(raw) <= limit:
        raise ValueError("Package data changed or exceeded its bound")
    return raw


def payload_member(name):
    if not member_path(name):
        return False
    path = Path(name)
    if path.suffix == ".exe":
        return name in ROOT_ROLES.values()
    if path.suffix in {".dll", ".pyd", ".zip", "._pth"}:
        return name.startswith("python/")
    return path.suffix in {".py", ".cpp", ".h", ".json", ".txt", ".md"} and (
        "grant" not in path.name and "receipt" not in path.name)


def inventory(root):
    ordinary_ancestry(root)
    members, pending = {}, [root]
    count = total = 0
    while pending:
        for path in pending.pop().iterdir():
            count += 1
            if count > MAX_FILES:
                raise ValueError("Package file count exceeded")
            name = path.relative_to(root).as_posix()
            info = ordinary(path)
            if stat.S_ISDIR(info.st_mode):
                if not member_path(name + "/member"):
                    raise ValueError("Unexpected package directory")
                pending.append(path)
            elif not payload_member(name) or not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 256 * MIB:
                raise ValueError("Unexpected package member")
            else:
                total += info.st_size
                if total > MAX_BYTES:
                    raise ValueError("Package size exceeded")
                members[name] = info.st_size
    return members


def checked_payload(path, record, output=None):
    expected = record["bytes"]
    if ordinary(path).st_size != expected:
        raise ValueError("Package member size changed")
    sha = hashlib.sha256()
    observed = 0
    with path.open("rb") as source:
        while chunk := source.read(MIB):
            observed += len(chunk)
            if observed > expected:
                raise ValueError("Package member grew while reading")
            sha.update(chunk)
            if output is not None:
                output.write(chunk)
    if observed != expected or sha.hexdigest() != record["sha256"]:
        raise ValueError("Package member hash changed")


def validate_paths(paths):
    if tuple(paths.decode("ascii").splitlines()) != ISOLATED_PATHS:
        raise ValueError("Interpreter paths are not closed")


@dataclass(frozen=True, order=True)
class Resolution:
    consumer: str
    kind: str
    name: str
    provider: str


def closure_records(raw, members):
    closure = fields_from_json(raw, PACKAGE_LIMIT)
    if (not exact_keys(closure, "version resolutions notices")
            or type(closure["version"]) is not int or closure["version"] != 1
            or type(closure["resolutions"]) is not list or not closure["resolutions"]
            or type(closure["notices"]) is not dict
            or not REQUIRED_RUNTIME | {CLOSURE} <= members.keys()):
        raise ValueError("Incomplete runtime, resolver or notice closure")
    resolutions = []
    identities = set()
    for item in closure["resolutions"]:
        if not exact_keys(item, "consumer kind name provider") or any(type(value) is not str for value in item.values()):
            raise ValueError("Malformed resolution")
        record = Resolution(**item)
        consumer, kind, name, provider = record.consumer, record.kind, record.name, record.provider
        identity = (consumer, kind, name)
        if consumer not in members or identity in identities:
            raise ValueError("Unknown or duplicate resolution requester")
        dependencies = members[consumer]["requires"]
        if kind == "import":
            if (not IMPORT.fullmatch(name) or provider not in dependencies
                    or not provider.startswith(("python/", "tools/", "route/"))
                    or not provider.endswith((".py", ".pyd", ".zip"))
                    or name.split(".", 1)[0] in {"site", "pip"}
                    or (name.split(".", 1)[0] == "winsound" and consumer != "tools/operator_cue_worker.py")):
                raise ValueError("Unapproved Python module resolution")
        elif kind == "dll":
            if (not DLL.fullmatch(name) or
                    (provider == "system32/" + name and name not in OS_DLLS) or
                    (provider != "system32/" + name
                     and (provider not in dependencies or provider.rsplit("/", 1)[-1] != name))
                    or (name == "winmm.dll" and consumer != "python/winsound.pyd")):
                raise ValueError("Unapproved OS or package DLL resolution")
        else:
            raise ValueError("Unknown resolver category")
        identities.add(identity)
        resolutions.append(record)
    names = {record.consumer for record in resolutions}
    if not {ROOT_ROLES[key] for key in ("loader", "interpreter", "operator", "supervisor", "controller", "watchdog", "reader")} <= names:
        raise ValueError("Fixed role is missing its checked resolver record")
    notices = closure["notices"]
    for name, member in members.items():
        notice = notices.get(member["license"])
        if type(notice) is not str or notice not in members or not notice.startswith("route/licenses/"):
            raise ValueError(f"Missing retained license notice for {name}")
    return tuple(sorted(resolutions))


def assemble(staging, output, specification):
    """Write an exclusive, content-pinned data package with manifest published last."""
    if (output.is_relative_to(staging) or staging.is_relative_to(output)
            or ".." in output.parts or not output.is_absolute()):
        raise ValueError("Assembly output must be a separate absolute directory")
    ordinary_ancestry(output.parent)
    listing = inventory(staging)
    if (not exact_keys(specification, "source tree members")
            or any(type(specification[key]) is not str or not GIT_ID.fullmatch(specification[key])
                   for key in ("source", "tree"))
            or type(specification["members"]) is not list):
        raise ValueError("Unsupported package assembly specification")
    members = {}
    for record in specification["members"]:
        if not exact_keys(record, "path bytes sha256 origin license requires"):
            raise ValueError("Incomplete member lock")
        name = record["path"]
        dependencies = record["requires"]
        if (not member_path(name) or name in members or type(record["bytes"]) is not int
                or listing.get(name) != record["bytes"] or not is_sha(record["sha256"])
                or any(type(record[key]) is not str or not 0 < len(record[key]) <= 300 for key in ("origin", "license"))
                or type(dependencies) is not list or any(not member_path(dep) for dep in dependencies)
                or len(set(dependencies)) != len(dependencies)):
            raise ValueError("Invalid or missing locked package member")
        members[name] = record
    if listing.keys() != members.keys():
        raise ValueError("Staged package differs from the exact member lock")
    validate_graph(members)
    for name, record in members.items():
        checked_payload(staging / name, record)
    closure = read_data(staging / CLOSURE, PACKAGE_LIMIT)
    if digest(closure) != members[CLOSURE]["sha256"]:
        raise ValueError("Resolver closure changed during assembly")
    closure_records(closure, members)
    paths = read_data(staging / "python/python313._pth", 1024)
    if digest(paths) != members["python/python313._pth"]["sha256"]:
        raise ValueError("Interpreter path file changed")
    validate_paths(paths)
    validate_pair(read_data(staging / ROOT_ROLES["pair"], 8192), members)
    raw = canonical(dict(version=1, platform="windows-x64", source=specification["source"],
                         tree=specification["tree"], roots=ROOT_ROLES,
                         members=[members[name] for name in sorted(members)]))
    if len(raw) > PACKAGE_LIMIT:
        raise ValueError("Package manifest exceeded its bound")
    output.mkdir()
    for name, record in members.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            checked_payload(staging / name, record, stream)
    with (output / "package.json").open("xb") as stream:
        stream.write(raw)
    return digest(raw)


@dataclass(frozen=True)
class InstallationObservation:
    directory: Path
    root: object
    manifest: bytes
    manifest_file: object
    pair: bytes
    closure: bytes
    interpreter_paths: bytes
    files: dict
    resolutions: tuple[Resolution, ...]


@dataclass(frozen=True)
class FixedLaunch:
    package: object
    loader: Path
    interpreter: Path
    entry: Path
    directory: Path


def load_fixed(registered_directory, approved_manifest, observe, launch):
    """Dispatch the fixed supervisory role through an injected pre-entry boundary."""
    if not callable(observe) or not callable(launch):
        raise PermissionError("Required protected loader capability is missing")
    observed = observe(registered_directory)
    if (type(observed) is not InstallationObservation or observed.directory != registered_directory
            or not registered_directory.is_absolute()
            or ".." in registered_directory.parts or registered_directory.drive.startswith("\\\\")):
        raise PermissionError("Installed package location changed")
    package = validate_package(observed.manifest, observed.pair, approved_manifest=approved_manifest,
                               root=observed.root, manifest_file=observed.manifest_file, files=observed.files)
    members = {item["path"]: item for item in fields_from_json(observed.manifest, PACKAGE_LIMIT)["members"]}
    closure_file = observed.files.get(CLOSURE)
    if closure_file is None:
        raise ValueError("Protected runtime closure is missing")
    closure_file.validate(len(observed.closure), digest(observed.closure))
    declared = closure_records(observed.closure, members)
    observed.files["python/python313._pth"].validate(len(observed.interpreter_paths), digest(observed.interpreter_paths))
    validate_paths(observed.interpreter_paths)
    if observed.resolutions != declared:
        raise PermissionError("Observed Python import or DLL resolution differs")
    return launch(FixedLaunch(package, registered_directory / ROOT_ROLES["loader"],
                              registered_directory / ROOT_ROLES["interpreter"],
                              registered_directory / ROOT_ROLES["supervisor"], registered_directory))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Assemble data for a future protected capture package.")
    parser.add_argument("staging", type=Path)
    parser.add_argument("lock", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.lock.name != "package-lock.json":
            raise ValueError("Expected the package-lock.json input")
        lock = fields_from_json(read_data(args.lock, PACKAGE_LIMIT), PACKAGE_LIMIT)
        print(assemble(args.staging.absolute(), args.output.absolute(), lock))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

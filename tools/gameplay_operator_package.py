"""Pure admission checks for the proposed protected Windows capture package.

Object observations are supplied by the trusted installation adapter. A
manifest or operator request cannot stand in for those observations.
"""

from dataclasses import dataclass
import hashlib
import json
import ntpath
from pathlib import PurePosixPath
import re

import gameplay_operator_runtime as runtime
from gameplay_attribution import SHA
from gameplay_raw import BOUNDARY_POLICY, WIRE_SCHEMA

PACKAGE_LIMIT = 512 * 1024
PAIR_LIMIT = 8192
ROOT_ROLES = {
    "loader": "bin/capture-loader.exe",
    "interpreter": "python/python.exe",
    "operator": "tools/gameplay_operator.py",
    "supervisor": "tools/operator_supervisor.py",
    "controller": "tools/operator_controller.py",
    "watchdog": "tools/operator_watchdog.py",
    "reader": "bin/gameplay-raw-reader.exe",
    "pair": "bin/reader-pair.json",
    "consumer": "tools/gameplay_raw.py",
    "native_source": "tools/gameplay-raw-reader/witness.cpp",
}
RUNTIME_ROOT_ROLES = ROOT_ROLES | {
    "interpreter": runtime.CONSOLE,
    "background_interpreter": runtime.BACKGROUND,
    **{role: entry for role, entry, _, _ in runtime.ENTRIES},
}


def package_runtime(value):
    if value != runtime.RUNTIME_ID:
        raise ValueError("Unsupported operator package runtime")
    return value


PREFIXES = {"bin", "python", "tools", "route"}
SEGMENT = re.compile(r"[a-z0-9_][a-z0-9_.-]{0,79}\Z")
GIT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def exact_keys(value, names):
    return type(value) is dict and value.keys() == set(names.split())


def is_sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def fields_from_json(raw, limit):
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        raise ValueError("Receipt exceeds its byte bound")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate receipt field: {key}")
            result[key] = value
        return result

    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique)


def member_path(name):
    if type(name) is not str or len(name) > 200:
        return False
    parts = name.split("/")
    return (len(parts) > 1 and parts[0] in PREFIXES
            and all(SEGMENT.fullmatch(part) and not part.endswith(".")
                    and not ntpath.isreserved(part) for part in parts))


def payload_member(name, roots):
    if not member_path(name):
        return False
    path = PurePosixPath(name)
    if path.suffix == ".exe":
        return name in roots.values()
    if path.suffix in {".dll", ".pyd", ".zip", "._pth"}:
        return name.startswith("python/")
    return path.suffix in {".py", ".cpp", ".h", ".json", ".txt", ".md"} and (
        "grant" not in path.name and "receipt" not in path.name)


@dataclass(frozen=True)
class ProtectedObject:
    identity: str
    owner: str
    ordinary_write: bool
    reparse: bool

    def require_protected(self):
        if (not self.identity or self.owner not in {"system", "administrators", "trusted-installer"}
                or self.ordinary_write is not False or self.reparse is not False):
            raise PermissionError("Unknown, writable or redirected package authority")


@dataclass(frozen=True)
class ObservedFile:
    first: ProtectedObject
    current: ProtectedObject
    size: int
    sha256: str

    def validate(self, size, sha256):
        if self.first != self.current:
            raise PermissionError("Package object changed during validation")
        self.current.require_protected()
        if type(self.size) is not int or self.size != size or self.sha256 != sha256:
            raise ValueError("Observed package payload does not match")


@dataclass(frozen=True)
class ProtectedRoot:
    ancestry: tuple[ProtectedObject, ...]
    current_ancestry: tuple[ProtectedObject, ...]
    resolution_closed: bool

    def require_protected(self):
        if not self.ancestry or self.ancestry != self.current_ancestry or self.resolution_closed is not True:
            raise PermissionError("Package ancestry or import/DLL resolution is unverified")
        for ancestor in self.ancestry:
            ancestor.require_protected()


@dataclass(frozen=True)
class Package:
    manifest_sha256: str
    source: str
    tree: str
    pair_sha256: str
    reader_sha256: str
    interpreter_sha256: str
    runtime_id: str | None = None
    background_interpreter_sha256: str | None = None

    @property
    def background_sha256(self):
        if self.runtime_id is None:
            return self.interpreter_sha256  # Version 1 used one image for every role.
        return self.background_interpreter_sha256


def validate_runtime_members(members):
    actual = {name: (item["bytes"], item["sha256"]) for name, item in members.items()
              if name.startswith("python/")}
    if actual != runtime.RUNTIME_FILES:
        raise ValueError("Selected runtime file inventory or pin differs")
    if any(not payload_member(name, RUNTIME_ROOT_ROLES) for name in members):
        raise ValueError("Unexpected selected runtime package member")
    for name, pin in runtime.NOTICE_FILES.items():
        member = members.get(name)
        if member is None or (member["bytes"], member["sha256"]) != pin:
            raise ValueError(f"Selected runtime notice missing or pin differs for {name}")
    for name, member in members.items():
        license_id = runtime.MEMBER_LICENSES.get(name)
        if license_id is None:
            if member["license"] in runtime.LICENSE_NOTICES:
                raise ValueError(f"Unexpected selected runtime license reference for {name}")
            continue
        if member["license"] != license_id:
            raise ValueError(f"Selected runtime license reference differs for {name}")
        required_notices = set(runtime.LICENSE_NOTICES[license_id]) - {name}
        notice_edges = runtime.NOTICE_FILES.keys() & member["requires"]
        if notice_edges != required_notices:
            raise ValueError(f"Selected runtime notice dependencies differ for {name}")
    for consumer, required in runtime.REQUIRED_EDGES.items():
        if consumer not in members or not required <= set(members[consumer]["requires"]):
            raise ValueError(f"Missing selected runtime dependency for {consumer}")


def validate_graph(members, roots=ROOT_ROLES):
    reachable = set()
    pending = list(roots.values())
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        if name not in members:
            raise ValueError("Missing transitive package dependency")
        reachable.add(name)
        pending.extend(members[name]["requires"])
    if reachable != members.keys():
        raise ValueError("Unreferenced package member")


def validate_pair(pair_raw, members):
    pair = fields_from_json(pair_raw, PAIR_LIMIT)
    pair_sha256 = digest(pair_raw)
    reader = members[ROOT_ROLES["reader"]]["sha256"]
    if (not exact_keys(pair, "version wire_schema ambiguity_policy reader_sha256 native_source_sha256 "
                            "consumer_source_sha256 compile_receipt_sha256")
            or type(pair["version"]) is not int or pair["version"] != 1
            or type(pair["wire_schema"]) is not int or pair["wire_schema"] != WIRE_SCHEMA
            or pair["ambiguity_policy"] != BOUNDARY_POLICY or pair["reader_sha256"] != reader
            or pair["native_source_sha256"] != members[ROOT_ROLES["native_source"]]["sha256"]
            or pair["consumer_source_sha256"] != members[ROOT_ROLES["consumer"]]["sha256"]
            or not is_sha(pair["compile_receipt_sha256"])
            or pair_sha256 != members[ROOT_ROLES["pair"]]["sha256"]):
        raise ValueError("Package reader pair or provenance does not match")
    return pair_sha256, reader


def validate_package(manifest_raw, pair_raw, *, approved_manifest, root, manifest_file, files):
    """Validate observed closure, stable objects and the explicitly reviewed pair."""
    root.require_protected()
    manifest = fields_from_json(manifest_raw, PACKAGE_LIMIT)
    manifest_hash = digest(manifest_raw)
    if not is_sha(approved_manifest) or approved_manifest != manifest_hash:
        raise PermissionError("Package manifest lacks independent approval")
    manifest_file.validate(len(manifest_raw), manifest_hash)
    version = manifest.get("version") if type(manifest) is dict else None
    if type(version) is not int or version not in (1, runtime.MANIFEST_VERSION):
        raise ValueError("Unsupported operator package layout")
    fields = "version platform source tree roots members"
    roots = ROOT_ROLES
    runtime_id = None
    if version == runtime.MANIFEST_VERSION:
        fields += " runtime"
        roots = RUNTIME_ROOT_ROLES
        runtime_id = package_runtime(manifest.get("runtime"))
    if (not exact_keys(manifest, fields)
            or manifest["platform"] != "windows-x64"
            or any(type(manifest[key]) is not str or not GIT_ID.fullmatch(manifest[key]) for key in ("source", "tree"))
            or manifest["roots"] != roots or type(manifest["members"]) is not list):
        raise ValueError("Unsupported operator package layout")
    members = {}
    for member in manifest["members"]:
        if not exact_keys(member, "path bytes sha256 origin license requires"):
            raise ValueError("Incomplete package member provenance")
        name = member["path"]
        required = member["requires"]
        if (not member_path(name) or name in members or type(member["bytes"]) is not int
                or not 0 < member["bytes"] <= 256 * 1024**2 or not is_sha(member["sha256"])
                or any(type(member[key]) is not str or not 0 < len(member[key]) <= 300
                       for key in ("origin", "license"))
                or type(required) is not list or any(not member_path(path) for path in required)
                or len(set(required)) != len(required)):
            raise ValueError("Invalid package member or dependency")
        members[name] = member
    if not set(roots.values()) <= members.keys() or files.keys() != members.keys():
        raise ValueError("Observed package inventory differs from required closure")
    if runtime_id is not None:
        validate_runtime_members(members)
    validate_graph(members, roots)
    for name, member in members.items():
        files[name].validate(member["bytes"], member["sha256"])
    pair_sha256, reader = validate_pair(pair_raw, members)
    return Package(manifest_hash, manifest["source"], manifest["tree"], pair_sha256, reader,
                   members[roots["interpreter"]]["sha256"], runtime_id,
                   members[runtime.BACKGROUND]["sha256"] if runtime_id is not None else None)

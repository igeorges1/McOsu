"""Version-2 admission with synthetic observations, without a runtime payload.

These fixtures provide declared sizes/hashes; they never materialize, load or
verify a vendor interpreter. Actual Windows observation and trust are separate.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import gameplay_operator_bootstrap as bootstrap
import gameplay_operator_package as package
import gameplay_operator_runtime as runtime
from gameplay_operator_test import observation
from gameplay_raw import BOUNDARY_POLICY, WIRE_SCHEMA


class RuntimeChecks(unittest.TestCase):
    def setUp(self):
        for name in ("ctypes.WinDLL", "ctypes.CDLL", "subprocess.Popen"):
            blocked = patch(name, side_effect=AssertionError("Unexpected native or child entry"))
            blocked.start()
            self.addCleanup(blocked.stop)
        self.directory = ROOT / "synthetic-protected-package-not-created"
        names = (set(package.RUNTIME_ROOT_ROLES.values()) | runtime.RUNTIME_FILES.keys()
                 | runtime.NOTICE_FILES.keys() | {runtime.MARK_INVENTORY, runtime.PACKAGE,
                    runtime.POLICY_SOURCE, bootstrap.CLOSURE, "route/licenses/inert.txt"})
        self.members = {}
        for name in sorted(names):
            size, sha = (runtime.RUNTIME_FILES | runtime.NOTICE_FILES).get(
                name, (len(name), package.digest(name.encode("ascii"))))
            license_id = runtime.MEMBER_LICENSES.get(name, "inert")
            required = set(runtime.REQUIRED_EDGES.get(name, ()))
            required |= set(runtime.LICENSE_NOTICES.get(license_id, ())) - {name}
            self.members[name] = dict(path=name, bytes=size, sha256=sha,
                origin="Synthetic observation only; no vendor file", license=license_id,
                requires=sorted(required))
        resolutions = set(runtime.REQUIRED_RESOLUTIONS)
        resolutions |= {
            (package.ROOT_ROLES["loader"], "dll", "kernel32.dll", "system32/kernel32.dll"),
            (package.ROOT_ROLES["reader"], "dll", "tdh.dll", "system32/tdh.dll"),
        }
        for role in ("supervisor", "controller", "watchdog", "cue_worker"):
            resolutions.add((package.RUNTIME_ROOT_ROLES[role], "import", "json", runtime.STDLIB))
        self.resolutions = tuple(sorted(bootstrap.Resolution(*row) for row in resolutions))
        for row in self.resolutions:
            if row.provider in self.members:
                required = self.members[row.consumer]["requires"]
                self.members[row.consumer]["requires"] = sorted(set(required) | {row.provider})
        loader = package.ROOT_ROLES["loader"]
        self.members[loader]["requires"] = sorted(names - {loader})
        self.closure = dict(version=1, resolutions=[asdict(row) for row in self.resolutions],
            notices={"inert": "route/licenses/inert.txt"}
                    | {key: list(value) for key, value in runtime.LICENSE_NOTICES.items()})
        self.pair = package.canonical(dict(version=1, wire_schema=WIRE_SCHEMA,
            ambiguity_policy=BOUNDARY_POLICY,
            reader_sha256=self.members[package.ROOT_ROLES["reader"]]["sha256"],
            native_source_sha256=self.members[package.ROOT_ROLES["native_source"]]["sha256"],
            consumer_source_sha256=self.members[package.ROOT_ROLES["consumer"]]["sha256"],
            compile_receipt_sha256="c" * 64))
        self.load = Mock(name="inert loader; no native launch")

    def enter(self, members=None, closure=None, paths=runtime.PATHS):
        members = deepcopy(self.members if members is None else members)
        closure_raw = package.canonical(self.closure if closure is None else closure)
        for name, raw in ((bootstrap.CLOSURE, closure_raw), (package.ROOT_ROLES["pair"], self.pair)):
            members[name].update(bytes=len(raw), sha256=package.digest(raw))
        raw = package.canonical(dict(version=2, platform="windows-x64", source="1" * 40,
            tree="2" * 40, runtime=runtime.RUNTIME_ID, roots=package.RUNTIME_ROOT_ROLES,
            members=list(members.values())))
        files = {name: package.ObservedFile(observation(name), observation(name),
                    row["bytes"], row["sha256"]) for name, row in members.items()}
        root = observation("inert root")
        view = bootstrap.InstallationObservation(self.directory,
            package.ProtectedRoot((root,), (root,), True), raw,
            package.ObservedFile(root, root, len(raw), package.digest(raw)), self.pair, closure_raw,
            paths, files, self.resolutions,
            bootstrap.RuntimeObservation(runtime.RUNTIME_ID, runtime.VERSION, runtime.MACHINE,
                runtime.BACKGROUND_SUBSYSTEM, self.directory / runtime.BACKGROUND,
                self.directory / package.RUNTIME_ROOT_ROLES["supervisor"], runtime.FLAGS, True, True))
        return bootstrap.load_fixed(self.directory, package.digest(raw), lambda _: view, self.load)

    def refuses(self, message, **kwargs):
        self.load.reset_mock()
        with self.assertRaisesRegex((ValueError, PermissionError), message):
            self.enter(**kwargs)
        self.load.assert_not_called()

    def test_v2_selects_fixed_gui_supervisor_and_preserves_console_requester_pin(self):
        self.enter()
        plan, = self.load.call_args.args
        self.assertEqual(plan.interpreter, self.directory / runtime.BACKGROUND)
        self.assertEqual(plan.entry, self.directory / package.RUNTIME_ROOT_ROLES["supervisor"])
        self.assertEqual(plan.flags, runtime.FLAGS)
        self.assertEqual(plan.package.interpreter_sha256, runtime.RUNTIME_FILES[runtime.CONSOLE][1])
        self.assertEqual(plan.package.background_sha256, runtime.RUNTIME_FILES[runtime.BACKGROUND][1])

    def test_runtime_inventory_rejects_missing_extra_and_reapproved_changed_metadata(self):
        for change in ("missing", "extra", "digest", "size"):
            with self.subTest(change=change):
                members = deepcopy(self.members)
                if change == "missing":
                    del members["python/_queue.pyd"]
                elif change == "extra":
                    members["python/extra.pyd"] = members["python/_queue.pyd"] | {"path": "python/extra.pyd"}
                else:
                    members[runtime.BACKGROUND]["sha256" if change == "digest" else "bytes"] = (
                        "f" * 64 if change == "digest" else 1)
                self.refuses("runtime file inventory or pin", members=members)

    def test_notice_metadata_cannot_be_removed_renamed_or_repinned(self):
        for name in runtime.NOTICE_FILES:
            for change in ("missing", "rename", "digest", "size"):
                with self.subTest(name=name, change=change):
                    members = deepcopy(self.members)
                    if change in {"missing", "rename"}:
                        row = members.pop(name)
                        if change == "rename":
                            members[name + ".txt"] = row | {"path": name + ".txt"}
                    else:
                        members[name]["sha256" if change == "digest" else "bytes"] = (
                            "e" * 64 if change == "digest" else 1)
                    self.refuses("notice missing or pin", members=members)

    def test_license_groups_edges_and_resolver_providers_refuse_before_load(self):
        for name in runtime.MEMBER_LICENSES:
            with self.subTest(name=name):
                members = deepcopy(self.members)
                members[name]["license"] = "inert"
                self.refuses("runtime license reference", members=members)
        for consumer, dependencies in runtime.REQUIRED_EDGES.items():
            for dependency in dependencies:
                with self.subTest(consumer=consumer, dependency=dependency):
                    members = deepcopy(self.members)
                    members[consumer]["requires"].remove(dependency)
                    self.refuses("runtime dependency", members=members)
        members = deepcopy(self.members)
        members[package.ROOT_ROLES["reader"]]["license"] = runtime.CORE_LICENSE
        self.refuses("Unexpected selected runtime license", members=members)
        members = deepcopy(self.members)
        members[runtime.STDLIB]["requires"].remove(runtime.SUPPLEMENTAL_NOTICE)
        self.refuses("runtime notice dependencies", members=members)
        closure = deepcopy(self.closure)
        next(row for row in closure["resolutions"] if row["name"] == "gameplay_mark_inventory")["provider"] = runtime.PACKAGE
        self.refuses("runtime resolver providers differ", closure=closure)

    def test_ordered_notice_references_and_path_bytes_are_independent_gates(self):
        for group in runtime.LICENSE_NOTICES:
            for change in ("missing", "extra", "wrong_type"):
                with self.subTest(group=group, change=change):
                    closure = deepcopy(self.closure)
                    if change == "missing":
                        del closure["notices"][group]
                    elif change == "extra":
                        closure["notices"][group].append("route/licenses/inert.txt")
                    else:
                        closure["notices"][group] = closure["notices"][group][0]
                    self.refuses("closure notice reference", closure=closure)
        closure = deepcopy(self.closure)
        closure["notices"][runtime.CORE_LICENSE].reverse()
        self.refuses("closure notice reference", closure=closure)
        self.refuses("Observed package payload", paths=runtime.PATHS + b"import site\n")

    def test_shipped_notice_source_bytes_match_selected_package_pins(self):
        for relative, (size, sha) in runtime.NOTICE_SOURCE_FILES.items():
            with self.subTest(path=relative):
                raw = (ROOT / relative).read_bytes()
                self.assertEqual((len(raw), package.digest(raw)), (size, sha))


if __name__ == "__main__":
    unittest.main()

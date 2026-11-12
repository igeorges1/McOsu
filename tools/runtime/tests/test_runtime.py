"""Windows integration tests. Native fixture is test-only, never a game artifact."""
import json
from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime as r
import build as builder


@contextmanager
def owned_process(command, **kwargs):
    """Record identity; only terminate this owned handle if it exceeds the test."""
    with subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW, **kwargs) as p:
        start = time.monotonic()
        print(json.dumps({"test_pid": p.pid, "command": command, "cwd": str(kwargs.get("cwd", Path.cwd())),
                          "exe_sha256": r.digest(command[0]), "deadline_s": 20}), file=sys.stderr, flush=True)
        try:
            yield p
        finally:
            if p.poll() is None:
                p.kill()
            p.wait(timeout=5)
            print(json.dumps({"test_pid": p.pid, "exit": p.returncode, "exit_hex": hex(p.returncode & 0xffffffff),
                              "elapsed_s": round(time.monotonic() - start, 3)}), file=sys.stderr, flush=True)


@unittest.skipUnless(os.name == "nt", "Actual Windows deployment/process semantics required")
class RuntimeIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.error_mode = ctypes.WinDLL("kernel32").SetErrorMode(0x0001 | 0x0002)
        cls.addClassCleanup(ctypes.WinDLL("kernel32").SetErrorMode, cls.error_mode)
        cls.shared = tempfile.TemporaryDirectory(prefix="mcosu-fixture-", dir=Path(__file__).parents[1] / "out")
        root = Path(cls.shared.name)
        source = root / "fixture.c"
        source.write_text('''/* TEST ONLY: no game, window, audio or library access. */
#include <windows.h>
#include <stdio.h>
#include <direct.h>
#include <stdlib.h>
int main(int argc, char **argv) {
    char cwd[32768]; _getcwd(cwd, sizeof(cwd));
    FILE *f = fopen("fixture-cwd.txt", "wb");
    if (!f) return 7; fputs(cwd, f); fclose(f);
    if (argc > 1) {
        for (int i=0; i<1000; ++i) {
            f = fopen("fixture-release.txt", "rb");
            if (f) { fclose(f); break; } Sleep(10);
        }
    }
    if (argc > 3) {
        f = fopen("scores.db", "wb");
        if (!f) return 8; fputs(argv[3], f); fclose(f);
    }
    f = fopen("fixture-complete.txt", "wb");
    if (!f) return 9; fputs("COMPLETE failures=0", f); fclose(f);
    return argc > 2 ? atoi(argv[2]) : 0;
}
''', encoding="utf-8")
        compiler = os.environ.get("MCOSU_TEST_CC")
        if not compiler:
            raise RuntimeError("Set MCOSU_TEST_CC to the GCC8 bin/gcc.exe used for the native test fixture")
        cls.exe = root / "fixture.exe"
        env = dict(os.environ, PATH=str(Path(compiler).parent) + os.pathsep + os.environ["PATH"])
        subprocess.run([compiler, "-O2", "-static", str(source), "-o", str(cls.exe)], env=env, check=True, timeout=30)
        print(f"Fixture {cls.exe} SHA256={r.digest(cls.exe)}", file=sys.stderr, flush=True)

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-test-", dir=Path(__file__).parents[1] / "out")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "runtime with spaces"
        self.packages = []
        for index in (1, 2, 3):
            payload = self.base / ("payload" + str(index))
            (payload / "materials").mkdir(parents=True)
            (payload / "McOsu.exe").write_bytes(self.exe.read_bytes())
            (payload / "materials/common.txt").write_bytes(b"asset" + bytes([index]))
            (payload / ("materials/old.txt" if index == 1 else "materials/new.txt")).write_bytes(bytes([index]))
            package = self.base / ("package" + str(index))
            r.make_package(payload, {"source": str(index) * 40, "dirty": False, "engine": r.ENGINE_PIN,
                                    "test_fixture": True,
                                    "toolchain": {"version": "8.1.0", "target": "i686-w64-mingw32",
                                                  "threads": "win32", "exceptions": "dwarf2",
                                                  "gxx_sha256": "0" * 64, "tree_sha256": "0" * 64}}, package)
            self.packages.append(package)
        r.initialize(self.root)
        r.operate("update", self.root, self.packages[0])
        self.sentinels = {}
        for name in ("cfg/osu.cfg", "cfg/timing-audio-profiles.cfg", "cfg/osu.cfg.backup", "cfg/save.tmp",
                     "scores.db", "scoresvr.db", "collections.db", "stars.cache", "screenshots/test.png",
                     "version.txt", "unrelated.txt", "materials/custom-user.png", "other/nested.bin"):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"untouched\x00\xff\r\n" + name.encode())
            self.sentinels[name] = p.read_bytes()

    def snapshot(self, root=None):
        # Windows byte-range locks prohibit even reads by other handles.
        return {n: p.read_bytes() for n, p in r.files(root or self.root).items()
                if n != r.CONTROL + "/lock"}

    def preserved(self):
        self.assertEqual(self.sentinels, {n: (self.root / n).read_bytes() for n in self.sentinels})

    def cli(self, action, *args, root=None):
        return subprocess.run([sys.executable, str(r.__file__), action, "--runtime",
                               str(root or self.root), *map(str, args)],
                              capture_output=True, text=True, timeout=20)

    def refused_unchanged(self, callback, text=None):
        before = self.snapshot()
        with self.assertRaises(r.Refusal) as error:
            callback()
        if text:
            self.assertIn(text, str(error.exception))
        self.assertEqual(before, self.snapshot())

    def rewrite_manifest(self, package, change):
        m = r.read_json(package / "manifest.json")
        change(m)
        m["id"] = r.identity(m)
        r.write_json(package / "manifest.json", m)

    def test_update_rollback_preserve_all_state_and_bound_history(self):
        r.operate("update", self.root, self.packages[1])
        self.preserved()
        self.assertFalse((self.root / "materials/old.txt").exists())
        self.assertTrue((self.root / "materials/new.txt").exists())
        self.refused_unchanged(lambda: r.operate("rollback", self.root), "Compatibility")
        r.operate("rollback", self.root, acknowledge_state_risk=True)
        self.preserved()
        self.assertEqual((self.root / "materials/common.txt").read_bytes(), b"asset\x01")
        self.assertFalse((self.root / "materials/new.txt").exists())
        r.operate("update", self.root, self.packages[2])
        self.assertEqual(len(list((self.root / r.CONTROL / "bundles").iterdir())), 2)
        before = self.snapshot()
        r.operate("update", self.root, self.packages[2])
        self.assertEqual(before, self.snapshot())
        self.preserved()

    def test_dry_runs_and_inspection_do_not_write(self):
        before = self.snapshot()
        for action in ("inspect", "launch", "update", "rollback"):
            if action == "rollback":
                r.operate("update", self.root, self.packages[1])
                before = self.snapshot()
            r.operate(action, self.root, self.packages[2] if action == "update" else None, dry_run=True)
            self.assertEqual(before, self.snapshot())
        target = self.base / "not-created"
        r.initialize(target, dry_run=True)
        self.assertFalse(target.exists())

    def test_bad_packages_fail_before_mutation(self):
        p = self.packages[1]
        mpath = p / "manifest.json"
        original = mpath.read_bytes()
        cases = [lambda m: m["files"].update({"cfg/osu.cfg": {"size": 0, "sha256": "0" * 64}}),
                 lambda m: m["files"].update({"../escape": {"size": 0, "sha256": "0" * 64}}),
                 lambda m: m["files"].update({"materials/x:ads": {"size": 0, "sha256": "0" * 64}}),
                 lambda m: m["files"].update({"materials/NUL.txt": {"size": 0, "sha256": "0" * 64}}),
                 lambda m: m["build"].update({"dirty": True}),
                 lambda m: m["build"].update({"engine": "0" * 40}),
                 lambda m: m["build"].update({"toolchain": {}}),
                 lambda m: m["build"].update({"source": None}),
                 lambda m: m.update({"format": 99})]
        for change in cases:
            with self.subTest(change=change):
                mpath.write_bytes(original)
                self.rewrite_manifest(p, change)
                self.refused_unchanged(lambda: r.operate("update", self.root, p))
        mpath.write_bytes(original)
        (p / "payload/materials/common.txt").write_bytes(b"corruption")
        self.refused_unchanged(lambda: r.operate("update", self.root, p), "mismatch")
        (p / "payload/materials/common.txt").write_bytes(b"asset\x02")
        (p / "extra.log").write_text("not in manifest")
        self.refused_unchanged(lambda: r.operate("update", self.root, p), "Unmanifested")
        (p / "extra.log").unlink()
        mpath.write_text('{"format":1,"format":1}')
        self.refused_unchanged(lambda: r.operate("update", self.root, p), "Duplicate")

    def test_unmanaged_and_nonempty_initialization_refused(self):
        root = self.base / "unmanaged"
        root.mkdir()
        (root / "keep.txt").write_bytes(b"keep")
        before = self.snapshot(root)
        with self.assertRaises(r.Refusal):
            r.operate("update", root, self.packages[1])
        with self.assertRaises(r.Refusal):
            r.initialize(root)
        self.assertEqual(before, self.snapshot(root))

    def test_explicit_import_copies_state_without_sharing(self):
        target = self.base / "imported"
        before = self.snapshot()
        r.initialize(target, import_from=self.root)
        self.assertEqual(before, self.snapshot())
        self.assertFalse((target / "McOsu.exe").exists())
        self.assertFalse((target / "materials/custom-user.png").exists())
        for name in self.sentinels:
            if name.split("/")[0] in r.PERSISTENT:
                self.assertEqual((target / name).read_bytes(), self.sentinels[name])
        (target / "cfg/osu.cfg").write_bytes(b"changed copy")
        self.preserved()

    def test_competing_init_cannot_overwrite_completed_runtime(self):
        target = self.base / "contested runtime"
        import_cfg = self.base / "import source" / "cfg"
        import_cfg.mkdir(parents=True)
        (import_cfg / "osu.cfg").write_bytes(b"losing import")
        scan = r.files
        winner = {}

        def interleave(path):
            if path == import_cfg:
                initialized = self.cli("init", root=target)
                self.assertEqual(initialized.returncode, 0, initialized.stderr)
                deployed = self.cli("update", "--package", self.packages[0], root=target)
                self.assertEqual(deployed.returncode, 0, deployed.stderr)
                (target / "cfg/osu.cfg").write_bytes(b"winning runtime state")
                winner.update(self.snapshot(target))
            return scan(path)

        # Make a second real CLI initialization finish during the first import scan.
        with patch.object(r, "files", interleave):
            with self.assertRaisesRegex(r.Refusal, "empty|initializ"):
                r.initialize(target, import_cfg.parent)
        self.assertTrue(winner)
        self.assertEqual(winner, self.snapshot(target))

    def test_failed_first_import_can_retry_empty_destination(self):
        source = self.base / "state source"
        source.mkdir()
        (source / "scores.db").write_bytes(b"original scores")
        target = self.base / "import retry"
        with patch.object(r.shutil, "copyfile", side_effect=PermissionError("source open failed")):
            with self.assertRaises(PermissionError):
                r.initialize(target, source)
        self.assertEqual(list(target.iterdir()), [])
        result = self.cli("init", "--import-from", source, root=target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((target / "scores.db").read_bytes(), b"original scores")

    def test_readonly_package_assets_do_not_block_rollback_or_collection(self):
        asset = self.packages[1] / "payload/materials/common.txt"
        asset.chmod(stat.S_IREAD)
        self.addCleanup(asset.chmod, stat.S_IREAD | stat.S_IWRITE)
        for action, args in (
            ("update", ("--package", self.packages[1])),
            ("rollback", ("--acknowledge-state-risk",)),
            ("rollback", ("--acknowledge-state-risk",)),
            ("update", ("--package", self.packages[2])),
            ("update", ("--package", self.packages[0])),
        ):
            result = self.cli(action, *args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.preserved()
        self.assertFalse(asset.stat().st_mode & stat.S_IWRITE)
        self.assertEqual(len(list((self.root / r.CONTROL / "bundles").iterdir())), 2)

    def test_readonly_legacy_stage_and_bundle_can_be_retired(self):
        control = self.root / r.CONTROL
        old_bundle = control / "bundles" / r.validate(self.packages[0])["id"]
        asset = self.packages[0] / "payload/materials/common.txt"
        asset.chmod(stat.S_IREAD)
        self.addCleanup(asset.chmod, stat.S_IREAD | stat.S_IWRITE)
        # Older copies preserved the package's file attributes inside both trees.
        shutil.copymode(asset, old_bundle / "payload/materials/common.txt")
        shutil.copytree(self.packages[0], control / "stage")
        for package in self.packages[1:]:
            result = self.cli("update", "--package", package)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.preserved()
        self.assertFalse(old_bundle.exists())
        self.assertFalse((control / "stage").exists())
        self.assertFalse(asset.stat().st_mode & stat.S_IWRITE)
        self.assertEqual(len(list((control / "bundles").iterdir())), 2)

    def test_failed_replacement_recovers_without_rewriting_unchanged_asset(self):
        asset = self.root / "materials/common.txt"
        asset.chmod(stat.S_IREAD)
        self.addCleanup(asset.chmod, stat.S_IREAD | stat.S_IWRITE)
        before = self.snapshot()
        result = self.cli("update", "--package", self.packages[1])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse((self.root / r.CONTROL / "transaction.json").exists(), result.stderr)
        self.assertIn("pre-update bundle restored", result.stderr)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(asset.stat().st_mode & stat.S_IWRITE)
        self.preserved()

    def test_changed_owned_and_conflicting_unowned_files_are_refused(self):
        (self.root / "materials/new.txt").write_bytes(b"user file")
        self.refused_unchanged(lambda: r.operate("update", self.root, self.packages[1]), "Unowned")
        (self.root / "materials/new.txt").unlink()
        (self.root / "materials/common.txt").write_bytes(b"customized managed asset")
        self.refused_unchanged(lambda: r.operate("update", self.root, self.packages[1]), "changed")

    def test_failed_update_automatically_restores_previous_bundle(self):
        before = self.snapshot()
        replace = os.replace
        failed = []

        def failure(source, target):
            if Path(target) == self.root / "materials/common.txt" and not failed:
                failed.append(True)
                raise OSError("test-only simulated disk failure after earlier mutations")
            return replace(source, target)

        with patch.object(r.os, "replace", failure):
            with self.assertRaisesRegex(r.Refusal, "pre-update bundle restored"):
                r.operate("update", self.root, self.packages[1])
        self.assertTrue(failed)
        self.assertEqual(before, self.snapshot())
        self.preserved()

    def test_hard_interruption_recovery_uses_actual_journal(self):
        before_state = r.operate("inspect", self.root)
        code = '''import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import runtime as r
original = os.replace
def interrupt(source, target):
    original(source, target)
    if Path(target) == Path(sys.argv[2]) / "materials/common.txt": os._exit(73)
r.os.replace = interrupt
r.operate("update", Path(sys.argv[2]), Path(sys.argv[3]))
'''
        result = subprocess.run([sys.executable, "-c", code, str(Path(r.__file__).parent),
                                 str(self.root), str(self.packages[1])])
        self.assertEqual(result.returncode, 73)
        self.assertTrue(r.operate("inspect", self.root)["recovery_required"])
        for action in ("update", "rollback", "launch"):
            self.refused_unchanged(lambda: r.operate(action, self.root,
                                                   self.packages[1] if action == "update" else None), "Interrupted")
        r.operate("recover", self.root)
        self.assertEqual(before_state, r.operate("inspect", self.root))
        self.assertEqual((self.root / "materials/common.txt").read_bytes(), b"asset\x01")
        self.assertTrue((self.root / "materials/old.txt").exists())
        self.assertFalse((self.root / "materials/new.txt").exists())
        self.preserved()
        r.operate("update", self.root, self.packages[1])
        self.preserved()

    def test_interruption_after_pointer_switch_retains_old_rollback_history(self):
        r.operate("update", self.root, self.packages[1])
        before = r.operate("inspect", self.root)
        code = '''import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import runtime as r
original = os.replace
def interrupt(source, target):
    original(source, target)
    if Path(target).name == "state.json": os._exit(74)
r.os.replace = interrupt
r.operate("update", Path(sys.argv[2]), Path(sys.argv[3]))
'''
        result = subprocess.run([sys.executable, "-c", code, str(Path(r.__file__).parent),
                                 str(self.root), str(self.packages[2])])
        self.assertEqual(result.returncode, 74)
        self.assertTrue(r.operate("inspect", self.root)["recovery_required"])
        # Recovery itself can be interrupted after replacing an asset and safely retried.
        code = code.replace('if Path(target).name == "state.json": os._exit(74)',
                            'if Path(target).name == "common.txt": os._exit(75)')
        code = code.replace('r.operate("update", Path(sys.argv[2]), Path(sys.argv[3]))',
                            'r.operate("recover", Path(sys.argv[2]))')
        result = subprocess.run([sys.executable, "-c", code, str(Path(r.__file__).parent), str(self.root)])
        self.assertEqual(result.returncode, 75)
        r.operate("recover", self.root)
        self.assertEqual(before, r.operate("inspect", self.root))
        self.assertEqual((self.root / "materials/common.txt").read_bytes(), b"asset\x02")
        r.operate("rollback", self.root, acknowledge_state_risk=True)
        self.assertEqual((self.root / "materials/common.txt").read_bytes(), b"asset\x01")
        self.preserved()

    def await_file(self, path):
        deadline = time.monotonic() + 8
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(path.exists(), "Native fixture failed to start")

    def test_external_active_image_is_refused_before_any_write(self):
        with owned_process([str(self.root / "McOsu.exe"), "wait"], cwd=self.root) as child:
            try:
                self.await_file(self.root / "fixture-cwd.txt")
                for action in ("update", "rollback", "launch", "recover"):
                    self.refused_unchanged(lambda: r.operate(action, self.root,
                                                           self.packages[1] if action == "update" else None), "active")
            finally:
                (self.root / "fixture-release.txt").write_bytes(b"release our test-only process")
                self.assertEqual(child.wait(timeout=10), 0)
                self.assertEqual((self.root / "fixture-complete.txt").read_text(), "COMPLETE failures=0")
        self.preserved()

    def test_cli_launch_cwd_lock_and_native_exit(self):
        launcher = Path(r.__file__)
        command = [sys.executable, str(launcher), "launch", "--runtime", str(self.root), "--", "wait"]
        with owned_process(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
            try:
                self.await_file(self.root / "fixture-cwd.txt")
                self.assertEqual(Path((self.root / "fixture-cwd.txt").read_text()), self.root)
                self.refused_unchanged(lambda: r.operate("update", self.root, self.packages[1]), "active")
            finally:
                (self.root / "fixture-release.txt").write_bytes(b"release")
                stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(json.loads(stdout)["exit_code"], 0)
            self.assertEqual((self.root / "fixture-complete.txt").read_text(), "COMPLETE failures=0")
        self.preserved()

    def test_lock_and_junction_refusals(self):
        with r.locked(self.root):
            self.refused_unchanged(lambda: r.operate("update", self.root, self.packages[1]), "locked")
        # Junctions need no elevated symlink privilege on Windows.
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "sentinel").write_bytes(b"outside")
        link = self.root / "materials/link"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            with self.assertRaisesRegex(r.Refusal, "junction"):
                r.operate("update", self.root, self.packages[1])
            self.assertEqual((outside / "sentinel").read_bytes(), b"outside")
        finally:
            link.rmdir()  # Remove our link only, never its target.

    def test_packager_requires_completed_unchanged_build(self):
        built = self.base / "built"
        built.mkdir()
        shutil.copytree(self.packages[0] / "payload", built / "payload")
        record = {"complete": True, "identity": r.validate(self.packages[0])["build"],
                  "payload_hashes": {n: r.digest(p) for n, p in r.files(built / "payload").items()}}
        r.write_json(built / "build.json", record)
        destination = self.base / "repackaged"
        builder.package_build(built, destination)
        self.assertEqual(r.validate(destination), r.validate(self.packages[0]))
        (built / "payload/McOsu.exe").write_bytes(b"tampered")
        with self.assertRaises(r.Refusal):
            builder.package_build(built, self.base / "must-not-exist")
        self.assertFalse((self.base / "must-not-exist").exists())

    def test_build_refuses_unignored_in_tree_output_before_dependency_checks(self):
        source = self.base / "clean source"
        subprocess.run(["git", "init", "-q", str(source)], check=True, capture_output=True)
        # This is a disposable Git fixture, not a new project worktree.
        git = ["git", "-C", str(source), "-c", "user.name=Runtime Fixture",
               "-c", "user.email=runtime-fixture@example.invalid"]
        (source / ".gitignore").write_text("/ignored/\n", encoding="utf-8")
        subprocess.run([*git, "add", ".gitignore"], check=True, capture_output=True)
        subprocess.run([*git, "commit", "-qm", "fixture"], check=True, capture_output=True)
        command = [sys.executable, str(builder.__file__), "build", "--source", str(source),
                   "--engine", str(self.base / "missing engine"), "--toolchain", str(self.base / "cc"),
                   "--assets", str(self.base / "assets"), "--out"]
        refused = subprocess.run([*command, str(source / "unignored")], capture_output=True, text=True)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("Git-ignored", refused.stderr)
        self.assertFalse((source / "unignored").exists())
        accepted = subprocess.run([*command, str(source / "ignored/fresh")], capture_output=True, text=True)
        # An ignored output passes the gate and reaches the deliberately absent engine.
        self.assertEqual(accepted.returncode, 1)
        self.assertNotIn("Git-ignored", accepted.stderr)
        self.assertIn("missing engine", accepted.stderr)

    def stage(self, index=1, **kwargs):
        return r.operate("stage", self.root, self.packages[index], **kwargs)

    def status(self):
        return r.operate("status", self.root)

    def test_queue_independent_lock_replace_cancel_and_identity(self):
        before = self.snapshot()
        with r.locked(self.root):
            self.assertEqual(self.stage()["result"], "staged")
            staged = self.snapshot()
            self.assertEqual(self.stage()["result"], "already-queued")
            self.assertEqual(self.stage(0)["result"], "already-installed")
            self.assertEqual(staged, self.snapshot())
            self.refused_unchanged(lambda: self.stage(2), "--replace")
            self.assertEqual(self.stage(2, replace=True)["queued"]["source"], "3" * 40)
            self.assertEqual(self.status()["installed"]["source"], "1" * 40)
            self.assertEqual(r.operate("cancel", self.root)["result"], "cancelled")
        self.assertEqual({n: b for n, b in before.items() if not n.startswith(r.CONTROL + "/")},
                         {n: b for n, b in self.snapshot().items() if not n.startswith(r.CONTROL + "/")})
        self.assertIsNone(self.status()["backup"])

    def test_launcher_stage_during_child_and_fresh_exit_backup(self):
        ctl = self.root / "preview-runtime.py"
        launch = self.root / "Launch-preview.cmd"
        shutil.copyfile(r.__file__, ctl)
        shutil.copyfile(Path(r.__file__).with_name(launch.name), launch)
        (self.root / "preview-python.txt").write_text(sys.executable + "\n", encoding="ascii")
        plan = subprocess.run([str(launch), "--dry-run"], cwd=self.base, shell=True,
                              capture_output=True, text=True, timeout=20)
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertEqual(Path(json.loads(plan.stdout)["cwd"]), self.root)
        cmd = [sys.executable, str(ctl), "launch", "--runtime", str(self.root), "--", "wait", "0", "last-save"]
        with owned_process(cmd, cwd=self.base, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
            self.await_file(self.root / "fixture-cwd.txt")
            self.assertEqual(self.stage()["result"], "staged")
            pending = self.status()
            self.assertEqual(pending["installed"]["source"], "1" * 40)
            self.assertIsNone(pending["backup"])
            self.assertTrue(pending["active_images"])
            (self.root / "fixture-release.txt").touch()
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout)["after_exit"]["result"], "promoted")
        self.assertEqual((self.root / "fixture-complete.txt").read_text(), "COMPLETE failures=0")
        current = self.status()
        self.assertEqual(current["installed"]["source"], "2" * 40)
        self.assertEqual(current["previous"]["source"], "1" * 40)
        self.sentinels["scores.db"] = b"last-save"
        self.preserved()
        with zipfile.ZipFile(current["backup"]["path"]) as z:
            meta = json.loads(z.read("backup.json"))
            expected = {n: b for n, b in self.sentinels.items() if n.split("/")[0] in r.BACKUP_PATHS}
            self.assertEqual({n: z.read("state/" + n) for n in meta["files"]}, expected)
            self.assertEqual(meta["candidate"], current["installed"]["id"])

    def test_nonzero_exit_holds_and_defer_suppresses_both_edges(self):
        self.stage()
        (self.root / "fixture-release.txt").touch()
        run = self.cli("launch", "--defer-queue", "--", "wait", "9")
        self.assertEqual(run.returncode, 9, run.stderr)
        self.assertEqual(self.status()["queued"]["phase"], "queued")
        self.assertIsNone(self.status()["backup"])
        r.operate("cancel", self.root)
        (self.root / "fixture-release.txt").unlink()
        (self.root / "fixture-cwd.txt").unlink()
        cmd = [sys.executable, str(r.__file__), "launch", "--runtime", str(self.root), "--", "wait", "9"]
        with owned_process(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
            self.await_file(self.root / "fixture-cwd.txt")
            self.stage()
            (self.root / "fixture-release.txt").touch()
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 9, stderr)
        self.assertEqual(json.loads(stdout)["after_exit"]["result"], "held")
        held = self.status()
        self.stage()
        self.stage(0)
        self.assertEqual(self.status(), held)
        self.assertEqual(self.cli("launch").returncode, 0)
        self.assertEqual(self.status(), held)
        self.assertEqual(r.operate("retry", self.root)["result"], "promoted")

    def test_failed_or_missing_candidate_and_failed_backup_never_auto_retry(self):
        self.stage()
        p = self.status()["queued"]["id"]
        bundle = self.root / r.CONTROL / "bundles" / p
        shutil.move(bundle, self.base / "removed-package")
        result = self.cli("launch")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["before_launch"]["result"], "failed")
        self.assertEqual(self.status()["queued"]["phase"], "held")
        self.assertIsNone(self.status()["backup"])
        self.stage()  # Repairs the missing copy, without rearming it.
        with patch.object(r, "BACKUP_LIMIT", 0):
            self.assertEqual(r.operate("retry", self.root)["exit_code"], 1)
        held = self.status()
        self.assertIn("backup size limit", held["last"]["detail"])
        self.assertEqual(held["installed"]["source"], "1" * 40)
        self.assertEqual(self.cli("launch").returncode, 0)
        self.assertEqual(self.status(), held)
        self.assertEqual(r.operate("retry", self.root)["result"], "promoted")
        self.preserved()

    def test_prelaunch_promotion_known_good_and_safe_gc(self):
        pin = r.operate("pin", self.root)["known_good"]
        unknown = self.root / r.CONTROL / "bundles" / ("0" * 64)
        unknown.mkdir()
        (unknown / "owner-note").write_text("leave me")
        self.stage()
        result = self.cli("launch")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["before_launch"]["result"], "promoted")
        self.stage(2)
        r.operate("retry", self.root)
        self.assertEqual(self.status()["known_good"]["id"], pin)
        r.operate("rollback", self.root, to="known-good", acknowledge_state_risk=True)
        self.assertEqual(self.status()["installed"]["id"], pin)
        self.preserved()
        self.assertEqual((unknown / "owner-note").read_text(), "leave me")
        self.assertEqual(len(list((self.root / r.CONTROL).glob("*.zip"))), 1)

    def test_queue_interrupted_journal_protects_references_and_reconciles(self):
        self.stage()
        before = self.status()["installed"]["id"]
        code = '''import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import runtime as r
original = os.replace
def interrupt(source, target):
    original(source, target)
    if Path(target).name == "common.txt": os._exit(76)
r.os.replace = interrupt
r.operate("retry", Path(sys.argv[2]))
'''
        result = subprocess.run([sys.executable, "-c", code, str(Path(r.__file__).parent), str(self.root)], timeout=20)
        self.assertEqual(result.returncode, 76)
        interrupted = self.status()
        self.assertTrue(interrupted["recovery_required"])
        self.assertEqual(interrupted["queued"]["phase"], "held")
        for act in ("cancel", "pin"):
            with self.assertRaisesRegex(r.Refusal, "Interrupted"):
                r.operate(act, self.root)
        with self.assertRaisesRegex(r.Refusal, "Interrupted"):
            self.stage(2, replace=True)
        r.operate("recover", self.root)
        self.assertEqual(self.status()["installed"]["id"], before)
        self.assertEqual(r.operate("retry", self.root)["result"], "promoted")
        self.preserved()

    def test_legacy_migration_and_downgrade_gate(self):
        r.operate("disable-queue", self.root)
        self.assertFalse(self.status()["queue_enabled"])
        self.refused_unchanged(lambda: self.stage(), "Enable the queue")
        state = r.read_json(self.root / r.CONTROL / "state.json")
        self.assertEqual(state["kind"], "mcosu-flat-runtime-v1")
        r.operate("enable-queue", self.root)
        self.assertNotEqual(r.read_json(self.root / r.CONTROL / "state.json")["kind"], state["kind"])
        self.stage()
        self.refused_unchanged(lambda: r.operate("disable-queue", self.root), "Cancel the queue")
        r.operate("cancel", self.root)
        r.operate("pin", self.root)
        self.refused_unchanged(lambda: r.operate("disable-queue", self.root), "unpin")
        r.operate("unpin", self.root)
        r.operate("disable-queue", self.root)
        self.assertEqual(r.read_json(self.root / r.CONTROL / "state.json"), state)
        self.preserved()


if __name__ == "__main__":
    (Path(__file__).parents[1] / "out").mkdir(exist_ok=True)
    result = unittest.main(verbosity=2, exit=False, failfast=True).result
    print(f"COMPLETE failures={len(result.failures) + len(result.errors)} tests={result.testsRun}", flush=True)
    sys.exit(0 if result.wasSuccessful() else 1)

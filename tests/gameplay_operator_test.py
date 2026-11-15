"""Exercise the source-only operator interfaces with inert owned observations."""

from contextlib import redirect_stderr, redirect_stdout
import ctypes
from dataclasses import asdict, replace
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import gameplay_operator as op
from gameplay_collector import MODE, PROFILE
from gameplay_operator_package import (ObservedFile, ProtectedObject, ProtectedRoot, ROOT_ROLES, canonical, digest,
                                       member_path, validate_package)
from gameplay_raw import BOUNDARY_POLICY, WIRE_SCHEMA

SOURCE = "a" * 40
TARGET_SETTINGS = (1, 1, 0, 0, 1, 121, 120, 120, 0, 0, 100, 12, 0, 1)
ACCOUNT = "inert-desktop-account"


def refuse(*args, **kwargs):
    raise AssertionError("Unexpected native, process, playback or decoder entry")


def observation(identity):
    return ProtectedObject(identity, "administrators", False, False)


def package_fixture():
    payloads = {name: name.encode("ascii") for name in ROOT_ROLES.values()}
    dependency = "python/python313.dll"
    payloads[dependency] = b"inert interpreter dependency"
    pair = dict(version=1, wire_schema=WIRE_SCHEMA, ambiguity_policy=BOUNDARY_POLICY,
                reader_sha256=digest(payloads[ROOT_ROLES["reader"]]),
                native_source_sha256=digest(payloads[ROOT_ROLES["native_source"]]),
                consumer_source_sha256=digest(payloads[ROOT_ROLES["consumer"]]),
                compile_receipt_sha256="c" * 64)
    pair_raw = canonical(pair)
    payloads[ROOT_ROLES["pair"]] = pair_raw
    records = [dict(path=name, bytes=len(data), sha256=digest(data), origin="inert reviewed source", license="MIT",
                    requires=[dependency] if name == ROOT_ROLES["interpreter"] else [])
               for name, data in payloads.items()]
    files = {name: ObservedFile(observation(name), observation(name), len(data), digest(data))
             for name, data in payloads.items()}
    root = ProtectedRoot((observation("system drive"), observation("installed package")),
                         (observation("system drive"), observation("installed package")), True)
    manifest = dict(version=1, platform="windows-x64", source="d" * 40, tree="0" * 40, roots=ROOT_ROLES, members=records)
    return manifest, pair_raw, root, files


def write_mark(root, number, mark, *, map_id="a" * 32, context=op.FOCUSED | op.PLAY, history=False, final=True):
    parent = root / f"mark-{1000 + number}-00"
    parent.mkdir()
    boundary = 2 if history else 1
    points = [(1, mark - 15, mark - 5)] if history else []
    points.append((boundary, mark - 5, mark + 5))
    rows = [f"frame {seq} 1 {start} {end} {start + 3} 0 0 {context} 0 0 0 0 0 0 0 0"
            for seq, start, end in points]
    contents = ["MCOSU_GAMEPLAY_QPC 1", f"source {SOURCE}", "map " + map_id, "identity 44 9001 71 1000",
                f"mark {number} 1 {mark} {boundary}", "settings " + " ".join(map(str, TARGET_SETTINGS)),
                "status recording", "post_end target", f"counts {boundary} {boundary} 0 0",
                "stages 0 0 0", *rows, "end complete" if final else "end partial"]
    (parent / "gameplay.qpc").write_text("\n".join(contents) + "\n", encoding="ascii")
    (parent / "export.txt").write_text("gameplay_qpc=saved\n", encoding="ascii")
    return parent.name


class OperatorChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.captures = self.root / "timing-captures"
        self.captures.mkdir()
        self.attempt_base, self.report_base = self.root / "protected", self.root / "reports"
        self.attempt_base.mkdir()
        self.report_base.mkdir()
        self.manifest, self.pair, self.protection, self.files = package_fixture()
        self.package = self.validate_package()
        self.requester = self.actor(10, False)
        self.supervisor, self.controller, self.watchdog = (self.actor(pid, True) for pid in (20, 21, 22))
        self.cue_worker = self.actor(23, False)
        self.target = op.Target(44, 9001, 71, 1000, SOURCE, "e" * 64, ACCOUNT, 1, TARGET_SETTINGS,
                                "game", "thread", str(self.root / "McOsu.exe"))

    def actor(self, pid, elevated):
        return op.ProcessObject(op.Actor(pid, 80 + pid, ACCOUNT, 1, self.package.interpreter_sha256, elevated),
                                f"object-{pid}")

    def validate_package(self, *, manifest=None, pair=None, protection=None, files=None, approved=None):
        raw = canonical(self.manifest if manifest is None else manifest)
        manifest_file = ObservedFile(observation("package.json"), observation("package.json"), len(raw), digest(raw))
        return validate_package(raw, self.pair if pair is None else pair,
                                approved_manifest=digest(raw) if approved is None else approved,
                                root=self.protection if protection is None else protection,
                                manifest_file=manifest_file,
                                files=self.files if files is None else files)

    def test_package_inventory_pair_and_observed_protection(self):
        self.assertEqual(self.package.reader_sha256, digest(ROOT_ROLES["reader"].encode("ascii")))
        with self.assertRaisesRegex(PermissionError, "independent approval"):
            self.validate_package(approved="0" * 64)
        for path in ("bin/../evil.exe", "tools/con.txt", "C:/scripts/tool.py", "tools/evil.py:stream", "bin/x."):
            self.assertFalse(member_path(path))
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.validate_package(files=self.files | {"python/phantom.dll": next(iter(self.files.values()))})
        with self.assertRaisesRegex(PermissionError, "ancestry"):
            self.validate_package(protection=replace(self.protection, resolution_closed=False))
        writable = replace(self.protection.ancestry[0], ordinary_write=True)
        with self.assertRaisesRegex(PermissionError, "writable"):
            self.validate_package(protection=ProtectedRoot((writable,), (writable,), True))
        victim, observed = next(iter(self.files.items()))
        changed = replace(observed, current=observation("replacement"))
        with self.assertRaisesRegex(PermissionError, "changed"):
            self.validate_package(files=self.files | {victim: changed})
        with self.assertRaisesRegex(ValueError, "reader pair"):
            self.validate_package(pair=canonical(json.loads(self.pair) | {"wire_schema": 1}))
        records = [member | {"requires": ["route/missing.py"]} if member["path"] == ROOT_ROLES["controller"]
                   else member for member in self.manifest["members"]]
        with self.assertRaisesRegex(ValueError, "transitive"):
            self.validate_package(manifest=self.manifest | {"members": records})

    def prepare(self, *, cue="soft", **overrides):
        write_mark(self.captures, 1, 12, context=0, map_id="unknown")
        baseline = op.select_baseline(self.captures, self.target, (), 10)
        request = dict(version=1, operation="start-operator-capture", session=str(uuid.uuid4()), profile="diagnostic",
                       package_sha256=self.package.manifest_sha256, preferences={"active_cue": cue}, budget={})
        args = dict(package=self.package, profile="diagnostic", requester=self.requester, target=self.target,
                    baseline=baseline, baseline_floor_qpc=10, attempt_base=self.attempt_base,
                    capture_directory=self.captures, report_base=self.report_base, start_ms=100, dispatch_ms=200)
        return op.prepare_attempt(request, **(args | overrides))

    def session(self, *, cue="soft"):
        plan = self.prepare(cue=cue)
        return op.Session(plan, self.supervisor, self.controller, 300,
                          cue_worker=None if cue == "off" else self.cue_worker)

    def phase(self, session, name, seq, ms, qpc, *, publisher=None, props=None, **changes):
        payload = dict(session=session.plan.session, plan_sha256=session.plan.sha256, sequence=seq, phase=name,
                       ms=ms, qpc=qpc, readiness_sha256=None, start_sha256=None,
                       restored=False, owned_query=False, loss=None) | changes
        return session.read_phase(canonical(payload), publisher or self.controller, properties=props)

    def arm(self, session):
        self.phase(session, "READY", 1, 360, 20)
        with self.assertRaisesRegex(PermissionError, "registered target"):
            session.mark_ready(self.root / "other-captures", "mark-123-00")
        bad = write_mark(self.captures, 2, 21, context=op.FOCUSED | op.PLAY | op.LOADING)
        with self.assertRaisesRegex(ValueError, "focused, loaded"):
            session.mark_ready(self.captures, bad)
        folder = write_mark(self.captures, 3, 24)
        mark = session.mark_ready(self.captures, folder)
        readiness = digest(mark.raw)
        self.phase(session, "ARMING", 2, 400, 26, readiness_sha256=readiness)
        with self.assertRaisesRegex(PermissionError, "registration"):
            session.authorize_start(420)
        proof = op.HandleRegistration(self.supervisor, self.controller, self.watchdog, self.watchdog, 450)
        with self.assertRaisesRegex(PermissionError, "registration"):
            session.register_handles(replace(proof, transferred_watchdog=self.controller))
        session.register_handles(proof)
        return readiness

    def active(self, session, readiness):
        start = session.authorize_start(460)
        with self.assertRaisesRegex(PermissionError, "registration"):
            session.authorize_start(461)
        session_id = session.plan.session
        properties = dict(name="McOsu-Controlled-" + session_id, guid=session_id,
                          file=str(Path(session.plan.directory) / "fixture.etl"), context=23, clock=1, mode=MODE,
                          keywords=PROFILE, file_mib=256, buffer_kib=64, minimum=128, maximum=128, number=128)
        with self.assertRaisesRegex(PermissionError, "owned samples"):
            self.phase(session, "RECORDING", 3, 500, 30, props=properties,
                       readiness_sha256=readiness, restored=True, owned_query=True, loss=0)
        return self.phase(session, "RECORDING", 3, 500, 30, props=properties, start_sha256=start.sha256,
                          readiness_sha256=readiness, restored=True, owned_query=True, loss=0)

    def test_start_identity_replay_quota_and_mixed_entries(self):
        session = self.session()
        with self.assertRaises(FileExistsError):
            op.Session(session.plan, self.supervisor, self.controller, 300)
        with self.assertRaisesRegex(PermissionError, "Expired consent"):
            op.Session(session.plan, self.supervisor, self.controller, session.plan.consent_until_ms)
        for index in range(8):
            (self.captures / f"mark-{index}-00").mkdir()
        self.assertEqual(op.capture_capacity(self.captures, 12, 3)[1:], (3, 3))
        (self.captures / "unrelated.partial").mkdir()
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            op.capture_capacity(self.captures, 12, 3)
        (self.captures / "ordinary.txt").write_text("inert", encoding="ascii")
        self.assertEqual(op.capture_capacity(self.captures, 12, 1)[1:], (2, 1))
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            op.select_baseline(self.captures, self.target, (), 10)

    def test_baseline_ambiguity_and_cross_user_refuse(self):
        with self.assertRaisesRegex(PermissionError, "identity"):
            self.prepare(target=replace(self.target, account="other"))
        write_mark(self.captures, 4, 22, map_id="unknown", context=0)
        with self.assertRaisesRegex(ValueError, "one fresh"):
            op.select_baseline(self.captures, self.target, (), 10)
        good = op.select_baseline(self.captures, self.target, ("mark-1004-00",), 10)
        self.assertEqual(good.folder, "mark-1001-00")

    def test_active_once_and_worker_result_does_not_drive_state(self):
        session = self.session()
        with self.assertRaisesRegex(ValueError, "Malformed"):
            session.read_phase(b"{}", self.controller)
        with self.assertRaises(json.JSONDecodeError):
            session.read_phase(b'{"session":', self.controller)
        with self.assertRaisesRegex(PermissionError, "foreign"):
            self.phase(session, "RECORDING", 3, 500, 30, publisher=self.supervisor)
        readiness = self.arm(session)
        active = self.active(session, readiness)
        self.assertIsNone(session.take_cue(active, active.ms + 251))
        task = session.take_cue(active, active.ms + 1)
        self.assertIsNotNone(task)
        self.assertIsNone(session.take_cue(active, active.ms + 1))

        def bounded_worker(wave, **limits):
            self.assertEqual((wave[:4], len(wave)), (b"RIFF", 3116))
            self.assertEqual(limits, dict(deadline_ms=500, memory_bytes=64 * 1024**2, output_bytes=8192))
            return op.CueResult("timeout", 1001)

        session.finish_cue(task, op.deliver_cue(task, bounded_worker))
        view = session.view()
        self.assertEqual((view["phase"], view["release"], view["cue"]), ("RECORDING", "unverified", "timeout"))
        self.assertEqual(view["cue_request"]["active_qpc"], 30)
        self.assertEqual(view["app_settings"], TARGET_SETTINGS)
        self.assertIs(view["owns_app"], False)
        self.assertEqual(op.deliver_cue(task, unittest.mock.Mock(side_effect=TimeoutError())).disposition, "timeout")
        with self.assertRaisesRegex(PermissionError, "Stale"):
            session.observe(active)

    def test_stop_races_and_disabled_cue(self):
        session = self.session(cue="off")
        active = self.active(session, self.arm(session))
        self.assertIsNone(session.take_cue(active, 501))
        session.request_stop()
        self.phase(session, "STOPPING", 4, 530, 90)
        self.assertIsNone(session.take_cue(active, 531))
        self.assertEqual(session.view()["release"], "unverified")

    def test_pending_stop_rejects_start_and_late_active_never_cues(self):
        session = self.session()
        self.arm(session)
        session.request_stop()
        with self.assertRaisesRegex(PermissionError, "registration"):
            session.authorize_start(460)
        self.phase(session, "STOPPING", 4, 530, 90)
        self.assertIsNone(session.take_cue(None, 531))
        self.assertEqual(session.view()["phase"], "STOPPING")
        self.assertFalse((Path(session.plan.directory) / "operator-start-intent.json").exists())

    def assert_rejected_active_cannot_cue(self, reject):
        session = self.session()
        active = self.active(session, self.arm(session))
        with self.assertRaises((ValueError, PermissionError)):
            reject(session, active)
        self.assertIsNone(session.take_cue(active, active.ms + 1))
        self.assertEqual(session.view()["phase"], "STATUS UNVERIFIED")
        self.phase(session, "STOPPING", 4, 520, 90)
        self.assertEqual(session.view()["phase"], "STOPPING")
        self.assertEqual(session.view()["release"], "unverified")

    def test_malformed_read_invalidates_previous_active_cue(self):
        self.assert_rejected_active_cannot_cue(lambda session, _: session.read_phase(b"{}", self.controller))

    def test_foreign_snapshot_invalidates_previous_active_cue(self):
        self.assert_rejected_active_cannot_cue(
            lambda session, active: session.observe(replace(active, publisher=self.supervisor, sequence=4)))

    def test_stale_snapshot_invalidates_previous_active_cue(self):
        self.assert_rejected_active_cannot_cue(lambda session, active: session.observe(active))

    def test_release_operator_v2_and_complete_mark_with_partial_history(self):
        session = self.session()
        self.active(session, self.arm(session))
        self.phase(session, "STOPPING", 4, 600, 96)
        release = op.ReleaseEvidence(
            session.plan.session, session.plan.sha256, self.supervisor,
            op.ExitEvidence(self.controller, 0, 620), op.ExitEvidence(self.watchdog, 0, 614),
            op.ExitEvidence(self.supervisor, 0, 635), 632, "McOsu-Controlled-" + session.plan.session,
            session.plan.session, 4201, True, False, 0, 0, True, False, 90, ((30, 0), (78, 0), (84, 0)),
            op.ExitEvidence(self.cue_worker, 0, 610),
        )
        with self.assertRaisesRegex(PermissionError, "verified"):
            session.select_evidence(self.captures)
        for changes in ({"query_status": 5}, {"query_guid": "foreign"}, {"target_owned": True},
                        {"watchdog_recovery": True}, {"query_ms": 605}, {"cue_exit": None},
                        {"watchdog_exit": replace(release.watchdog_exit, process=self.requester)}):
            with self.assertRaisesRegex(PermissionError, "unverified"):
                session.finish_release(replace(release, **changes))
        session.finish_release(release)
        self.assertEqual(session.view()["marked_answer"], "unavailable")
        self.assertIsNone(session.select_evidence(self.captures))
        selected = write_mark(self.captures, 5, 40, history=True, final=False)
        write_mark(self.captures, 6, 78)  # penultimate sample is the exclusive edge
        write_mark(self.captures, 7, 50)
        with self.assertRaisesRegex(ValueError, "Select one"):
            session.select_evidence(self.captures)
        mark = session.select_evidence(self.captures, folder=selected)
        proof = dict(version=2, operation="operator-marked-analysis", session=session.plan.session,
                     plan_sha256=session.plan.sha256, release_sha256=digest(canonical(asdict(release))),
                     mark_sha256=digest(mark.raw), trace_sha256="f" * 64, trace_bytes=1024,
                     wire_schema=WIRE_SCHEMA, pair_sha256=self.package.pair_sha256,
                     reader_sha256=self.package.reader_sha256)
        for change in ({"version": 1}, {"operation": "one-offline-raw-gameplay-analysis"},
                       {"wire_schema": 1}, {"trace_bytes": True}, {"pair_sha256": "1" * 64}):
            with self.assertRaisesRegex(PermissionError, "proof v2"):
                session.admit_analysis(proof | change, mark, trace_sha256="f" * 64, trace_bytes=1024)
        admission = session.admit_analysis(proof, mark, trace_sha256="f" * 64, trace_bytes=1024)
        self.assertTrue(Path(session.plan.report_directory, "operator-analysis-intent.json").is_file())
        self.assertFalse(Path(session.plan.directory, "operator-analysis-intent.json").exists())
        report = session.save_marked_report(admission, [{"start": 35, "end": 45, "state": "waiting"}])
        self.assertEqual(report["marked_frame"]["status"], "complete")
        self.assertTrue(report["history"]["app_partial"])
        self.assertEqual(report["history"]["scheduler_ticks"]["unknown"], 10)
        self.assertEqual(report["history"]["partial_frames"], 1)
        self.assertEqual(report["history"]["frame_ticks"]["count"], 2)
        self.assertEqual(self.cli("reopen", session.plan.report_directory)[0], 0)
        self.assertFalse(Path(session.plan.directory, op.REPORT_FILE).exists())
        self.assertEqual(json.loads(Path(session.plan.report_directory, op.REPORT_FILE).read_bytes())["session"],
                         session.plan.session)
        unknown_mark = op.marked_report(admission, [{"start": 35, "end": 40, "state": "waiting"}])
        self.assertEqual(unknown_mark["marked_frame"]["status"], "partial")
        self.assertEqual(unknown_mark["marked_frame"]["ticks"]["unknown"], 5)
        with self.assertRaisesRegex(PermissionError, "unused"):
            session.admit_analysis(proof, mark, trace_sha256="f" * 64, trace_bytes=1024)

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = op.main(list(args))
        return status, out.getvalue(), err.getvalue()

    def test_cli_persistence_help_refusal_and_readonly_reopen(self):
        self.assertEqual(self.cli("start")[:2], (2, op.UNAVAILABLE + "\n"))
        self.assertFalse((self.root / op.PREFERENCES_FILE).exists())
        status, out, error = self.cli("settings", "--preferences", str(self.root), "--active-cue", "clear", "--save")
        self.assertEqual((status, error, json.loads(out)["effective"]["active_cue"]), (0, "", "clear"))
        self.assertEqual(op.read_preferences(self.root), {"active_cue": "clear"})
        bad = self.cli("settings", "--baseline-wait-ms", "999")
        self.assertEqual(bad[0], 1)
        preferences = self.root / op.PREFERENCES_FILE
        preferences.write_bytes(b'{"version":1,"preferences":{"active_cue":"off","active_cue":"soft"}}')
        self.assertEqual(self.cli("settings", "--preferences", str(self.root))[0], 1)
        report_path = self.root / op.REPORT_FILE
        archive = canonical(dict(version=1, session=str(uuid.uuid4()), release="verified", cue="api-ok"))
        report_path.write_bytes(archive)
        status, out, _ = self.cli("reopen", str(self.root))
        self.assertEqual((status, json.loads(out)["live_release"], report_path.read_bytes()),
                         (0, "unverified", archive))
        self.assertEqual(set(self.root.iterdir()), {self.captures, preferences, report_path,
                                                   self.attempt_base, self.report_base})


if __name__ == "__main__":
    original = Path.open

    def guarded_open(path, *args, **kwargs):
        if path.suffix.lower() in {".etl", ".exe", ".dll"}:
            refuse()
        return original(path, *args, **kwargs)

    with (patch.object(ctypes, "WinDLL", create=True, side_effect=refuse),
          patch.object(subprocess, "Popen", side_effect=refuse),
          patch.object(Path, "open", guarded_open)):
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(OperatorChecks)
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    if result.wasSuccessful():
        print(f"COMPLETE gameplay operator checks={result.testsRun}")
    raise SystemExit(0 if result.wasSuccessful() else 1)

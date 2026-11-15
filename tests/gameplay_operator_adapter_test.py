"""Offline assembly, fixed-role dispatch and owned channel regressions."""

from dataclasses import asdict, replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gameplay_operator_test import ACCOUNT, SOURCE, TARGET_SETTINGS, observation, write_mark
from gameplay_operator import Actor, ExitEvidence, HandleRegistration, ProcessObject, ReleaseEvidence, Target, select_baseline
from gameplay_collector import MODE, PROFILE
from gameplay_operator_adapter import CaptureChannel, LocalPeer, Message, OriginalEntry, open_attempt
from gameplay_operator_bootstrap import (CLOSURE, ISOLATED_PATHS, InstallationObservation, Resolution, assemble,
                                          load_fixed, main)
from gameplay_operator_package import ObservedFile, ProtectedRoot, ROOT_ROLES, canonical, digest
from gameplay_operator_route import WatchdogArm
from gameplay_raw import BOUNDARY_POLICY, WIRE_SCHEMA


class AdapterChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.staging, self.output = self.root / "staging", self.root / "assembled"
        self.lock, self.resolutions = self.stage(self.staging)

    def stage(self, root, *, path_file=None, resolver_override=None):
        payloads = {name: name.encode("ascii") for name in ROOT_ROLES.values()}
        runtime = {"python/python313.dll", "python/python313.zip", "python/python313._pth"}
        payloads.update({name: name.encode("ascii") for name in runtime})
        payloads["python/python313._pth"] = path_file or ("\n".join(ISOLATED_PATHS) + "\n").encode("ascii")
        notices = "route/licenses/reviewed.txt"
        payloads[notices] = b"Inert license fixture"
        resolutions = [
            Resolution(ROOT_ROLES["loader"], "dll", "kernel32.dll", "system32/kernel32.dll"),
            Resolution(ROOT_ROLES["interpreter"], "dll", "python313.dll", "python/python313.dll"),
            Resolution(ROOT_ROLES["reader"], "dll", "tdh.dll", "system32/tdh.dll"),
        ]
        resolutions.extend(Resolution(ROOT_ROLES[key], "import", "json", "python/python313.zip")
                           for key in ("operator", "supervisor", "controller", "watchdog"))
        if resolver_override is not None:
            resolutions[-1] = resolver_override
        payloads[CLOSURE] = canonical(dict(version=1, resolutions=[asdict(row) for row in resolutions],
                                           notices={"inert": notices}))
        role = ROOT_ROLES
        payloads[role["pair"]] = canonical(dict(
            version=1, wire_schema=WIRE_SCHEMA, ambiguity_policy=BOUNDARY_POLICY,
            reader_sha256=digest(payloads[role["reader"]]), native_source_sha256=digest(payloads[role["native_source"]]),
            consumer_source_sha256=digest(payloads[role["consumer"]]), compile_receipt_sha256="c" * 64))
        requires = {role["loader"]: [CLOSURE, notices], role["interpreter"]: sorted(runtime)}
        for key in ("operator", "supervisor", "controller", "watchdog"):
            requires[role[key]] = ["python/python313.zip"]
        records = []
        for name, raw in payloads.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            records.append(dict(path=name, bytes=len(raw), sha256=digest(raw), license="inert",
                                origin="inert source fixture", requires=requires.get(name, [])))
        return dict(source="1" * 40, tree="2" * 40, members=records), tuple(sorted(resolutions))

    def assemble_observation(self):
        approved = assemble(self.staging, self.output, self.lock)
        root = observation("approved installed root")
        files = {}
        for item in self.lock["members"]:
            raw = (self.output / item["path"]).read_bytes()
            obj = observation(item["path"])
            files[item["path"]] = ObservedFile(obj, obj, len(raw), digest(raw))
        raw = (self.output / "package.json").read_bytes()
        obj = observation("manifest")
        return approved, InstallationObservation(
            self.output, ProtectedRoot((root,), (root,), True), raw, ObservedFile(obj, obj, len(raw), digest(raw)),
            (self.output / ROOT_ROLES["pair"]).read_bytes(), (self.output / CLOSURE).read_bytes(),
            (self.output / "python/python313._pth").read_bytes(), files, self.resolutions,
        )

    def test_assembly_pins_real_bytes_deterministically_and_refuses_stale_input(self):
        approved, _ = self.assemble_observation()
        other = self.root / "second"
        self.assertEqual(assemble(self.staging, other, self.lock), approved)
        self.assertEqual((other / "package.json").read_bytes(), (self.output / "package.json").read_bytes())
        with self.assertRaises(FileExistsError):
            assemble(self.staging, other, self.lock)
        (self.staging / ROOT_ROLES["operator"]).write_bytes(b"replaced")
        with self.assertRaisesRegex(ValueError, "locked package member"):
            assemble(self.staging, self.root / "no-output", self.lock)
        self.assertFalse((self.root / "no-output").exists())

    def test_assembler_cli_refuses_extra_file_closure_and_external_python_path(self):
        lock_file = self.root / "package-lock.json"
        lock_file.write_bytes(canonical(self.lock))
        self.assertEqual(main([str(self.staging), str(lock_file), str(self.output)]), 0)
        bad = self.root / "bad-path"
        lock, _ = self.stage(bad, path_file=b"python313.zip\n.\nimport site\n")
        with self.assertRaisesRegex(ValueError, "paths are not closed"):
            assemble(bad, self.root / "no-package", lock)
        bad = self.root / "bad-dll"
        lock, _ = self.stage(bad, resolver_override=Resolution(ROOT_ROLES["watchdog"], "dll", "winmm.dll",
                                                              "system32/winmm.dll"))
        with self.assertRaisesRegex(ValueError, "DLL resolution"):
            assemble(bad, self.root / "no-package", lock)
        (self.staging / "route/old-grant.json").write_bytes(b"inert")
        with self.assertRaisesRegex(ValueError, "Unexpected package member"):
            assemble(self.staging, self.root / "no-package", self.lock)

    def test_fixed_dispatch_rejects_unverified_observations_before_load(self):
        approved, observed = self.assemble_observation()
        load = Mock(name="inert fixed loader")
        for bad in (replace(observed, resolutions=observed.resolutions[:-1]),
                    replace(observed, resolutions=observed.resolutions + (observed.resolutions[0],)),
                    replace(observed, root=replace(observed.root, resolution_closed=False)),
                    replace(observed, directory=self.root),
                    replace(observed, closure=observed.closure + b" "),
                    replace(observed, interpreter_paths=b"import site\n")):
            with self.assertRaises((ValueError, PermissionError)):
                load_fixed(self.output, approved, lambda _: bad, load)
        load.assert_not_called()
        load_fixed(self.output, approved, lambda _: observed, load)
        chosen, = load.call_args.args
        self.assertEqual(chosen.entry, self.output / "tools/operator_supervisor.py")
        self.assertEqual(chosen.interpreter, self.output / "python/python.exe")

    def open(self):
        approved, installed = self.assemble_observation()
        interpreter = digest(ROOT_ROLES["interpreter"].encode("ascii"))

        def actor(pid, elevated):
            return ProcessObject(Actor(pid, 50 + pid, ACCOUNT, 1, interpreter, elevated), f"inert-{pid}")

        requester, supervisor, controller, watchdog = actor(10, False), actor(20, True), actor(21, True), actor(22, True)
        self.captures, attempts, reports = self.root / "timing-captures", self.root / "attempts", self.root / "reports"
        for path in (self.captures, attempts, reports):
            path.mkdir()
        target = Target(44, 9001, 71, 1000, SOURCE, "e" * 64, ACCOUNT, 1, TARGET_SETTINGS,
                        "target", "app-thread", str(self.root / "McOsu.exe"))
        write_mark(self.captures, 1, 12, context=0, map_id="unknown")
        baseline = select_baseline(self.captures, target, (), 10)
        request = dict(version=1, operation="start-operator-capture", session=str(uuid.uuid4()), profile="diagnostic",
                       package_sha256=approved, preferences={}, budget={})
        inputs = dict(profile="diagnostic", requester=requester, target=target, baseline=baseline, baseline_floor_qpc=10,
                      attempt_base=attempts, capture_directory=self.captures, report_base=reports, start_ms=100, dispatch_ms=200)
        self.cue_worker = actor(23, False)
        consent = Mock(return_value=OriginalEntry(supervisor, controller, 300, self.cue_worker))
        with self.assertRaisesRegex(ValueError, "Start intent"):
            open_attempt(self.output, approved, request | {"output": "foreign"}, installation=lambda _: installed,
                         target_inputs=inputs, consent=consent)
        consent.assert_not_called()
        session = open_attempt(self.output, approved, request, installation=lambda _: installed,
                               target_inputs=inputs, consent=consent)
        with self.assertRaises(FileExistsError):
            open_attempt(self.output, approved, request, installation=lambda _: installed,
                         target_inputs=inputs, consent=consent)
        consent.assert_called_once()
        return session, watchdog

    def message(self, session, actor, sequence, kind, payload=None, **change):
        peer = LocalPeer("b" * 64, actor, True, True)
        return Message(**(dict(peer=peer, session=session.plan.session, plan_sha256=session.plan.sha256,
                              sequence=sequence, kind=kind, payload=payload) | change))

    def snapshot(self, session, number, phase, ms, qpc, **change):
        raw = canonical(dict(session=session.plan.session, plan_sha256=session.plan.sha256, sequence=number, phase=phase,
                             ms=ms, qpc=qpc, readiness_sha256=None, start_sha256=None, restored=False,
                             owned_query=False, loss=None) | change)
        return raw

    def arming(self):
        session, watchdog = self.open()
        start, stop = Mock(name="inert owned Start"), Mock(name="inert owned Stop")
        channel = CaptureChannel(session, "b" * 64, start, stop)
        ready = self.message(session, session.controller, 1, "phase", (self.snapshot(session, 1, "READY", 350, 20), None))
        channel.receive(lambda: ready)
        folder = write_mark(self.captures, 2, 24)
        mark = session.mark_ready(self.captures, folder)
        readiness = digest(mark.raw)
        active_wait = self.snapshot(session, 2, "ARMING", 400, 26, readiness_sha256=readiness)
        channel.receive(lambda: self.message(session, session.controller, 2, "phase", (active_wait, None)))
        registration = HandleRegistration(session.supervisor, session.controller, watchdog, watchdog, 450)
        context = dict(status="observed", effective_source="process", thread={"status": "no-token"},
                       process={"token_type": 1, "elevated": True}, enabled_administrator=True,
                       caller=dict(pid=watchdog.actor.pid, creation_filetime=watchdog.actor.creation))
        arm = WatchdogArm(registration, session.controller.actor.pid, session.controller.actor.creation,
                          watchdog.actor.pid, watchdog.actor.creation, 34400, True, context)
        return session, channel, start, stop, readiness, arm

    def test_owned_arm_start_stop_and_status_read_failure(self):
        session, channel, start, stop, readiness, arm = self.arming()
        channel.receive(lambda: self.message(session, session.supervisor, 1, "arm", arm))
        channel.receive(lambda: self.message(session, session.controller, 3, "start", 460))
        permit, = start.call_args.args
        ids = session.plan.session
        properties = dict(name="McOsu-Controlled-" + ids, guid=ids, file=str(Path(session.plan.directory) / "fixture.etl"),
                          context=23, clock=1, mode=MODE, keywords=PROFILE,
                          file_mib=256, buffer_kib=64, minimum=128, maximum=128, number=128)
        active = self.snapshot(session, 3, "RECORDING", 500, 30, readiness_sha256=readiness,
                               start_sha256=permit.sha256, restored=True, owned_query=True, loss=0)
        channel.receive(lambda: self.message(session, session.controller, 4, "phase", (active, properties)))
        with self.assertRaises(TimeoutError):
            channel.receive(Mock(side_effect=TimeoutError))
        self.assertIsNone(channel.take_cue(507))
        self.assertEqual(session.view()["phase"], "STATUS UNVERIFIED")
        low = self.message(session, session.plan.requester, 1, "stop")
        channel.receive(lambda: low)
        stop.assert_called_once_with(ids)
        with self.assertRaises(PermissionError):
            channel.receive(lambda: low)
        stop.assert_called_once()
        final = self.snapshot(session, 4, "STOPPING", 600, 90)
        channel.receive(lambda: self.message(session, session.controller, 5, "phase", (final, None)))
        release = ReleaseEvidence(
            ids, session.plan.sha256, session.supervisor,
            ExitEvidence(session.controller, 0, 620), ExitEvidence(arm.registration.watchdog, 0, 615),
            ExitEvidence(session.supervisor, 0, 630), 625, "McOsu-Controlled-" + ids, ids, 4201, True, False,
            0, 0, True, False, 85, ((30, 0), (75, 0), (80, 0)), ExitEvidence(self.cue_worker, 0, 611),
        )
        with self.assertRaisesRegex(PermissionError, "Foreign"):
            channel.receive(lambda: self.message(session, session.plan.requester, 2, "release", release))
        self.assertEqual(session.view()["release"], "unverified")
        channel.receive(lambda: self.message(session, session.supervisor, 2, "release", release))
        self.assertEqual((session.view()["phase"], session.view()["release"]), ("STOPPED", "verified"))

    def test_substituted_peer_or_missing_arm_never_calls_owned_start(self):
        session, channel, start, _, _, arm = self.arming()
        foreign = self.message(session, session.plan.requester, 1, "arm", arm)
        with self.assertRaisesRegex(PermissionError, "Foreign"):
            channel.receive(lambda: foreign)
        with self.assertRaisesRegex(PermissionError, "registration"):
            channel.receive(lambda: self.message(session, session.controller, 3, "start", 460))
        start.assert_not_called()
        self.assertFalse((Path(session.plan.directory) / "operator-start-intent.json").exists())

    def test_watchdog_transfer_requires_the_original_object(self):
        session, channel, start, _, _, arm = self.arming()
        changed = replace(arm.registration, transferred_watchdog=session.controller)
        with self.assertRaisesRegex(PermissionError, "registration"):
            channel.receive(lambda: self.message(session, session.supervisor, 1, "arm",
                                                 replace(arm, registration=changed)))
        with self.assertRaisesRegex(PermissionError, "registration"):
            channel.receive(lambda: self.message(session, session.controller, 3, "start", 460))
        start.assert_not_called()


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AdapterChecks)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    if result.wasSuccessful():
        print(f"COMPLETE gameplay operator adapter checks={result.testsRun}")
    raise SystemExit(0 if result.wasSuccessful() else 1)

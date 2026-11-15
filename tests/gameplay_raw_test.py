"""Exercise the owned raw seal and the public verifier entry without reading an ETL."""

from copy import deepcopy
from itertools import permutations
from contextlib import redirect_stdout
from dataclasses import asdict
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest import TestCase, main
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from gameplay_attribution import analyze, checked, reduce_span
from gameplay_budget import Budget, MIB
from gameplay_collector import MODE, PROFILE
from gameplay_process import digest
from gameplay_raw import (BOUNDARY_POLICY, NATIVE_SOURCE, describe, raw_slices, scheduler_window,
                          source_digest)
from gameplay_record import grant_fields, seal
import verify

IDENTITY = {"pid": 44, "creation": 2**57 + 9, "tid": 71, "qpf": 1000, "source": "a" * 40}


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def write_app(path, identity, mark_id, mark, start, end, history=False):
    rows = [f"frame 1 1 {start - 5} {start} {start} 0 0 5 0 0 0 0 0 0 0 0"] if history else []
    boundary = len(rows) + 1
    rows.append(f"frame {boundary} 1 {start} {end} {end} 0 0 5 0 0 0 0 0 0 0 0")
    lines = ["MCOSU_GAMEPLAY_QPC 1", f'source {identity["source"]}', "map " + "a" * 32,
             "identity " + " ".join(str(identity[key]) for key in ("pid", "creation", "tid", "qpf")),
             f"mark {mark_id} 1 {mark} {boundary}", "settings 1 1 0 0 1 121 0 120 0 0 100 2 0 0",
             "status recording", "post_end target", f"counts {boundary} {boundary} 0 0", "stages 0 0 0"]
    path.write_text("\n".join([*lines, *rows, "end complete"]) + "\n", encoding="ascii")


def fixture(root, identity, *, owns_app=True):
    session = str(uuid.uuid4())
    name = "McOsu-Controlled-" + session
    budget = asdict(Budget(report_mib=1))
    image = root / "game.exe"
    image.write_bytes(b"reviewed test image")
    etl = root / "fixture.etl"
    etl.write_bytes(b"inert placeholder")
    config = dict(session=session, budget=budget, image=str(image), image_sha256=digest(image),
                  identity=identity, owns_app=owns_app, baseline_mark=dict(id=1, qpc=2, folder_limit=4))
    config_path = root / "recording-config.json"
    write_json(config_path, config)
    grant = root / "recording-grant.json"
    write_json(grant, grant_fields(config_path, session))
    child = dict(session=session, pid=9, creation=2**57 + 15, entry_ms=10,
                 config_sha256=digest(config_path), grant_sha256=digest(grant))
    properties = dict(name=name, guid=session, file=str(etl), context=23, clock=1, mode=MODE, keywords=PROFILE,
                      file_mib=budget["etl_mib"], buffer_kib=64, minimum=128, maximum=128, number=128)
    active = dict(session=session, budget=budget, identity=identity, image_sha256=config["image_sha256"],
                  live_identity=dict(image=str(image), image_sha256=config["image_sha256"],
                                     **{k: identity[k] for k in ("pid", "creation", "tid", "qpf")}),
                  active_qpc=20, active_sample=dict(qpc=20, lost=0), active_properties=properties,
                  readiness=dict(mark=dict(id=2, qpc=11, epoch=1)))
    controller = dict(session=session, budget=budget, producer=child, controller_entry_ms=child["entry_ms"],
                      status="controller-reports-release", incomplete=False, stop=0, after_query=4201,
                      final_loss=0, watchdog_exit=0, active_qpc=20, stop_request_qpc=90,
                      active_properties=properties, active_sample=active["active_sample"], readiness=active["readiness"],
                      polls=[dict(qpc=70, lost=0), dict(qpc=80, lost=0)], etl_bytes=etl.stat().st_size)
    write_json(root / "child-identity.json", child)
    write_json(root / "observer.json", dict(child=child, pid=child["pid"], creation=child["creation"], wait=0, exit=0))
    write_json(root / "gameplay-active.json", active)
    write_json(root / "controller.json", controller)
    write_app(root / "readiness.qpc", identity, 2, 11, 10, 12)
    write_app(root / "gameplay.qpc", identity, 3, 27, 20, 35, history=True)
    query = root / "independent-query.json"
    write_json(query, dict(operation="ControlTraceW QUERY only", name=name, input_guid=session, status=4201,
                           trace_mutation=False, etl_read=False))
    write_json(root / "independent-absence.json", dict(session=session, name=name, input_guid=session, status=4201,
               remaining_owned_processes=[], observed_owned_pids=[child["pid"]] + ([identity["pid"]] if owns_app else []),
               app_target=dict(pid=identity["pid"], creation=identity["creation"], owned=owns_app),
               query_receipt_sha256=digest(query)))


def seal_fixture(root):
    bundle = root / "bundle.json"
    seal(root, root / "gameplay.qpc", root / "independent-absence.json", bundle,
         raw_query=root / "independent-query.json")
    return bundle


def event(tick, kind, detail=0, cpu=65537):
    return dict(Tick=tick, Kind=kind, Cpu=cpu, Detail=detail)


def payload(events):
    return dict(ProcessPair=True, ThreadPair=True, ClockMatches=True, Loss=False, InvalidLifecycle=False,
                InvalidScheduler=False, Overflow=False, ShapeOverflow=False, Candidates=len(events),
                V4Candidates=0, V4Checked=0, V4Schema=0, V4Corroborated=0, V4Accepted=0,
                HeaderClockType=1, HeaderQpf=1000, HeaderEventsLost=0, HeaderBuffersLost=0,
                RejectedSchedulerRecords=0, RejectedShapes=[], Events=events)


COMPLETE = "COMPLETE raw gameplay scheduler evidence"
INCONCLUSIVE = "INCONCLUSIVE raw gameplay scheduler evidence"
WITNESSES = [event(20, "I"), event(25, "O", 5), event(30, "R", 1), event(33, "I"), event(35, "O")]


class RawGameplayTests(TestCase):
    def test_explicit_cli_and_marked_frame_with_unknown_history(self):
        for identity in (IDENTITY, IDENTITY | dict(pid=885, tid=332, qpf=2000)):
            with self.subTest(pid=identity["pid"]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture(root, identity)
                bundle = seal_fixture(root)
                exe, grant, output = (root / n for n in ("raw.exe", "offline-grant.json", "output"))
                exe.write_bytes(b"inert reader")
                args = ["verify.py", "--gameplay", str(bundle), "--gameplay-raw-reader", str(exe), "--output", str(output)]
                captured = io.StringIO()
                with (patch.object(sys, "argv", [*args, "--describe-gameplay-raw-grant"]),
                      redirect_stdout(captured), patch("gameplay_attribution.checked", wraps=checked) as checks):
                    self.assertEqual(verify.main(), 0)
                    self.assertNotIn(root / "fixture.etl", [call.args[0] for call in checks.call_args_list])
                fields = json.loads(captured.getvalue())
                self.assertEqual(fields["budget"]["report_mib"], 1)
                self.assertFalse(output.exists())
                write_json(grant, fields)

                def run(argv, _cwd, _env, timeout, stdout, stderr, *, memory_limit, stream_limit):
                    self.assertEqual(argv[0], exe)
                    self.assertEqual(argv[2:9], [str(identity[k]) for k in ("pid", "tid", "qpf")] + ["20", "80", "20", "70"])
                    self.assertEqual((timeout, memory_limit, stream_limit), (15, 1024 * MIB, MIB - 65536))
                    stdout.write_text(json.dumps(payload(WITNESSES) | {"HeaderQpf": identity["qpf"]}) + "\n" + COMPLETE)
                    stderr.touch()
                    return dict(exit=0, timeout=False, error=None, owned_process_remaining=False, stream_truncated=False)

                with patch("gameplay_attribution.execute", side_effect=run) as owned, patch.object(
                        sys, "argv", [*args, "--gameplay-raw-grant", str(grant)]):
                    self.assertEqual(verify.main(), 3)
                    owned.assert_called_once()
                    with self.assertRaises(FileExistsError):
                        analyze(bundle, exe, None, output, raw_grant=grant)
                report = json.loads((output / "summary.json").read_bytes())
                self.assertEqual(report["status"], "inconclusive")
                self.assertEqual(report["marked_frame"]["status"], "complete")
                self.assertEqual(report["marked_frame"]["ticks"], dict(running=7, waiting=5, ready=3, unknown=0))
                self.assertNotIn("Events", report["decoder"])
                self.assertLessEqual(sum(path.stat().st_size for path in output.iterdir()), MIB)

    def test_swapped_or_tampered_chain_refuses_before_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("a", "b"):
                folder = root / name
                folder.mkdir()
                fixture(folder, IDENTITY)
                seal_fixture(folder)
            reader = root / "raw.exe"
            reader.write_bytes(b"reader")
            a, b = root / "a/bundle.json", root / "b/bundle.json"
            grant = root / "grant.json"
            output = root / "output"
            write_json(grant, describe(a, reader, output))
            with patch("gameplay_attribution.execute") as run:
                with self.assertRaises(PermissionError):
                    analyze(b, reader, None, output, raw_grant=grant)
                for filename in ("gameplay-active.json", "recording-grant.json", "independent-query.json", "readiness.qpc"):
                    path = b.with_name(filename)
                    old = path.read_bytes()
                    path.write_bytes(old + b"tampered")
                    with self.assertRaises(ValueError):
                        describe(b, reader, output)
                    path.write_bytes(old)
                run.assert_not_called()
            self.assertFalse(output.exists())
            with patch("gameplay_attribution.execute") as run:
                etl = a.with_name("fixture.etl")
                etl.write_bytes(b"X" + etl.read_bytes()[1:])
                with self.assertRaises(ValueError):
                    analyze(a, reader, None, output, raw_grant=grant)
                run.assert_not_called()

    def test_sealer_rejects_coherent_files_with_invalid_live_evidence(self):
        for edit in ("short-polls", "live-tid", "loss", "wrong-query"):
            with self.subTest(edit=edit), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture(root, IDENTITY)
                controller = root / "controller.json"
                final = json.loads(controller.read_bytes())
                if edit == "short-polls":
                    final["polls"].pop()
                elif edit == "loss":
                    final["polls"][0]["lost"] = 1
                elif edit == "live-tid":
                    active = root / "gameplay-active.json"
                    initial = json.loads(active.read_bytes())
                    initial["live_identity"]["tid"] += 1
                    write_json(active, initial)
                else:
                    query = root / "independent-query.json"
                    write_json(query, json.loads(query.read_bytes()) | {"input_guid": str(uuid.uuid4())})
                    absence = root / "independent-absence.json"
                    write_json(absence, json.loads(absence.read_bytes()) | {"query_receipt_sha256": digest(query)})
                write_json(controller, final)
                with self.assertRaises(ValueError):
                    seal_fixture(root)
                self.assertFalse((root / "bundle.json").exists())

    def test_independent_release_allows_player_app_to_keep_running(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # The target is still live according to the independent witness.
            # Only the recorder's controller belongs to the owned set.
            fixture(root, IDENTITY, owns_app=False)
            absence = root / "independent-absence.json"
            record = json.loads(absence.read_bytes())
            write_json(absence, record | {"observed_live_pids": [IDENTITY["pid"]]})
            self.assertTrue(seal_fixture(root).is_file())

    def test_independent_release_rejects_missing_or_misassigned_owned_processes(self):
        for change in ("controller-alive", "controller-omitted", "owned-app-omitted", "nonowned-app-listed",
                       "forged-target-creation", "forged-target-pid", "ambiguous-role", "forged-role-and-owned-set"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture(root, IDENTITY)
                path = root / "independent-absence.json"
                absence = json.loads(path.read_bytes())
                controller = next(pid for pid in absence["observed_owned_pids"] if pid != IDENTITY["pid"])
                if change == "controller-alive":
                    absence["remaining_owned_processes"] = [controller]
                elif change == "controller-omitted":
                    absence["observed_owned_pids"].remove(controller)
                elif change == "owned-app-omitted":
                    absence["observed_owned_pids"].remove(IDENTITY["pid"])
                elif change == "nonowned-app-listed":
                    absence["app_target"]["owned"] = False
                elif change == "forged-target-creation":
                    absence["app_target"]["creation"] += 1
                elif change == "forged-target-pid":
                    absence["app_target"]["pid"] = controller
                elif change == "forged-role-and-owned-set":
                    absence["app_target"]["owned"] = False
                    absence["observed_owned_pids"].remove(IDENTITY["pid"])
                else:
                    absence["app_target"]["owned"] = 1
                write_json(path, absence)
                with self.assertRaises(ValueError):
                    seal_fixture(root)
                self.assertFalse((root / "bundle.json").exists())

    def test_scheduler_ties_cpu_loss_and_caps(self):
        request = dict(Active=20, LiveUpper=70, Qpf=1000, EventLimit=5, SliceLimit=8)
        with self.assertRaises(ValueError):
            raw_slices(payload(WITNESSES), request | {"EventLimit": 4}, 0, COMPLETE)
        self.assertFalse(raw_slices(payload(WITNESSES), request | {"SliceLimit": 2}, 0, COMPLETE)[0])
        ok, spans, diag = raw_slices(payload([*WITNESSES[:2], event(25, "R")]), request, 0, COMPLETE)
        self.assertTrue(ok)
        self.assertFalse(spans)
        self.assertEqual(diag["TiedEvents"], 2)
        self.assertFalse(raw_slices(payload([]) | {"Loss": True}, request, 3, INCONCLUSIVE)[0])
        custom = deepcopy(WITNESSES)
        custom[1]["Cpu"] = 1
        ok, spans, _ = raw_slices(payload(custom), request, 0, COMPLETE)
        self.assertTrue(ok)
        self.assertEqual(reduce_span(20, 35, spans)["ticks"]["unknown"], 5)
        custom[1]["Detail"] = 0x81
        ok, spans, _ = raw_slices(payload(custom), request, 0, COMPLETE)
        self.assertTrue(ok)
        self.assertEqual(reduce_span(20, 35, spans)["ticks"]["unknown"], 13)


    def test_tied_groups_are_uninterpreted_barriers(self):
        request = dict(Active=10, LiveUpper=100, SchedulerLower=20, SchedulerUpperInclusive=60,
                       Qpf=1000, EventLimit=20, SliceLimit=20)
        group = [event(30, "O", 7), event(30, "R", 0, cpu=65541), event(30, "I")]
        boundary_group = [event(60, "O", 5), event(60, "I")]
        before = [event(20, "I"), event(22, "O", 5), event(24, "R", 1)]
        after = [event(31, "R", 1), event(35, "I"), event(38, "O", 5),
                 event(42, "R", 0), event(45, "I")]
        first = None
        for permutation in permutations(group):
            events = [*before, *permutation, *after, *boundary_group]
            report = payload(events)
            original = deepcopy(report)
            usable, spans, diag = raw_slices(report, request, 0, COMPLETE)
            self.assertTrue(usable)
            self.assertEqual(report, original)
            self.assertEqual((diag["TiedGroups"], diag["TiedEvents"]), (2, 5))
            self.assertEqual([(span["start"], span["end"]) for span in spans],
                             [(20, 22), (35, 38), (38, 42), (42, 45)])
            self.assertEqual(reduce_span(20, 61, spans)["ticks"],
                             dict(running=5, waiting=4, ready=3, unknown=29))
            if first is None:
                first = spans
            self.assertEqual(spans, first)

        for bad in ([*before, *group, event(29, "I")],
                    [*before, *group, event(30, "I", 1)],
                    [*before, *group, event(61, "I")],
                    [event(19, "I"), *before, *group]):
            self.assertFalse(raw_slices(payload(bad), request, 0, COMPLETE)[0])
        self.assertFalse(raw_slices(payload([*before, *group, *after]),
                                   request | {"SliceLimit": 1}, 0, COMPLETE)[0])
        for pending in ([], [event(42, "R", 0), event(43, "R", 1)], [event(42, "R", 7)]):
            events = [*group, *after[:3], *pending, after[-1]]
            _, spans, _ = raw_slices(payload(events), request, 0, COMPLETE)
            self.assertEqual(reduce_span(38, 45, spans)["ticks"]["unknown"], 7)

    def test_window_options_derive_bounds_and_preserve_lifecycle(self):
        app = dict(rows=[dict(start=13, end=17), dict(start=40, end=60)])
        self.assertEqual(scheduler_window(app, 1000, 20, 80, "whole", None)["inclusive_qpc"], [20, 80])
        retained = scheduler_window(app, 1501, 20, 80, "retained", 1)
        self.assertEqual(retained["retained_app_qpc"], [13, 60])
        self.assertEqual(retained["inclusive_qpc"], [20, 61])
        self.assertEqual(retained["lookaround_ticks"], 2)
        self.assertEqual(scheduler_window(app, 1000, 20, 80, "retained", None)["inclusive_qpc"], [20, 79])
        self.assertEqual(scheduler_window(app, 1000, 20, 80, "retained", 0)["inclusive_qpc"], [20, 59])
        for mode, value in (("whole", 0), ("unknown", None), ("retained", True),
                            ("retained", -1), ("retained", 5001)):
            with self.assertRaises(ValueError):
                scheduler_window(app, 1000, 20, 80, mode, value)

    def test_tie_samples_saturate_without_discarding_groups(self):
        request = dict(Active=20, LiveUpper=60, Qpf=1000, EventLimit=40, SliceLimit=20)
        rows = [event(tick, "I") for tick in range(20, 40) for _ in range(2)]
        ok, spans, diag = raw_slices(payload(rows), request, 0, COMPLETE)
        self.assertTrue(ok)
        self.assertFalse(spans)
        self.assertEqual((diag["TiedGroups"], diag["TiedEvents"], diag["LargestTiedGroup"]), (20, 40, 2))
        self.assertEqual(diag["TiedGroupSamples"][0], dict(index=0, tick=20, count=2))
        self.assertEqual(len(diag["TiedGroupSamples"]), 16)
        self.assertTrue(diag["TiedSamplesSaturated"])

    def test_retained_cli_grant_binds_selected_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root, IDENTITY)
            bundle = seal_fixture(root)
            exe, grant, output = (root / name for name in ("raw.exe", "grant.json", "out"))
            exe.write_bytes(b"inert reader")
            args = ["verify.py", "--gameplay", str(bundle), "--gameplay-raw-reader", str(exe), "--output", str(output),
                    "--gameplay-raw-window", "retained", "--gameplay-raw-lookaround-ms", "1"]
            printed = io.StringIO()
            with patch.object(sys, "argv", [*args, "--describe-gameplay-raw-grant"]), redirect_stdout(printed):
                self.assertEqual(verify.main(), 0)
            fields = json.loads(printed.getvalue())
            self.assertEqual(fields["consumer"]["window"]["inclusive_qpc"], [20, 35])
            self.assertEqual(fields["consumer"]["following_poll_qpc"], 80)
            self.assertNotIn("lookaround_ms", fields["budget"])
            write_json(grant, fields)
            with patch("gameplay_attribution.execute") as owned:
                with self.assertRaises(PermissionError):
                    analyze(bundle, exe, None, output, raw_grant=grant,
                            raw_options={"mode": "retained", "lookaround_ms": 2})
                owned.assert_not_called()
            self.assertFalse(output.exists())
            forged = deepcopy(fields)
            forged["consumer"]["requested_lookaround_ms"] = True
            write_json(grant, forged)
            with patch("gameplay_attribution.execute") as owned:
                with self.assertRaises(PermissionError):
                    analyze(bundle, exe, None, output, raw_grant=grant,
                            raw_options={"mode": "retained", "lookaround_ms": 1})
                owned.assert_not_called()
            write_json(grant, fields)

            def run(argv, _cwd, _env, _timeout, stdout, stderr, **_limits):
                self.assertEqual(argv[5:9], ["20", "80", "20", "35"])
                stdout.write_text(json.dumps(payload(WITNESSES)) + "\n" + COMPLETE)
                stderr.touch()
                return dict(exit=0, timeout=False, error=None, owned_process_remaining=False, stream_truncated=False)

            with patch("gameplay_attribution.execute", side_effect=run), patch.object(
                    sys, "argv", [*args, "--gameplay-raw-grant", str(grant)]):
                self.assertEqual(verify.main(), 3)
            summary = json.loads((output / "summary.json").read_bytes())
            self.assertEqual(summary["consumer"], fields["consumer"])
            self.assertEqual(summary["observed_slice_span"], [20, 35])
            self.assertEqual(summary["coverage"], dict(written_frames=2, frames_with_unknown=1, unknown_ticks=5))
            self.assertEqual(summary["marked_frame"]["status"], "complete")


    def test_reviewed_pair_binds_sources_schema_and_exact_grant(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root, IDENTITY)
            bundle = seal_fixture(root)
            reader, manifest, grant, output = (root / name for name in ("raw.exe", "pair.json", "grant.json", "out"))
            reader.write_bytes(b"inert reader")
            consumer = Path(verify.__file__).parent / "gameplay_raw.py"
            reviewed = dict(version=1, wire_schema=2, ambiguity_policy=BOUNDARY_POLICY,
                            reader_sha256=digest(reader),
                            native_source_sha256=source_digest(consumer.parent / NATIVE_SOURCE),
                            consumer_source_sha256=source_digest(consumer), compile_receipt_sha256="a"*64)
            for key, invalid in (("version", True), ("wire_schema", 2.0), ("reader_sha256", "b"*64),
                                 ("native_source_sha256", "b"*64), ("consumer_source_sha256", "b"*64),
                                 ("compile_receipt_sha256", ""), ("ambiguity_policy", "ignore")):
                write_json(manifest, reviewed | {key: invalid})
                with self.assertRaises(ValueError):
                    describe(bundle, reader, output, pair_manifest=manifest)
            manifest.write_bytes(b" " * 8193)
            with self.assertRaises(ValueError):
                describe(bundle, reader, output, pair_manifest=manifest)
            write_json(manifest, reviewed)
            args = ["verify.py", "--gameplay", str(bundle), "--gameplay-raw-reader", str(reader),
                    "--gameplay-raw-reader-pair", str(manifest), "--output", str(output)]
            printed = io.StringIO()
            with patch.object(sys, "argv", [*args, "--describe-gameplay-raw-grant"]), redirect_stdout(printed):
                self.assertEqual(verify.main(), 0)
            allowed = json.loads(printed.getvalue())
            self.assertEqual(allowed["reader_pair"]["manifest_sha256"], digest(manifest))
            self.assertEqual(allowed["consumer"]["ambiguity_policy"], BOUNDARY_POLICY)
            write_json(grant, allowed)
            # Even a semantically identical manifest with changed bytes needs a new grant.
            manifest.write_bytes(manifest.read_bytes() + b"\n")
            with patch("gameplay_attribution.execute") as owned:
                for options in ({"pair_manifest": manifest}, {}):
                    with self.assertRaises(PermissionError):
                        analyze(bundle, reader, None, output, raw_grant=grant, raw_options=options)
                owned.assert_not_called()
            write_json(manifest, reviewed)

            def run(_argv, _cwd, _env, _timeout, stdout, stderr, **_limits):
                report = payload(WITNESSES) | dict(WireSchema=2, BoundaryRecords=0)
                stdout.write_text(json.dumps(report) + "\n" + COMPLETE)
                stderr.touch()
                return dict(exit=0, timeout=False, error=None, owned_process_remaining=False, stream_truncated=False)

            with patch("gameplay_attribution.execute", side_effect=run), patch.object(
                    sys, "argv", [*args, "--gameplay-raw-grant", str(grant)]):
                self.assertEqual(verify.main(), 3)
            summary = json.loads((output / "summary.json").read_bytes())
            self.assertEqual(summary["reader_pair"], allowed["reader_pair"])
            self.assertEqual(summary["consumer"]["ambiguity_policy"], BOUNDARY_POLICY)
            self.assertEqual(summary["reader_pair"]["reader_sha256"], digest(reader))
            self.assertEqual(summary["marked_frame"]["status"], "complete")

    def test_legacy_rejects_unrequested_v2_and_pair_rejects_malformed_boundary(self):
        request = dict(Active=20, LiveUpper=70, Qpf=1000, EventLimit=8, SliceLimit=12)
        v2_without_boundaries = payload(WITNESSES) | dict(WireSchema=2, BoundaryRecords=0)
        with self.assertRaisesRegex(ValueError, "not requested"):
            raw_slices(v2_without_boundaries, request, 0, COMPLETE)
        with self.assertRaisesRegex(ValueError, "wire schema"):
            raw_slices(payload(WITNESSES), request, 0, COMPLETE, expected_schema=2)
        with self.assertRaisesRegex(ValueError, "boundary"):
            raw_slices(payload([event(24, "B", 3)]) | dict(WireSchema=2, BoundaryRecords=0),
                       request, 0, COMPLETE, expected_schema=2)
        events = [event(20, "I"), event(24, "B", 2), event(24, "R", 1), event(30, "I"), event(33, "O")]
        values = payload(events) | dict(WireSchema=2, BoundaryRecords=1, V4Candidates=1, V4Checked=1,
                                      V4Schema=1, V4Corroborated=1, V4Accepted=1)
        ok, spans, diag = raw_slices(values, request, 0, COMPLETE, expected_schema=2)
        self.assertTrue(ok)
        self.assertEqual(diag["TiedGroups"], 1)
        self.assertEqual(diag["BoundaryGroups"], 1)
        self.assertEqual(diag["BarrierGroups"], 1)
        self.assertEqual(reduce_span(20, 33, spans)["ticks"], dict(running=3, waiting=0, ready=0, unknown=10))


if __name__ == "__main__":
    main()

"""Pure gameplay policy and reducer regression cases. No ETL or native calls."""

from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
import sys
import tempfile
from io import BytesIO
import json
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from gameplay_budget import Budget, MIB, poll_decision, trace_pressure
from gameplay_collector import MODE, PROFILE, collect
from gameplay_attribution import analyze, read_app, reduce_span
from gameplay_process import StreamBudget
from gameplay_record import WindowsAdapter, collection_summary, open_app_thread, ready_mark

SESSION = "f9d206fc-7e8d-44ec-b3eb-f4b77d4c8a91"


def sample(ms, written=1, **values):
    return dict(ms=ms, qpc=ms * 10000, written=written, file_bytes=written * 65536,
                output_free=2**31, system_free=2**31, lost=0) | values


class Adapter:
    def __init__(self, fault=None):
        self.ms = 1000
        self.fault = fault
        self.released = False

    def prepare(self, session, path, budget):
        return SimpleNamespace(session=session, path=path, budget=budget, restored=False, handle=0)

    def free_space(self):
        return (2**31, 2**31)

    def await_ready(self, latest, budget):
        self.waited = True
        if self.fault == "no-ready":
            return 100, None, None
        return 100, 250, dict(id=2, qpc=2000000)

    def arm(self, attempt, latest, budget):
        if not self.waited:
            raise ValueError("Arm preceded readiness")
        self.armed = True
        return 1000

    def start_scoped(self, attempt, latest):
        self.started = True
        if self.fault == "start":
            raise ValueError("Start failed")
        attempt.handle = 37
        if self.fault == "restore":
            raise ValueError("restore")
        attempt.restored = True

    def observe(self, attempt):
        return dict(name="McOsu-Controlled-" + attempt.session, guid=attempt.session, file=str(attempt.path),
                    context=37, clock=1, mode=MODE, keywords=PROFILE, file_mib=attempt.budget.etl_mib,
                    buffer_kib=64, minimum=128, maximum=128, number=128), sample(
                        self.ms, lost=int(self.fault == "loss" and self.ms > 1000))

    def active_receipt(self, result):
        self.active = result["active_qpc"]

    def wait_until(self, when):
        self.ms = when

    def qpc(self):
        if self.fault == "stop-clock":
            raise ValueError("clock")
        return self.ms * 10000

    def stop_clock(self):
        return self.qpc(), self.ms + (1 if self.fault == "late-stop" else 0)

    def release(self, attempt):
        self.released = True
        if not attempt.handle:
            return dict(start_invoked=False)
        if self.fault == "cleanup":
            return dict(stop=5, after_query=0, watchdog_exit=1)
        return dict(stop=0, after_query=4201, watchdog_exit=0, etl_bytes=65536, final_loss=0)


class GameplayTests(TestCase):
    def test_thread_rights_and_mismatched_handle_closed(self):
        calls = []
        abi = SimpleNamespace(
            OpenThread=lambda access, inherit, tid: calls.append((access, inherit, tid)) or 7,
            GetProcessIdOfThread=lambda handle: 12 if calls[-1][0] & 0x0840 else 0,
            CloseHandle=lambda handle: calls.append(handle))
        self.assertEqual(open_app_thread(abi, 13, 12), 7)
        self.assertEqual(calls[-1], (0x100800, False, 13))
        with self.assertRaises(ValueError):
            open_app_thread(abi, 13, 99)
        self.assertEqual(calls[-1], 7)

    def test_shared_stream_limit_enforced_during_writes(self):
        output, errors = BytesIO(), BytesIO()
        budget = StreamBudget(10)
        budget.drain(BytesIO(b"a" * 7), output)
        budget.drain(BytesIO(b"b" * 8), errors)
        self.assertEqual((output.getvalue(), errors.getvalue()), (b"a" * 7, b"b" * 3))
        self.assertTrue(budget.exhausted)
        self.assertEqual(budget.remaining, 0)

    def test_analysis_retains_one_report_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reader = root / "Reader.dll"
            for path in (reader, reader.with_suffix(".deps.json"), reader.with_suffix(".runtimeconfig.json")):
                path.touch()
            app = dict(pid=1, tid=2, creation=3, qpf=10, source="a"*40, map="unknown", rows=[
                dict(sequence=1, start=10, end=11, context=0, scopes=[]),
            ], settings=[], mark=10, mark_id=1, epoch=1, boundary=1, status="recording",
                post_end="target", stages=[], observed=1, evicted=0, partial=False)
            release = dict(active_qpc=0, stop_request_qpc=20, identity={}, image_sha256="a"*64)
            bundle = dict(session=SESSION, etl_sha256="a"*64, budget={"report_mib": 1})

            def fake(_argv, _cwd, _env, _timeout, stdout, stderr, *, memory_limit, stream_limit):
                self.assertEqual(memory_limit, 1024 * MIB)
                if stdout.parent.name == "stream-overflow":
                    stream = StreamBudget(stream_limit)
                    with stdout.open("wb") as f:
                        stream.drain(BytesIO(b"x" * (MIB + 1)), f)
                    stderr.touch()
                    return dict(exit=0, timeout=False, error=None, owned_process_remaining=False, stream_truncated=stream.exhausted)
                evidence = dict(Usable=True, Lower=0, Upper=20, Slices=[])
                body = json.dumps(evidence).encode()
                suffix = b"\nCOMPLETE gameplay scheduler evidence\n"
                stdout.write_bytes(body + b" " * (stream_limit - len(body) - len(suffix) - 1) + suffix)
                stderr.touch()
                return dict(exit=0, timeout=False, error=None, owned_process_remaining=False, stream_truncated=False)

            with patch("gameplay_attribution.load_bundle", return_value=(bundle, Budget.parse(bundle["budget"]), root, release, app)):
                with patch("gameplay_attribution.execute", side_effect=fake):
                    for name in ("stream-overflow", "frame-overflow"):
                        out = root / name
                        self.assertEqual(analyze(root, reader, sys.executable, out), 3)
                        self.assertLessEqual(sum(p.stat().st_size for p in out.iterdir()), MIB)
                        result = json.loads((out / "summary.json").read_text())
                        self.assertEqual(result["status"], "inconclusive")
                        if name == "frame-overflow":
                            self.assertTrue(result["output_truncated"])

    def test_hard_ceiling_and_stop_clock(self):
        budget = Budget.parse({"target_ms": 1000, "max_ms": 1000})
        ledger = budget.ledger(0, 100, 250, 1000, 1000)
        self.assertEqual(poll_decision(budget, ledger, sample(1750), sample(2000)), "target")
        self.assertEqual(poll_decision(budget, ledger, sample(1750), sample(2250)), "hard-deadline")
        with tempfile.TemporaryDirectory() as folder:
            api = Adapter("late-stop")
            result = collect(api, budget, SESSION, Path(folder) / "capture.etl", 0)
            self.assertTrue(api.released)
            self.assertTrue(result["incomplete"])
            self.assertEqual(result["stop_reason"], "hard-deadline")

    def test_limits_and_ledger(self):
        budget = Budget.parse({})
        ledger = budget.ledger(10, 110, 44110, 49009, 52009)
        self.assertEqual(ledger["stop_request_ms"], 72009)
        self.assertEqual(ledger["watchdog_ms"], 83009)
        self.assertEqual(ledger["setup_deadline_ms"], 49010)
        self.assertEqual(ledger["readiness_deadline_ms"], 45110)
        for values in ({"poll_ms": False}, {"wat": 5}, {"watchdog_ms": 33999}, {"observer_ms": 87999},
                       {"readiness_ms": 47001}, {"forecast_window_ms": 249}, {"etl_mib": 199},
                       {"live_free_mib": 511}, {"analysis_memory_mib": 1}, {"max_ms": 30001}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Budget.parse(values)
        for timestamps in ((10, 5010, 5010, 5010, 8010), (10, 110, 45110, 45110, 45110),
                           (10, 110, 44110, 49010, 52010), (10, 110, 44110, 49009, 52010)):
            with self.assertRaises(ValueError):
                budget.ledger(*timestamps)

    def test_poll_stop_reasons(self):
        budget = Budget.parse({})
        ledger = budget.ledger(0, 100, 250, 1000, 1000)
        previous = sample(1000)
        for current, reason in [
            (sample(1250), None), (sample(1501), "missed-poll"), (sample(1250, 0), "decreasing-counter"),
            (sample(1250, lost=1), "reported-loss"), (sample(1250, system_free=640*MIB-1), "low-space"),
            (sample(1250, 100), None), (sample(1250, file_bytes=-1), "invalid-counter"),
            (sample(1250, 1920), "trace-budget-observed"),
            (sample(1250, 1919), None),
        ]:
            with self.subTest(reason=reason):
                self.assertEqual(poll_decision(budget, ledger, previous, current), reason)

    def test_forecast_uses_window_and_short_horizon(self):
        budget = Budget.parse({})
        ledger = budget.ledger(0, 100, 250, 1000, 1000)
        origin, previous = sample(1000, 0), sample(1750, 480)
        current = sample(2000, 640)
        self.assertEqual(trace_pressure(budget, ledger, current, origin)["projected_bytes"], 128*MIB)
        self.assertEqual(poll_decision(budget, ledger, previous, current, origin), "trace-budget-forecast")
        self.assertIsNone(poll_decision(budget, ledger, previous, current, sample(1001, 0)))
        plateau = sample(2000, 640)
        self.assertIsNone(poll_decision(budget, ledger, sample(1750, 640), plateau, sample(1000, 640)))
        self.assertEqual(trace_pressure(budget, ledger, plateau, sample(1000, 640))["projected_bytes"], 48*MIB)
        short = ledger | {"stop_request_ms": 2250}
        self.assertEqual(trace_pressure(budget, short, current, origin)["projected_bytes"], 58*MIB)
        self.assertIsNone(poll_decision(budget, short, previous, current, origin))

    def test_recorded_polls_fit_new_lookahead(self):
        # Offsets and written buffers from the consumed trial's controller receipt.
        offsets = (0, 251, 503, 754, 1005, 1256, 1507, 1759, 2010)
        counts = (89, 105, 119, 130, 147, 162, 181, 204, 231)
        free = (20167598080, 20167598080, 20166549504, 20165500928, 20164452352,
                20163403776, 20162387968, 20161331200, 20159234048)
        samples = [sample(1000 + ms, written, output_free=room, system_free=room)
                   for ms, written, room in zip(offsets, counts, free)]
        ledger = Budget().ledger(0, 100, 250, 1000, 1000)
        previous, last = samples[-2:]
        self.assertEqual(last["file_bytes"] + 1769472 * 17990 // 251 + 8*MIB, 150351333)
        for index, current in enumerate(samples[1:], 1):
            origin = next((point for point in reversed(samples[:index]) if current["ms"] - point["ms"] >= 1000), None)
            self.assertIsNone(poll_decision(Budget(), ledger, samples[index-1], current, origin))
        self.assertEqual(trace_pressure(Budget(), ledger, last, samples[4])["projected_bytes"], 34482695)

    def test_collect_keeps_release_on_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "capture.etl"
            for fault in (None, "no-ready", "start", "restore", "loss", "cleanup", "stop-clock"):
                with self.subTest(fault=fault):
                    api = Adapter(fault)
                    result = collect(api, Budget.parse({}), SESSION, path, 0)
                    self.assertTrue(api.released)
                    self.assertEqual(result["incomplete"], fault is not None)
                    if fault == "cleanup":
                        self.assertEqual(result["status"], "pending-cleanup")
                    if fault in ("restore", "start", "no-ready"):
                        self.assertFalse(hasattr(api, "active"))
                    if fault == "no-ready":
                        self.assertEqual(result["stop_reason"], "readiness-timeout")
                        self.assertFalse(hasattr(api, "armed"))
                        self.assertFalse(hasattr(api, "started"))
                    if fault == "start":
                        self.assertEqual(result["stop_reason"], "start-failed")

    def test_ready_mark_requires_new_complete_focused_gameplay(self):
        spec = dict(identity=dict(pid=12, tid=13, creation=99, qpf=10000000, source="a"*40),
                    baseline_mark=dict(id=1, qpc=90, folder_limit=12))

        def sidecar(pid=12, created=99, tid=13, qpf=10000000, source="a"*40, mark_id=2,
                    tick=110, context=13, end="complete", map_id="b"*32):
            return (f"MCOSU_GAMEPLAY_QPC 1\nsource {source}\nmap {map_id}\nidentity {pid} {created} {tid} {qpf}\n"
                    f"mark {mark_id} 1 {tick} 1\nsettings 1 1 1 1 4 4217 1024 1024 0 0 2000 12 0 0\n"
                    "status recording\npost_end target\ncounts 1 1 0 0\nstages -1 -1 -1\n"
                    f"frame 1 1 90 120 100 0 0 {context} -1 -1 -1 -1 -1 -1 -1 -1\nend {end}\n")

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            mark_folder = root / "mark-123-00"
            mark_folder.mkdir()
            marked = mark_folder / "gameplay.qpc"
            marked.with_suffix(".qpc.partial").write_text(sidecar(), encoding="ascii")
            checked_paths = set()
            self.assertIsNone(ready_mark(root, spec, 100, checked_paths))
            self.assertFalse(checked_paths)
            marked.write_text(sidecar(), encoding="ascii")
            self.assertIsNone(ready_mark(root, spec, 100, checked_paths))
            self.assertFalse(checked_paths)
            marked.with_name("export.txt").write_bytes(b"gameplay_qpc=saved\n")
            for values in ({"tick": 100}, {"pid": 14}, {"created": 100}, {"tid": 14}, {"qpf": 9},
                           {"source": "c"*40}, {"mark_id": 1}, {"context": 4}, {"context": 7},
                           {"context": 21}, {"end": "partial"}, {"map_id": "unknown"}):
                with self.subTest(values=values):
                    marked.write_text(sidecar(**values), encoding="ascii")
                    self.assertIsNone(ready_mark(root, spec, 100, set()))
            marked.write_text(sidecar(), encoding="ascii")
            self.assertEqual(ready_mark(root, spec, 100, checked_paths),
                             dict(id=2, qpc=110, epoch=1, folder=mark_folder.name))

    def test_readiness_wait_uses_actual_adapter_without_native_start(self):
        budget = Budget.parse({"readiness_ms": 1000})
        for available in (False, True):
            with self.subTest(available=available), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                now = [200]
                mark = dict(id=2, qpc=2200000)
                spec = dict(session=SESSION, identity={}, baseline_mark=dict(folder_limit=12))
                adapter = WindowsAdapter(None, spec, root / "game.exe", root, [])
                adapter.require_game = lambda: None
                adapter.free_space = lambda: (2**31, 2**31)
                adapter.wait_until = lambda when: now.__setitem__(0, when)
                adapter.stop_clock = lambda: (now[0]*10000, now[0])
                with patch("gameplay_record.now_ms", side_effect=lambda: now[0]), patch(
                    "gameplay_record.ready_mark", side_effect=lambda *args: mark if available and now[0] >= 450 else None
                ):
                    self.assertEqual(adapter.await_ready(1000, budget), (200, 450, mark) if available else (200, None, None))
                notice = json.loads((root / "gameplay-waiting.json").read_text())
                self.assertEqual((notice["origin_qpc"], notice["deadline_ms"]), (2000000, 1200))
                self.assertIsNone(adapter.watcher)

    def test_terminal_readout(self):
        controller = dict(stop_reason="trace-budget-forecast", active_qpc=187225934850,
                          stop_request_qpc=187246040572, status="controller-reports-release", incomplete=True,
                          etl_bytes=21823488, trace_pressure=dict(occupied_bytes=23*MIB, projected_bytes=129*MIB,
                                                               early_bytes=128*MIB))
        text = collection_summary(controller, dict(exit=3), 10000000)
        for phrase in ("INCOMPLETE", "partial trace", "forecast", "2.011 s", "projected 129.0 MiB",
                       "independent release verification"):
            self.assertIn(phrase, text)
        text = collection_summary(dict(stop_reason="readiness-timeout", start_invoked=False), dict(exit=3), 10000000)
        for phrase in ("readiness", "did not become active", "never invoked"):
            self.assertIn(phrase, text)
        self.assertIn("free space", collection_summary(controller | dict(stop_reason="low-space"), dict(exit=3), 10000000))

    def test_clip_unknown_and_overlap(self):
        running = dict(start=7, end=15, state="running")
        ready = dict(start=18, end=30, state="ready")
        result = reduce_span(10, 25, [running, ready])
        self.assertEqual(result["ticks"], dict(running=5, waiting=0, ready=7, unknown=3))
        self.assertEqual(result["slices"][1]["clipped_end"], 25)
        with self.assertRaises(ValueError):
            reduce_span(10, 25, [running, dict(start=14, end=20, state="waiting")])

    def test_sidecar_lossless_mark_and_scope(self):
        tick = 2**53 + 101
        data = (
            f"MCOSU_GAMEPLAY_QPC 1\nsource {'a'*40}\nmap unknown\nidentity 12 134390657678403386 13 10000000\n"
            f"mark 1 4 {tick+10} 2\nsettings 1 1 1 1 4 4217 1024 1024 0 0 2000 12 0 0\n"
            f"status recording\npost_end target\ncounts 2 2 0 0\nstages {tick+11} -1 -1\n"
            f"frame 1 4 {tick} {tick+10} {tick+2} 0 0 4 -1 -1 -1 -1 -1 -1 -1 -1\n"
            f"frame 2 4 {tick+10} {tick+20} {tick+12} 1 1 4 {tick+13} {tick+17} -1 -1 -1 -1 -1 -1\nend complete\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "gameplay.qpc"
            path.write_text(data, encoding="ascii")
            result = read_app(path)
            self.assertEqual(result["mark"], tick + 10)
            self.assertEqual(result["boundary"], 2)
            self.assertEqual(result["rows"][1]["scopes"][1], ("draw-1", tick + 13, tick + 17))
            path.write_text(data.replace(f"mark 1 4 {tick+10} 2", f"mark 1 4 {tick+10} 1"), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "Mark boundary"):
                read_app(path)


if __name__ == "__main__":
    main()

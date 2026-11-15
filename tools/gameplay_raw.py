"""Admit raw scheduler evidence from an owned recording and reduce its witnesses."""

from dataclasses import asdict
from itertools import groupby
import hashlib
import json
from pathlib import Path

from gameplay_attribution import APP_LIMIT, REPORT_METADATA_BYTES, SHA, checked, load_bundle, local_artifact, read_app, read_json
from gameplay_budget import Budget, MIB
from gameplay_process import digest

META = 64 * 1024
PROOF_FILES = {
    "recording-config.json": META,
    "recording-grant.json": META,
    "child-identity.json": META,
    "observer.json": META,
    "gameplay-active.json": META,
    "controller.json": MIB,
    "readiness.qpc": APP_LIMIT,
    "independent-absence.json": META,
    "independent-query.json": META,
}
MAX_EVENTS = 131072
# The compact native event row is at most 75 ASCII bytes including its comma.
# Reserve an additional 8 KiB for diagnostics and the result marker.
EVENT_ROW_BYTES = 75
RAW_METADATA_BYTES = 8192


TIE_SAMPLE_LIMIT = 16
AMBIGUITY_POLICY = "equal-qpc-barrier-v1"
WIRE_SCHEMA = 2
BOUNDARY_POLICY = "equal-qpc-or-validated-self-switch-barrier-v2"
RAW_PAIR_OPTION = "--gameplay-raw-reader-pair"
RAW_PAIR_HELP = "Select a reviewed versioned raw reader-pair manifest. Omit for legacy I/O/R."
NATIVE_SOURCE = "gameplay-raw-reader/witness.cpp"
RAW_WINDOW_OPTION = "--gameplay-raw-window"
RAW_LOOKAROUND_OPTION = "--gameplay-raw-lookaround-ms"
RAW_WINDOW_MODES = ("whole", "retained")
RAW_WINDOW_DEFAULT = RAW_WINDOW_MODES[0]
RAW_LOOKAROUND = range(5001)
RAW_LOOKAROUND_DEFAULT = 500
RAW_WINDOW_HELP = "Choose the whole trusted window or the retained App span plus context."
RAW_LOOKAROUND_HELP = (
    f"Context on each side of the retained App span in ms ({RAW_LOOKAROUND.start}–{RAW_LOOKAROUND.stop - 1}, "
    f"default {RAW_LOOKAROUND_DEFAULT} in retained mode)."
)


def scheduler_window(app, qpf, active, upper, mode, lookaround_ms):
    first, last = app["rows"][0]["start"], app["rows"][-1]["end"]
    if mode not in RAW_WINDOW_MODES:
        raise ValueError("Unsupported raw scheduler window")
    if mode == "whole":
        if lookaround_ms is not None:
            raise ValueError(f"{RAW_LOOKAROUND_OPTION} requires {RAW_WINDOW_OPTION} retained")
        return dict(mode=mode, trusted_qpc=[active, upper], retained_app_qpc=[first, last],
                    inclusive_qpc=[active, upper], lookaround_ms=None, lookaround_ticks=None)
    effective = RAW_LOOKAROUND_DEFAULT if lookaround_ms is None else lookaround_ms
    if type(effective) is not int or effective not in RAW_LOOKAROUND:
        raise ValueError(RAW_LOOKAROUND_HELP)
    if max(active, first) >= min(upper, last):
        raise ValueError("No retained App time intersects the trusted live window")
    padding = (qpf * effective + 999) // 1000
    lower, end = max(active, first - padding), min(upper, last + padding)
    if lower >= end - 1:
        raise ValueError("Selected scheduler window is too short")
    return dict(mode=mode, trusted_qpc=[active, upper], retained_app_qpc=[first, last],
                inclusive_qpc=[lower, end - 1], half_open_qpc=[lower, end],
                lookaround_ms=effective, lookaround_ticks=padding)


def collect_proof(root, absence, query):
    if (absence != root / "independent-absence.json" or query != root / "independent-query.json"):
        raise ValueError("Stage the original independent receipts under the raw seal filenames")
    digests = {}
    for name, limit in PROOF_FILES.items():
        file = local_artifact(root, name)
        if not 0 < file.stat().st_size <= limit:
            raise ValueError(f"Invalid raw producer artifact size: {name}")
        digests[name] = digest(file)
    return dict(version=1, files=digests)


def validate_proof(root, proof, bundle, budget, etl, release, app):
    from gameplay_collector import validate_properties
    from gameplay_record import FOCUSED, LOADING, MAP_HASH, MINIMIZED, PLAY, PROFILE_HASH

    if proof.get("version") != 1 or set(proof.get("files", ())) != PROOF_FILES.keys():
        raise ValueError("Raw analysis needs a version-1 producer seal")
    files = {}
    for name, limit in PROOF_FILES.items():
        file = local_artifact(root, name)
        checked(file, proof["files"][name], limit)
        files[name] = read_app(file) if name == "readiness.qpc" else read_json(file, limit)
    config, grant, child, observer, active, controller, readiness, absence, query = (
        files[name] for name in PROOF_FILES
    )
    session = bundle["session"]
    identity = {key: app[key] for key in ("pid", "creation", "tid", "qpf", "source")}
    name = "McOsu-Controlled-" + session
    hashes = proof["files"]
    live = active["live_identity"]
    if (any(value["session"] != session for value in (config, grant, child, active, controller, absence))
            or identity != config["identity"] or identity != active["identity"] or identity != release["identity"]
            or any(readiness[key] != value for key, value in identity.items())
            or any(live[key] != identity[key] for key in ("pid", "creation", "tid", "qpf"))
            or Path(live["image"]) != Path(config["image"]).resolve()
            or config["image_sha256"] != live["image_sha256"]
            or config["image_sha256"] != active["image_sha256"]
            or config["image_sha256"] != release["image_sha256"]
            or not SHA.fullmatch(config["image_sha256"])
            or Budget.parse(config["budget"]) != budget or active["budget"] != asdict(budget)
            or controller["budget"] != asdict(budget)):
        raise ValueError("Raw recorder and App identity, session or budget disagree")
    source = grant["source"]
    expected_sources = {"python.exe", "gameplay_record.py", "gameplay_collector.py", "gameplay_budget.py",
                        "gameplay_attribution.py", "gameplay_process.py", "verification_process.py", "gameplay_raw.py"}
    if (grant["operation"] != "one-conditional-gameplay-recording"
            or grant["scope"] != "present-disabled-SeSystemProfilePrivilege" or grant["profile_sha256"] != PROFILE_HASH
            or set(source) != expected_sources or any(not SHA.fullmatch(value) for value in source.values())
            or grant["config_sha256"] != hashes["recording-config.json"]
            or child["config_sha256"] != hashes["recording-config.json"]
            or child["grant_sha256"] != hashes["recording-grant.json"]
            or child != controller["producer"] or child != release["producer"] or child != observer["child"]
            or any(type(child[key]) is not int or child[key] <= 0 for key in ("pid", "creation", "entry_ms"))
            or child["pid"] == app["pid"]
            or (observer["pid"], observer["creation"], controller["controller_entry_ms"]) !=
                (child["pid"], child["creation"], child["entry_ms"])
            or observer["exit"] != 0 or observer["wait"] != 0 or observer.get("timeout") or observer.get("error")):
        raise ValueError("Raw collector producer binding is missing or inconsistent")
    if (controller["status"] != "controller-reports-release"
            or any(receipt["incomplete"] or receipt["stop"] != 0 or receipt["after_query"] != 4201
                   or receipt["final_loss"] != 0 or receipt["watchdog_exit"] != 0 for receipt in (controller, release))
            or absence["name"] != name or absence["input_guid"] != session
            or absence["status"] != 4201 or absence["remaining_owned_processes"] != []
            or absence["query_receipt_sha256"] != hashes["independent-query.json"]
            or release["independent_receipt_sha256"] != hashes["independent-absence.json"]
            or query["operation"] != "ControlTraceW QUERY only" or query["name"] != name
            or query["input_guid"] != session or query["status"] != 4201
            or query["trace_mutation"] is not False or query["etl_read"] is not False
            or controller["etl_bytes"] != etl.stat().st_size
            or release["stop_request_qpc"] != controller["stop_request_qpc"]):
        raise ValueError("Raw collector normal release or independent query contradicts the seal")
    # Collector-owned processes must exit. An independently running App is
    # the recorder's target even while it remains live after Stop.
    owned = absence["observed_owned_pids"]
    target = absence["app_target"]
    if (type(owned) is not list or any(type(pid) is not int or pid <= 0 for pid in owned)
            or len(set(owned)) != len(owned) or child["pid"] not in owned
            or type(target) is not dict or set(target) != {"pid", "creation", "owned"}
            or type(target["pid"]) is not int or type(target["creation"]) is not int
            or (target["pid"], target["creation"]) != (app["pid"], app["creation"])
            or type(target["owned"]) is not bool or target["owned"] is not config.get("owns_app")
            or target["owned"] != (app["pid"] in owned)):
        raise ValueError("Independent release must distinguish the App target from owned processes")
    validate_properties(budget, session, etl, active["active_properties"])
    validate_properties(budget, session, etl, controller["active_properties"])
    initial = active["active_sample"]
    polls = controller["polls"]
    # There can be at most one sample per integral elapsed millisecond, even
    # after early wakeups. The JSON file has its own independent byte cap.
    if (type(polls) is not list or not 2 <= len(polls) <= budget.max_ms + 1
            or initial != controller["active_sample"] or active["active_qpc"] != initial["qpc"]
            or controller["active_qpc"] != initial["qpc"] or release["active_qpc"] != initial["qpc"]
            or active["readiness"] != controller["readiness"] or active["readiness"] != release["readiness"]):
        raise ValueError("Raw capture lacks a continuous collector sample chain")
    samples = (initial, *polls)
    ticks = [sample["qpc"] for sample in samples]
    if (any(type(tick) is not int or not 0 < tick < 2**63 for tick in ticks)
            or any(a >= b for a, b in zip(ticks, ticks[1:]))
            or any(type(sample["lost"]) is not int or sample["lost"] != 0 for sample in samples)
            or not ticks[-1] <= release["stop_request_qpc"] < 2**63):
        raise ValueError("Raw collector samples have invalid ordering or loss")
    mark = active["readiness"]["mark"]
    mark_context = next(row["context"] for row in readiness["rows"] if row["sequence"] == readiness["boundary"])
    if ((mark["id"], mark["qpc"], mark["epoch"]) != (readiness["mark_id"], readiness["mark"], readiness["epoch"])
            or (mark_context & (FOCUSED | MINIMIZED | PLAY | LOADING)) != (FOCUSED | PLAY)
            or readiness["partial"] or readiness["status"] != "recording" or not MAP_HASH.fullmatch(readiness["map"])
            or not config["baseline_mark"]["id"] < mark["id"] < app["mark_id"]
            or not config["baseline_mark"]["qpc"] < mark["qpc"] < ticks[0] <= app["mark"] < ticks[-2]):
        raise ValueError("Raw readiness or trial Mark is outside its verified coverage")
    # The final poll checks the original handles after the preceding sample.
    # Its own QPC follows that check and cannot serve as an alive timestamp.
    return ticks[0], ticks[-2], ticks[-1]


def source_digest(path):
    # Source hashes use canonical line endings across checkout and Git exports.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def reviewed_reader_pair(manifest_path, reader_sha256):
    if manifest_path is None:
        return dict(wire_schema=1, ambiguity_policy=AMBIGUITY_POLICY)
    manifest_path = Path(manifest_path).resolve(strict=True)
    with manifest_path.open("rb") as stream:
        data = stream.read(8193)
    if len(data) > 8192:
        raise ValueError("Raw reader-pair manifest exceeds 8 KiB")
    pair = json.loads(data)
    expected = dict(version=1, wire_schema=WIRE_SCHEMA, ambiguity_policy=BOUNDARY_POLICY,
                    reader_sha256=reader_sha256,
                    native_source_sha256=source_digest(Path(__file__).resolve().parent / NATIVE_SOURCE),
                    consumer_source_sha256=source_digest(Path(__file__)))
    if (type(pair) is not dict or pair.keys() != expected.keys() | {"compile_receipt_sha256"}
            or any(type(pair[key]) is not type(value) or pair[key] != value for key, value in expected.items())
            or type(pair["compile_receipt_sha256"]) is not str or not SHA.fullmatch(pair["compile_receipt_sha256"])):
        raise ValueError("Raw reader-pair manifest does not match this native and consumer pair")
    return pair | dict(manifest=str(manifest_path), manifest_sha256=hashlib.sha256(data).hexdigest())


def prepare(path, reader, output, capture, *, mode=None, lookaround_ms=None, pair_manifest=None):
    bundle, budget, etl, release, app = capture
    if (not reader.is_file() or reader.suffix.lower() != ".exe"
            or not 0 < reader.stat().st_size <= 64 * MIB):
        raise ValueError("Explicit built raw gameplay reader EXE required")
    if output.exists():
        raise FileExistsError("Raw analysis output is already occupied")
    path = Path(path).resolve()
    if "raw_evidence" not in bundle:
        raise ValueError("Raw analysis requires a raw producer seal; legacy bundles use the SDK command")
    active, upper, following = validate_proof(path.parent, bundle["raw_evidence"], bundle, budget, etl, release, app)
    evidence_cap = budget.report_mib * MIB - REPORT_METADATA_BYTES
    event_limit = min(MAX_EVENTS, (evidence_cap - RAW_METADATA_BYTES) // EVENT_ROW_BYTES)
    request = dict(Pid=app["pid"], Tid=app["tid"], Qpf=app["qpf"], Active=active, LiveUpper=upper,
                   FollowingPoll=following, EventLimit=event_limit, InputLimit=budget.etl_mib * MIB,
                   SliceLimit=budget.slices)
    effective_mode = RAW_WINDOW_DEFAULT if mode is None else mode
    window = scheduler_window(app, app["qpf"], active, upper, effective_mode, lookaround_ms)
    request["SchedulerLower"], request["SchedulerUpperInclusive"] = window["inclusive_qpc"]
    source = Path(__file__).resolve().parent
    reader_sha = digest(reader)
    pair = reviewed_reader_pair(pair_manifest, reader_sha)
    fields = dict(operation="one-offline-raw-gameplay-analysis", session=bundle["session"], bundle=str(path),
                  bundle_sha256=digest(path), output=str(output), reader=str(reader), reader_sha256=reader_sha,
                  producer_sha256=bundle["raw_evidence"]["files"]["recording-grant.json"],
                  etl_sha256=bundle["etl_sha256"], budget=asdict(budget),
                  reader_pair=pair,
                  consumer=dict(window_policy="scheduler-window-v1", ambiguity_policy=pair["ambiguity_policy"],
                                window=window, following_poll_qpc=following, requested_mode=mode,
                                requested_lookaround_ms=lookaround_ms),
                  source={name: digest(source / name) for name in
                          ("gameplay_raw.py", "gameplay_attribution.py", "gameplay_record.py",
                           "gameplay_budget.py", "gameplay_collector.py", "gameplay_process.py", "verify.py")})
    return fields, request


def describe(path, reader, output, **options):
    return prepare(path, Path(reader).resolve(), Path(output).resolve(),
                   load_bundle(path, verify_trace=False), **options)[0]


def raw_command(reader, etl, request):
    lower, upper = scheduler_bounds(request)
    prefix = ("Pid", "Tid", "Qpf", "Active", "FollowingPoll")
    return [reader, etl, *(str(request[key]) for key in prefix), str(lower), str(upper),
            str(request["EventLimit"]), str(request["InputLimit"])]


def scheduler_bounds(request):
    lower = request.get("SchedulerLower", request["Active"])
    upper = request.get("SchedulerUpperInclusive", request["LiveUpper"])
    if not request["Active"] <= lower < upper <= request["LiveUpper"]:
        raise ValueError("Scheduler bounds escape their trusted live interval")
    return lower, upper


def raw_slices(report, request, exit_code, marker, *, expected_schema=1):
    if type(expected_schema) is not int or expected_schema not in (1, WIRE_SCHEMA):
        raise ValueError("Unsupported expected raw wire schema")
    if expected_schema == 1:
        if "WireSchema" in report or "BoundaryRecords" in report:
            raise ValueError("Explicit wire envelope was not requested")
        boundary_records = 0
    else:
        if type(report.get("WireSchema")) is not int or report["WireSchema"] != WIRE_SCHEMA:
            raise ValueError("Expected exact wire schema 2")
        boundary_records = report.get("BoundaryRecords")
        if type(boundary_records) is not int or boundary_records < 0:
            raise ValueError("Invalid schema-2 boundary count")

    complete = exit_code == 0
    expected = "COMPLETE" if complete else "INCONCLUSIVE"
    if marker != expected + " raw gameplay scheduler evidence":
        raise ValueError("Raw reader exit and marker disagree")
    good = ("ProcessPair", "ThreadPair", "ClockMatches")
    bad = ("Loss", "InvalidLifecycle", "InvalidScheduler", "Overflow", "ShapeOverflow")
    if any(type(report[key]) is not bool for key in (*good, *bad)):
        raise ValueError("Invalid raw scheduler flags")
    if complete != (all(report[key] for key in good) and not any(report[key] for key in bad)):
        raise ValueError("Raw reader exit and flags disagree")
    count = report["Candidates"]
    fields = ("V4Accepted", "V4Corroborated", "V4Schema", "V4Checked", "V4Candidates")
    v4 = [report[name] for name in fields]
    if (any(type(n) is not int for n in (count, *v4))
            or not 0 <= count <= request["EventLimit"] or not 0 <= boundary_records <= v4[0] <= count
            or any(a > b for a, b in zip(v4, v4[1:]))):
        raise ValueError("Invalid raw witness counts")
    events = report["Events"]
    shapes = report["RejectedShapes"]
    rejected = report["RejectedSchedulerRecords"]
    if (type(rejected) is not int or rejected < 0 or type(shapes) is not list or len(shapes) > 16
            or any(type(shape["Count"]) is not int or shape["Count"] <= 0 for shape in shapes)
            or bool(rejected) != report["InvalidScheduler"]):
        raise ValueError("Invalid raw scheduler rejection counts")
    counted = sum(shape["Count"] for shape in shapes)
    if (report["ShapeOverflow"] and (len(shapes) != 16 or counted >= rejected)
            or not report["ShapeOverflow"] and counted != rejected
            or v4[-1] - v4[1] > rejected):
        raise ValueError("Raw scheduler rejection counts disagree")
    # Detailed records stay in the capped stream. The summary carries only
    # bounded scalar diagnostics, even for a long capture.
    keys = (*good, *bad, "Candidates", *fields, "HeaderClockType", "HeaderQpf",
            "HeaderEventsLost", "HeaderBuffersLost", "RejectedSchedulerRecords")
    summary = {key: report[key] for key in keys}
    if any(type(summary[key]) is not int or not 0 <= summary[key] < 2**64 for key in
           ("HeaderClockType", "HeaderQpf", "HeaderEventsLost", "HeaderBuffersLost")):
        raise ValueError("Invalid raw trace header diagnostics")
    if type(events) is not list or len(events) != (count if complete else 0):
        raise ValueError("Raw reader emitted an incomplete or invalid event list")
    if expected_schema == WIRE_SCHEMA:
        summary.update(WireSchema=WIRE_SCHEMA, BoundaryRecords=boundary_records, BoundaryPolicy=BOUNDARY_POLICY)
    if not complete:
        return False, [], summary
    if (report["HeaderClockType"] != 1 or report["HeaderQpf"] != request["Qpf"]
            or report["HeaderEventsLost"] != 0 or report["HeaderBuffersLost"] != 0
            or report["RejectedSchedulerRecords"] != 0 or report["RejectedShapes"] != []
            or any(n != v4[0] for n in v4)):
        raise ValueError("Raw scheduler corroboration contradicts successful admission")
    lower, upper = scheduler_bounds(request)
    prior_tick = lower
    observed_boundaries = 0
    for event in events:
        if type(event) is not dict or event.keys() != {"Tick", "Kind", "Cpu", "Detail"}:
            raise ValueError("Invalid raw scheduler event fields")
        tick, kind, cpu, detail = (event[key] for key in ("Tick", "Kind", "Cpu", "Detail"))
        if kind == "B":
            if expected_schema != WIRE_SCHEMA or type(detail) is not int or detail != 2:
                raise ValueError("Unexpected uninterpreted boundary")
            observed_boundaries += 1
        if (type(tick) is not int or not prior_tick <= tick <= upper or kind not in ("I", "O", "R", "B")
                or type(cpu) is not int or not (0 <= cpu <= 255 or 65536 <= cpu <= 131071)
                or type(detail) is not int or not 0 <= detail <= 255 or (kind == "I" and detail != 0)):
            return False, [], summary | {"Disposition": "unsupported-or-ambiguous-order"}
        prior_tick = tick
    if observed_boundaries != boundary_records:
        raise ValueError("Boundary wire count and payload disagree")

    # Validate the entire stream before interpreting any group. Resolve
    # group membership before using its first member as an endpoint.
    prior = None
    readiness = []
    slices = []
    tied_groups = tied_events = largest_group = 0
    samples = []
    boundary_groups = barrier_groups = 0
    boundary_samples = []
    cap_hit = False
    for tick, group in groupby(enumerate(events), key=lambda item: item[1]["Tick"]):
        index, event = next(group)
        size = 1
        boundaries = int(event["Kind"] == "B")
        for _, member in group:
            size += 1
            boundaries += int(member["Kind"] == "B")
        if size > 1:
            tied_groups += 1
            tied_events += size
            largest_group = max(largest_group, size)
            if len(samples) < TIE_SAMPLE_LIMIT:
                samples.append(dict(index=index, tick=tick, count=size))
        if boundaries:
            boundary_groups += 1
            if len(boundary_samples) < TIE_SAMPLE_LIMIT:
                boundary_samples.append(dict(index=index, tick=tick, count=size, boundaries=boundaries))
        if size > 1 or boundaries:
            barrier_groups += 1
            prior = None
            readiness.clear()
            continue
        if cap_hit:
            continue
        kind, cpu = event["Kind"], event["Cpu"]
        if kind == "R":
            readiness.append(event)
            continue
        if prior is not None:
            pair = prior["Kind"] + kind
            start = prior["Tick"]
            if pair == "IO" and prior["Cpu"] == cpu and not readiness:
                slices.append(dict(state="running", start=start, end=tick, cpu=cpu, endpoints=[prior, event]))
            elif pair == "OI" and prior["Detail"] == 1 and not readiness:
                slices.append(dict(state="ready", start=start, end=tick, endpoints=[prior, event]))
            elif pair == "OI" and prior["Detail"] == 5 and len(readiness) == 1 and readiness[0]["Detail"] in (0, 1):
                ready, = readiness
                endpoints = [prior, ready, event]
                slices.extend((dict(state="waiting", start=start, end=ready["Tick"], endpoints=endpoints),
                               dict(state="ready", start=ready["Tick"], end=tick, endpoints=endpoints)))
            if len(slices) > request["SliceLimit"]:
                cap_hit = True
        prior = event
        readiness.clear()
    summary.update(TiedGroups=tied_groups, TiedEvents=tied_events, LargestTiedGroup=largest_group,
                   TiedGroupSamples=samples, TiedSamplesSaturated=tied_groups > len(samples))
    if expected_schema == WIRE_SCHEMA:
        summary.update(BoundaryGroups=boundary_groups, BarrierGroups=barrier_groups,
                       BoundaryGroupSamples=boundary_samples,
                       BoundarySamplesSaturated=boundary_groups > len(boundary_samples))
    if cap_hit:
        return False, [], summary | {"Disposition": "slice-cap"}
    return True, slices, summary

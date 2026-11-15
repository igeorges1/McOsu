"""Validate a released gameplay bundle and reduce decoder evidence to App spans."""

import hashlib
import json
from pathlib import Path
import re
import os
import sys
import tempfile
import uuid

from gameplay_budget import Budget, MIB
from gameplay_process import execute

SHA = re.compile(r"[0-9a-f]{64}\Z")
HEX_ID = re.compile(r"[0-9a-f]{40,64}\Z")
APP_LIMIT = 2 * MIB
STATES = ("running", "waiting", "ready", "unknown")
REPORT_METADATA_BYTES = 64 * 1024


def read_json(path, limit):
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Input exceeds limit: {path}")
    return json.loads(data)


def checked(path, expected, limit):
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise ValueError("Invalid artifact hash")
    with path.open("rb") as stream:
        size = path.stat().st_size
        if not 0 < size <= limit or hashlib.file_digest(stream, "sha256").hexdigest() != expected:
            raise ValueError(f"Invalid artifact size or hash: {path}")
    return size


def read_app(path):
    with path.open("rb") as stream:
        raw = stream.read(APP_LIMIT + 1)
    return read_app_bytes(raw)


def read_app_bytes(raw):
    if len(raw) > APP_LIMIT:
        raise ValueError("App sidecar exceeds its bound")
    lines = raw.decode("ascii").splitlines()
    if len(lines) < 11 or lines[0] != "MCOSU_GAMEPLAY_QPC 1":
        raise ValueError("Unsupported App sidecar")
    def fields(index, key, count):
        name, _, value = lines[index].partition(" ")
        words = value.split()
        if name != key or len(words) != count:
            raise ValueError(f"Malformed App {key}")
        return words

    def numbers(index, key, count):
        words = fields(index, key, count)
        if any(not re.fullmatch(r"-?[0-9]{1,20}", word) for word in words):
            raise ValueError(f"Non-integer App {key}")
        return [int(word) for word in words]

    source, = fields(1, "source", 1)
    map_id, = fields(2, "map", 1)
    if not HEX_ID.fullmatch(source):
        raise ValueError("Unknown App source identity")
    pid, created, tid, qpf = numbers(3, "identity", 4)
    mark_id, epoch, mark, boundary = numbers(4, "mark", 4)
    settings = numbers(5, "settings", 14)
    if (not lines[6].startswith("status ") or not lines[7].startswith("post_end ")
            or lines[-1] not in ("end complete", "end partial")):
        raise ValueError("Incomplete App sidecar framing")
    observed, retained, evicted, post = numbers(8, "counts", 4)
    stages = numbers(9, "stages", 3)
    if not (0 < pid <= 0xffffffff and 0 < tid <= 0xffffffff and 0 < created < 2**64
            and 0 < qpf < 2**63 and mark_id > 0 and epoch > 0 and 0 <= mark < 2**63 and boundary > 0
            and 1 <= retained <= observed <= 4217 and len(lines) == 11 + retained
            and 0 <= post <= settings[9] <= 120 and evicted >= 0
            and settings[0] == 1 and all(settings[k] in (0, 1) for k in (1, 2, 3, 12, 13))
            and 1 <= settings[4] <= 4 and retained <= settings[5] <= 4217
            and 120 <= settings[7] <= 4096 and 100 <= settings[10] <= 5000 and 1 <= settings[11] <= 12):
        raise ValueError("App sidecar identity or bounds are inconsistent")
    rows = []
    partial = lines[-1] == "end partial"
    previous = None
    for index in range(10, 10 + retained):
        sequence, generation, start, end, update, draws, raw_draws, context, *spans = numbers(index, "frame", 16)
        if (sequence <= 0 or generation != epoch or not 0 <= start < end < 2**63
                or (previous and (sequence <= previous[0] or start < previous[1]))
                or not 0 <= draws <= 0xffffffff or not 0 <= raw_draws <= draws):
            raise ValueError("Invalid raw frame interval")
        if previous and (start != previous[1] or sequence != previous[0] + 1):
            partial = True
        previous = sequence, end
        scopes = []
        if settings[1]:
            if start <= update <= end:
                scopes.append(("update", start, update))
            else:
                partial = True
        edge = scopes[-1][2] if scopes else start
        for draw in range(min(raw_draws, settings[4]) if settings[2] else 0):
            left, right = spans[2 * draw:2 * draw + 2]
            if edge <= left <= right <= end:
                scopes.append((f"draw-{draw + 1}", left, right))
                edge = right
            else:
                partial = True
        if settings[2] and (draws != raw_draws or raw_draws > settings[4]):
            partial = True
        rows.append({"sequence": sequence, "start": start, "end": end, "context": context, "scopes": scopes})
    at_mark = [row for row in rows if row["start"] <= mark < row["end"]]
    if len(at_mark) != 1 or at_mark[0]["sequence"] != boundary:
        raise ValueError("Missing or inconsistent half-open Mark boundary")
    if lines[-1] == "end complete" and (retained != observed or post != settings[9]):
        partial = True
    return dict(source=source, map=map_id, pid=pid, creation=created, tid=tid, qpf=qpf, mark_id=mark_id,
                epoch=epoch, mark=mark, boundary=boundary, rows=rows, partial=partial,
                settings=settings, stages=stages, observed=observed, evicted=evicted,
                status=lines[6][7:], post_end=lines[7][9:])


def reduce_span(start, end, slices):
    if start > end:
        raise ValueError("Unordered span")
    totals = dict.fromkeys(STATES, 0)
    contributing = []
    cursor = start
    for raw in slices:
        left, right = max(start, raw["start"]), min(end, raw["end"])
        if left >= right:
            continue
        if left < cursor:
            raise ValueError("Overlapping scheduler evidence")
        totals["unknown"] += left - cursor
        totals[raw["state"]] += right - left
        contributing.append({**raw, "clipped_start": left, "clipped_end": right})
        cursor = right
    totals["unknown"] += end - cursor
    return {"start": start, "end": end, "ticks": totals, "slices": contributing}


def local_artifact(root, name):
    if not isinstance(name, str) or Path(name).name != name or name in ("", ".", "..") or ":" in name:
        raise ValueError("Expected a bundle-local filename")
    candidate = root / name
    if candidate.resolve().parent != root or candidate.is_symlink() or candidate.is_junction():
        raise ValueError("Bundle artifact escapes its directory")
    return candidate


def load_bundle(path, *, verify_trace=True):
    path = Path(path).resolve()
    bundle = read_json(path, 64 * 1024)
    budget = Budget.parse(bundle["budget"])
    session = str(uuid.UUID(bundle["session"]))
    if bundle["session"] != session:
        raise ValueError("Noncanonical trace identity")
    app_file, etl, release_file = (local_artifact(path.parent, bundle[key]) for key in ("app", "etl", "release"))
    checked(app_file, bundle["app_sha256"], APP_LIMIT)
    if verify_trace:
        size = checked(etl, bundle["etl_sha256"], budget.etl_mib * MIB)
    else:
        size = etl.stat().st_size
        if not 0 < size < budget.etl_mib * MIB or not SHA.fullmatch(bundle["etl_sha256"]):
            raise ValueError("Invalid declared trace size or hash")
    checked(release_file, bundle["release_sha256"], 64 * 1024)
    release = read_json(release_file, 64 * 1024)
    app = read_app(app_file)
    if (size >= budget.etl_mib * MIB or release["session"] != session
            or release["etl_sha256"] != bundle["etl_sha256"] or release["status"] != "normal-owned-release-verified"
            or release["stop"] != 0 or release["after_query"] != 4201 or release["independent_query"] != 4201
            or release["budget"] != bundle["budget"] or release["incomplete"]
            or release["identity"] != {key: app[key] for key in ("pid", "creation", "tid", "qpf", "source")}
            or not SHA.fullmatch(release["image_sha256"])
            or not release["active_qpc"] <= app["mark"] < release["stop_request_qpc"]):
        raise ValueError("Released trace and App Mark are not an eligible bound run")
    return bundle, budget, etl, release, app


def analyze(path, reader, dotnet, output, *, raw_grant=None, raw_options=None):
    raw_mode = dotnet is None
    capture = load_bundle(path, verify_trace=False) if raw_mode else load_bundle(path)
    bundle, budget, etl, release, app = capture
    reader = Path(reader).resolve()
    output = Path(output).resolve()
    report_cap = budget.report_mib * MIB
    evidence_cap = report_cap - REPORT_METADATA_BYTES
    if raw_mode:
        from gameplay_raw import prepare, raw_command, raw_slices
        fields, request = prepare(path, reader, output, capture, **(raw_options or {}))
        issued = read_json(Path(raw_grant), 64 * 1024) if raw_grant is not None else None
        if json.dumps(issued, sort_keys=True) != json.dumps(fields, sort_keys=True):
            raise PermissionError("Exact offline raw analysis grant required")
        command = raw_command(reader, etl, request)
    else:
        dotnet = Path(dotnet).resolve()
        if not reader.is_file() or not dotnet.is_file():
            raise ValueError("Explicit built gameplay reader and .NET executable required")
        for artifact in (reader, reader.with_suffix(".deps.json"), reader.with_suffix(".runtimeconfig.json")):
            if not artifact.is_file():
                raise ValueError("Incomplete gameplay reader build")
        request = dict(Pid=app["pid"], Tid=app["tid"], Creation=app["creation"], Qpf=app["qpf"],
                       Active=release["active_qpc"], Stop=release["stop_request_qpc"],
                       First=app["rows"][0]["start"], Last=app["rows"][-1]["end"],
                       InputLimit=budget.etl_mib * MIB, SliceLimit=budget.slices)
        command = [dotnet, reader, output / "request.json", etl]
    provider = "raw-classic-etw" if raw_mode else "sdk"
    output.mkdir(exist_ok=False)
    if raw_mode:
        checked(etl, bundle["etl_sha256"], budget.etl_mib * MIB - 1)
        checked(reader, fields["reader_sha256"], 64 * MIB)
    request_file = output / "request.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")
    env = {**os.environ, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_MULTILEVEL_LOOKUP": "0"}
    with tempfile.TemporaryDirectory() as temp:
        env.update(TEMP=temp, TMP=temp, DOTNET_CLI_HOME=temp)
        record = execute(command, output, env, budget.analysis_ms / 1000,
                         output / "reader.stdout", output / "reader.stderr",
                         memory_limit=budget.analysis_memory_mib * MIB, stream_limit=evidence_cap)
    record["reader_sha256"] = fields["reader_sha256"] if raw_mode else hashlib.sha256(reader.read_bytes()).hexdigest()
    if raw_mode:
        record["provider"] = provider
        record["bundle_sha256"] = fields["bundle_sha256"]
        record["producer_sha256"] = fields["producer_sha256"]
        record["reader_pair"] = fields["reader_pair"]
    record["etl_sha256"] = bundle["etl_sha256"]
    write_metadata(output / "process.json", record, 32768)
    if record["timeout"] or record["error"] or record["owned_process_remaining"] or record["exit"] not in (0, 3):
        raise ValueError("Gameplay decoder fault; see process and stream receipts")
    if record.get("stream_truncated"):
        summary = {"status": "inconclusive", "reason": "decoder stream cap"}
        if raw_mode:
            summary.update(provider=provider, consumer=fields["consumer"], reader_pair=fields["reader_pair"],
                           marked_frame={"status": "unavailable"})
        write_metadata(output / "summary.json", summary, 16384)
        print("INCONCLUSIVE decoder stream cap", file=sys.stderr)
        return 3
    if (output / "reader.stderr").stat().st_size:
        raise ValueError("Unexpected gameplay decoder stderr")
    with (output / "reader.stdout").open("rb") as stream:
        raw = stream.read(budget.report_mib * MIB + 1)
    if len(raw) > evidence_cap:
        print("INCONCLUSIVE decoder output cap", file=sys.stderr)
        return 3
    payload, marker = raw.decode("utf-8").strip().splitlines()
    decoder = json.loads(payload)
    if raw_mode:
        usable, slices, decoder = raw_slices(decoder, request, record["exit"], marker,
                                             expected_schema=fields["reader_pair"]["wire_schema"])
    else:
        usable = record["exit"] == 0 and marker == "COMPLETE gameplay scheduler evidence" and decoder["Usable"] is True
        if not usable and (record["exit"] != 3 or marker != "INCONCLUSIVE gameplay scheduler evidence" or decoder["Usable"] is not False):
            raise ValueError("Decoder exit and result disagree")
        slices = []
        if usable:
            for row in decoder["Slices"]:
                a, b, state = row["Start"], row["End"], row["State"]
                if (type(a) is not int or type(b) is not int or not decoder["Lower"] <= a < b <= decoder["Upper"]
                        or state not in STATES[:3] or (slices and a < slices[-1]["end"]) or len(slices) >= budget.slices):
                    raise ValueError("Invalid or oversized scheduler evidence")
                slices.append(dict(state=state, start=a, end=b, cpu=row["Cpu"], off=row["Off"],
                                   ready=row["Ready"], next=row["Next"]))
        decoder.pop("Slices")
    result = {
        "source": app["source"], "map": app["map"], "session": bundle["session"], "qpf": app["qpf"],
        "identity": release["identity"], "image_sha256": release["image_sha256"],
        "budget": bundle["budget"], "app_settings": app["settings"], "mark": app["mark"],
        "mark_id": app["mark_id"], "epoch": app["epoch"], "boundary": app["boundary"],
        "app_status": app["status"], "app_post_end": app["post_end"], "app_mark_stages": app["stages"],
        "observed_rows": app["observed"], "retained_rows": len(app["rows"]), "evicted": app["evicted"],
        "decoder": decoder, "partial_app": app["partial"],
    }
    if raw_mode:
        result.update(provider=provider, window=dict(active_qpc=request["Active"], upper_qpc=request["LiveUpper"]),
                      consumer=fields["consumer"], reader_pair=fields["reader_pair"],
                      marked_frame={"status": "unavailable"},
                      scheduler_status="verified" if usable else "unconfirmed",
                      observed_slice_span=[slices[0]["start"], slices[-1]["end"]] if slices else None,
                      coverage=dict(written_frames=0, frames_with_unknown=0, unknown_ticks=0))
    inconclusive = not usable
    size = 0
    cap = evidence_cap - sum((output / name).stat().st_size for name in ("reader.stdout", "reader.stderr"))
    index = 0
    with (output / "frames.jsonl").open("xb") as stream:
        for row in app["rows"]:
            while index < len(slices) and slices[index]["end"] <= row["start"]:
                index += 1
            right = index
            while right < len(slices) and slices[right]["start"] < row["end"]:
                right += 1
            visible = slices[index:right]
            frame = reduce_span(row["start"], row["end"], visible)
            unknown = frame["ticks"]["unknown"]
            scopes = []
            edge = row["start"]
            for name, left, stop in row["scopes"]:
                if edge < left:
                    scopes.append(dict(name="outside-recorded-app-scopes", **reduce_span(edge, left, visible)))
                scopes.append(dict(name=name, **reduce_span(left, stop, visible)))
                edge = stop
            if edge < row["end"]:
                scopes.append(dict(name="outside-recorded-app-scopes", **reduce_span(edge, row["end"], visible)))
            inconclusive |= unknown > 0
            line = (json.dumps(dict(sequence=row["sequence"], context=row["context"], frame=frame, scopes=scopes),
                               separators=(",", ":")) + "\n").encode()
            if size + len(line) > cap:
                result["output_truncated"] = True
                inconclusive = True
                break
            stream.write(line)
            size += len(line)
            if raw_mode:
                result["coverage"]["written_frames"] += 1
                result["coverage"]["frames_with_unknown"] += int(unknown > 0)
                result["coverage"]["unknown_ticks"] += unknown
            if raw_mode and row["sequence"] == app["boundary"]:
                status = "complete" if not unknown else "partial" if visible else "unavailable"
                result["marked_frame"] = dict(status=status, sequence=row["sequence"],
                                              ticks=frame["ticks"],
                                              scopes=[dict(name=scope["name"], ticks=scope["ticks"]) for scope in scopes])
    result["status"] = "inconclusive" if inconclusive or app["partial"] else "complete"
    write_metadata(output / "summary.json", result, 16384)
    print(f'{result["status"].upper()} gameplay attribution: {output}')
    return 0 if result["status"] == "complete" else 3


def write_metadata(path, value, limit):
    payload = json.dumps(value, indent=2).encode("utf-8")
    if len(payload) > limit:
        payload = b'{"status":"inconclusive","reason":"metadata cap"}'
        path.write_bytes(payload)
        raise ValueError("Gameplay report metadata cap")
    path.write_bytes(payload)

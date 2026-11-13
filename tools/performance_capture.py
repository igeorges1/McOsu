"""Validate and graph raw application cadence from a marked capture."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import time
import uuid


COLUMNS = "sequence,start,interval,update,draw,draws,context,fps_limit,background_limit,unlimited,vsync"
FLAGS = ("focused", "minimized", "play", "paused", "loading", "countdown", "continue")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_capture(data):
    lines = data.decode("ascii").splitlines()
    require(len(lines) >= 14 and lines[0] == "MCOSU_PERFORMANCE 1", "Unsupported performance capture schema")

    def field(index, name):
        require(lines[index].startswith(name + " "), "Missing " + name)
        return lines[index][len(name) + 1:]

    source, map_id = field(1, "source"), field(2, "map")
    require(re.fullmatch(r"unknown|[0-9a-f]{40}", source), "Invalid source identity")
    require(re.fullmatch(r"unknown|[0-9a-f]{32}", map_id), "Invalid map identity")
    require(field(3, "clock") == "engine_monotonic_seconds", "Unsupported clock")
    mark = float(field(4, "mark"))
    evicted, gaps = int(field(5, "evicted")), int(field(6, "discontinuities"))
    post, target = map(int, field(7, "post").split())
    marked_sequence = int(field(8, "boundary"))
    boundary = "complete" if marked_sequence else "missing"
    post_end = field(9, "post_end")
    stages = tuple(map(float, field(10, "stages_ms").split()))
    names = ("snapshot_main", "readback_main", "reserve_worker", "report_format_write_worker", "png_encode_worker", "png_write_worker")
    require(len(stages) == len(names) and all(math.isfinite(value) and (value == -1 or value >= 0) for value in stages),
            "Invalid capture stage durations")
    count = int(field(11, "frames"))
    require(math.isfinite(mark) and 0 <= mark <= 1e12 and evicted >= 0 and gaps >= 0, "Invalid mark or history counters")
    require(0 <= post <= target <= 120 and 0 <= count <= 4217, "Invalid frame or post-mark bound")
    require(marked_sequence >= 0 and post_end in {"target", "scene", "settings", "deadline", "clock", "shutdown"}
            and (post_end != "target" or (post == target and (marked_sequence or target > 0))), "Inconsistent post-mark completion")
    require(lines[12] == COLUMNS and lines[-1] == "end" and len(lines) == 14 + count, "Truncated or extra frame rows")
    frames = []
    for line in lines[13:-1]:
        fields = line.split(",")
        require(len(fields) == 11 and len(line) <= 384, "Invalid frame row")
        sequence = int(fields[0])
        start, interval, update, draw = map(float, fields[1:5])
        draws, context = map(int, fields[5:7])
        limits = tuple(map(float, fields[7:9]))
        unlimited, vsync = map(int, fields[9:11])
        require(all(math.isfinite(v) for v in (start, interval, update, draw, *limits))
                and 0 <= start <= 1e12 and 0 <= interval <= 1e12 and (update == -1 or 0 <= update <= 1e12)
                and ((draws == 0 and draw == -1) or (draws > 0 and 0 <= draw <= 1e12))
                and 0 <= context <= 127 and unlimited in (-1, 0, 1) and vsync in (-1, 0, 1)
                and sequence > (frames[-1]["sequence"] if frames else 0), "Invalid frame values or ordering")
        if frames and not gaps:
            previous = frames[-1]
            require(sequence == previous["sequence"] + 1 and math.isclose(start, previous["start"] + previous["interval"],
                    rel_tol=1e-12, abs_tol=1e-9), "Unexpected frame gap")
        frames.append(dict(sequence=sequence, start=start, interval=interval, update=update, draw=draw, draws=draws,
                           context=context, fps_limit=limits[0], background_limit=limits[1], unlimited=unlimited, vsync=vsync))
    require(not marked_sequence or any(f["sequence"] == marked_sequence and f["start"] <= mark <= f["start"] + f["interval"] + 1e-12
                                      for f in frames), "Missing mark-containing interval")
    require(post == sum(f["start"] >= mark and f["sequence"] != marked_sequence for f in frames), "Incorrect post-mark count")
    return dict(source=source, map=map_id, mark=mark, evicted=evicted, discontinuities=gaps,
                post=post, post_target=target, post_end=post_end, boundary=boundary, marked_sequence=marked_sequence,
                stages_ms={name: value if value >= 0 else None for name, value in zip(names, stages)}, frames=frames)


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return {"count": 0}
    def percentile(p):
        return ordered[max(0, math.ceil(len(ordered) * p) - 1)] * 1000
    return dict(count=len(ordered), median_ms=statistics.median(ordered) * 1000,
                p95_ms=percentile(.95), p99_ms=percentile(.99), max_ms=ordered[-1] * 1000)


def summary(capture):
    mark = capture["mark"]
    frames = capture["frames"]
    groups = {"before": [], "crosses_mark": [], "after": []}
    for frame in frames:
        start = frame["start"]
        group = "crosses_mark" if frame["sequence"] == capture["marked_sequence"] else "after" if start >= mark else "before"
        groups[group].append(frame)
    return {**{k: v for k, v in capture.items() if k != "frames"},
            "unavailable": ["main loop", "limiter wait", "swap", "GPU execution", "display"],
            "cadence": {key: distribution(f["interval"] for f in group) for key, group in groups.items()},
            "app_update": distribution(f["update"] for f in frames if f["update"] >= 0),
            "app_draw": distribution(f["draw"] for f in frames if f["draw"] >= 0),
            "without_draw": sum(f["draws"] == 0 for f in frames),
            "multiple_draws": sum(f["draws"] > 1 for f in frames),
            "context_counts": dict(Counter(str(f["context"]) for f in frames)),
            "context_bit_names": dict(enumerate(FLAGS)),
            "worst": sorted(frames, key=lambda f: f["interval"], reverse=True)[:10]}


def graph(capture):
    frames = capture["frames"]
    mark = capture["mark"]
    x0 = min([mark, *(f["start"] for f in frames)])
    x1 = max([mark, *(f["start"] + f["interval"] for f in frames)])
    peak = max([.001, *(f["interval"] for f in frames), *(f["draw"] for f in frames), *(f["update"] for f in frames)])

    def x(value):
        return 72 + (value - x0) * 900 / max(.001, x1 - x0)

    def y(value):
        return 340 - value * 270 / peak

    output = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 408">',
              '<rect width="1000" height="408" fill="#fff"/>',
              '<g font-family="sans-serif" font-size="14" fill="#17252f">',
              '<text x="72" y="25">App update cadence and CPU-side phases around mark</text>',
              '<text x="72" y="46">Cadence (blue) · Update (teal) · Draw (purple) · Mark (red)</text>',
              '<text x="72" y="392">Seconds relative to mark · gaps indicate unavailable observations</text>']
    for fraction in (0, .25, .5, .75, 1):
        level = peak * fraction
        output.append(f'<path d="M72 {y(level):.2f}H972" stroke="#d6dde1"/>')
        output.append(f'<text x="12" y="{y(level)+4:.2f}">{level*1000:.1f} ms</text>')
    for i in range(5):
        t = x0 + (x1 - x0) * i / 4
        output.append(f'<text x="{min(930, x(t)):.2f}" y="365">{t-mark:.3f}</text>')
    output.append(f'<path d="M{x(mark):.2f} 70V340" stroke="#b12020" stroke-dasharray="5 4"/>')
    for field, color in (("interval", "#174f85"), ("update", "#008079"), ("draw", "#774ea1")):
        for frame in frames:
            value = frame[field]
            if value >= 0:
                output.append(f'<circle cx="{x(frame["start"]):.2f}" cy="{y(value):.2f}" r="1.8" fill="{color}"/>')
    if not frames:
        output.append('<text x="90" y="102">No completed app update intervals in this report</text>')
    return "\n".join(output + ["</g></svg>", ""])


def analyze(path, checkout):
    limit = 2 * 1024 * 1024
    path = Path(path).resolve()
    require(path.is_file() and 0 < path.stat().st_size <= limit, "Missing or oversized performance capture")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    require(0 < len(data) <= limit, "Performance capture exceeds byte limit")
    capture = read_capture(data)
    parent = checkout / ".verification-runs"
    require(not parent.is_symlink() and (not parent.exists() or parent.resolve() == parent), "Invalid verification output root")
    parent.mkdir(exist_ok=True)
    out = parent / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-perf-" + uuid.uuid4().hex[:8])
    out.mkdir()
    (out / "performance.csv").write_bytes(data)
    result = summary(capture)
    result["input_sha256"] = hashlib.sha256(data).hexdigest()
    result["input"] = str(path)
    (out / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (out / "timeline.svg").write_text(graph(capture), encoding="utf-8")
    print(f"COMPLETE performance samples={len(capture['frames'])} summary={out / 'summary.json'} graph={out / 'timeline.svg'}")

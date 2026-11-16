"""Source-only operator capture policy and metadata console.

The Windows adapter that supplies original-handle and protected-channel
observations is a separate installation prerequisite. There is no native
Start, recovery, playback or trace reader in this entry point.
"""

import argparse
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys
import uuid

from gameplay_attribution import APP_LIMIT, HEX_ID, STATES, read_app_bytes, reduce_span
from gameplay_budget import Budget, MIB
from gameplay_collector import validate_properties
from gameplay_operator_package import canonical, digest, exact_keys, fields_from_json, is_sha
from gameplay_raw import WIRE_SCHEMA
from gameplay_mark_inventory import FOCUSED, LOADING, MAP_HASH, MARK_FOLDER, MINIMIZED, PLAY, capture_entries, is_reparse


PREFERENCES_FILE = "operator-preferences.json"
REPORT_FILE = "operator-report.json"
METADATA_LIMIT = 64 * 1024
CONSENT_MS = 120_000
CUE_MS, CUE_MEMORY, CUE_OUTPUT = 500, 64 * MIB, 8 * 1024
CUE_TONES = {"soft": (660, 0.12), "clear": (880, 0.22)}
UNAVAILABLE = "Operator capture unavailable. A qualified protected Windows package and installed route are required."


@dataclass(frozen=True)
class Setting:
    key: str
    default: str | int
    unit: str
    help: str
    choices: tuple[str, ...] = ()
    minimum: int = 0
    maximum: int = 0

    @property
    def flag(self):
        return "--" + self.key.replace("_", "-")

    @property
    def domain(self):
        return ", ".join(self.choices) if self.choices else f"{self.minimum}–{self.maximum}"

    def parse(self, value):
        if (type(value) is not type(self.default)
                or (value not in self.choices if self.choices else not self.minimum <= value <= self.maximum)):
            raise ValueError(f"Invalid {self.key}. Reset the preference or choose {self.domain}.")
        return value


SETTINGS = (
    Setting("active_cue", "soft", "preset", "Play one cue after authenticated RECORDING. Off leaves visible status.",
            (*CUE_TONES, "off")),
    Setting("baseline_wait_ms", 45_000, "ms", "Time from Start to bind a fresh saved baseline Mark.",
            minimum=1000, maximum=120_000),
)


def settings(requested):
    if type(requested) is not dict or requested.keys() - {spec.key for spec in SETTINGS}:
        raise ValueError("Unknown operator preference")
    return {spec.key: spec.parse(requested.get(spec.key, spec.default)) for spec in SETTINGS}


def bounded_read(path, limit):
    attributes = path.lstat()
    if not stat.S_ISREG(attributes.st_mode) or is_reparse(attributes) or not 0 < attributes.st_size <= limit:
        raise ValueError("Expected a bounded regular observation file")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if not 0 < len(raw) <= limit:
        raise ValueError("Observation file changed or exceeded its bound")
    return raw


def read_preferences(directory):
    try:
        raw = bounded_read(directory / PREFERENCES_FILE, METADATA_LIMIT)
    except FileNotFoundError:
        return {}
    record = fields_from_json(raw, METADATA_LIMIT)
    if not exact_keys(record, "version preferences") or type(record["version"]) is not int or record["version"] != 1:
        raise ValueError("Unknown operator preferences version")
    settings(record["preferences"])
    return record["preferences"]


def save_preferences(directory, requested):
    settings(requested)
    attributes = directory.lstat()
    if not stat.S_ISDIR(attributes.st_mode) or is_reparse(attributes):
        raise ValueError("Expected a local preferences directory")
    destination = directory / PREFERENCES_FILE
    temporary = directory / f".operator-preferences-{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(canonical({"version": 1, "preferences": requested}) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def capture_capacity(root, limit, needed):
    entries = capture_entries(root, limit)
    if len(entries) > limit:
        raise ValueError("Diagnostic capture folder exceeds the collector inventory limit")
    directories = []
    for entry in entries:
        attributes = entry.stat(follow_symlinks=False)
        if stat.S_ISDIR(attributes.st_mode) or (
                getattr(attributes, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_DIRECTORY):
            directories.append(entry.name)
    if limit - len(entries) < needed:
        raise ValueError("Insufficient capture slots for required Marks")
    return tuple(sorted(directories)), limit - len(directories), limit - len(entries)


@dataclass(frozen=True)
class Target:
    pid: int
    creation: int
    tid: int
    qpf: int
    source: str
    image_sha256: str
    account: str
    desktop: int
    app_settings: tuple[int, ...]
    process_object: str
    thread_object: str
    image: str


@dataclass(frozen=True)
class Actor:
    pid: int
    creation: int
    account: str
    desktop: int
    image_sha256: str
    elevated: bool


@dataclass(frozen=True)
class ProcessObject:
    actor: Actor
    identity: str


@dataclass(frozen=True)
class Mark:
    folder: str
    raw: bytes

    def parsed(self):
        return read_app_bytes(self.raw)


def candidate_marks(root, limit, *, exclude=()):
    results = []
    for entry in capture_entries(root, limit):
        if entry.name in exclude or not MARK_FOLDER.fullmatch(entry.name):
            continue
        try:
            attributes = entry.stat(follow_symlinks=False)
            if not stat.S_ISDIR(attributes.st_mode) or is_reparse(attributes):
                continue
            folder = Path(entry.path)
            if b"gameplay_qpc=saved" not in bounded_read(folder / "export.txt", 4096).splitlines():
                continue
            mark = Mark(entry.name, bounded_read(folder / "gameplay.qpc", APP_LIMIT))
            mark.parsed()
        except (OSError, ValueError):
            continue
        results.append(mark)
    return sorted(results, key=lambda mark: mark.folder)


def matches(mark, target):
    return (all(mark[key] == getattr(target, key) for key in ("pid", "creation", "tid", "qpf", "source"))
            and tuple(mark["settings"]) == target.app_settings and mark["status"] == "recording")


def select_baseline(root, target, excluded, after_qpc):
    limit = target.app_settings[11]
    capture_capacity(root, limit, 2)
    eligible = []
    for mark in candidate_marks(root, limit, exclude=excluded):
        app = mark.parsed()
        if matches(app, target) and app["mark"] > after_qpc and not app["partial"]:
            eligible.append(mark)
    if len(eligible) != 1:
        raise ValueError("Expected one fresh complete baseline for the original target")
    return eligible[0]


def positive_int(value):
    return type(value) is int and value > 0


def uuid_text(value):
    return type(value) is str and len(value) == 36 and str(uuid.UUID(value)) == value


@dataclass(frozen=True)
class AttemptPlan:
    session: str
    profile: str
    package: object
    requester: ProcessObject
    target: Target
    baseline: Mark
    cue: str
    baseline_wait_ms: int
    requested: tuple
    requested_budget: tuple
    budget: Budget
    consent_until_ms: int
    directory: str
    capture_directory: str
    report_directory: str

    @property
    def sha256(self):
        value = asdict(self)
        value["baseline"] = {"folder": self.baseline.folder, "sha256": digest(self.baseline.raw)}
        return digest(canonical(value))


def prepare_attempt(request, *, package, profile, requester, target, baseline, baseline_floor_qpc, attempt_base,
                    capture_directory, report_base, start_ms, dispatch_ms):
    """Only the normal Start adapter supplies its original requester and target observations."""
    if (not exact_keys(request, "version operation session profile package_sha256 preferences budget")
            or type(request["version"]) is not int or request["version"] != 1
            or request["operation"] != "start-operator-capture" or not uuid_text(request["session"])
            or type(profile) is not str or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", profile)
            or request["profile"] != profile or request["package_sha256"] != package.manifest_sha256):
        raise ValueError("Unsupported or mismatched operator Start intent")
    resolved = settings(request["preferences"])
    budget = Budget.parse(request["budget"])
    actor = requester.actor
    app = baseline.parsed()
    image = Path(target.image)
    if (not all((requester.identity, target.process_object, target.thread_object))
            or len({requester.identity, target.process_object, target.thread_object}) != 3
            or not positive_int(actor.pid) or not positive_int(actor.creation)
            or not actor.account or actor.account != target.account or actor.desktop != target.desktop
            or actor.elevated is not False or actor.image_sha256 != package.interpreter_sha256
            or actor.pid == target.pid or not is_sha(target.image_sha256) or not HEX_ID.fullmatch(target.source)
            or not matches(app, target) or app["partial"] or not positive_int(baseline_floor_qpc)
            or app["mark"] <= baseline_floor_qpc or not attempt_base.is_absolute() or ".." in attempt_base.parts
            or not report_base.is_absolute() or ".." in report_base.parts
            or report_base.is_relative_to(attempt_base) or attempt_base.is_relative_to(report_base)
            or attempt_base.is_relative_to(capture_directory) or capture_directory.is_relative_to(attempt_base)
            or report_base.is_relative_to(capture_directory) or capture_directory.is_relative_to(report_base)
            or not image.is_absolute() or ".." in image.parts or image.name.lower() != "mcosu.exe"
            or capture_directory != image.parent / "timing-captures"
            or not positive_int(start_ms) or not positive_int(dispatch_ms)
            or not start_ms <= dispatch_ms < start_ms + resolved["baseline_wait_ms"]):
        raise PermissionError("Operator identity, baseline or Start deadline did not match")
    return AttemptPlan(request["session"], profile, package, requester, target, baseline,
                       resolved["active_cue"], resolved["baseline_wait_ms"],
                       tuple(sorted(request["preferences"].items())), tuple(sorted(request["budget"].items())),
                       budget, dispatch_ms + CONSENT_MS,
                       str(attempt_base / request["session"]), str(capture_directory),
                       str(report_base / request["session"]))


@dataclass(frozen=True)
class HandleRegistration:
    supervisor: ProcessObject
    controller: ProcessObject
    watchdog: ProcessObject
    transferred_watchdog: ProcessObject
    registered_ms: int

    @property
    def owned(self):
        return self.supervisor, self.controller, self.watchdog

    def validate(self, plan, consent_ms):
        objects = (plan.requester, *self.owned)
        if (self.watchdog != self.transferred_watchdog
                or any(not item.identity for item in objects)
                or len({item.identity for item in objects} | {plan.target.process_object, plan.target.thread_object})
                != len(objects) + 2
                or len({item.actor.pid for item in objects} | {plan.target.pid}) != len(objects) + 1
                or any(item.actor.elevated is not True or not positive_int(item.actor.pid)
                       or not positive_int(item.actor.creation) or item.actor.account != plan.target.account
                       or item.actor.desktop != plan.target.desktop
                       or item.actor.image_sha256 != plan.package.background_sha256 for item in self.owned)
                or not positive_int(consent_ms) or consent_ms >= plan.consent_until_ms
                or not consent_ms <= self.registered_ms < consent_ms + plan.budget.observer_ms):
            raise PermissionError("Consent or original controller/watchdog registration did not match")


def select_readiness(root, plan, opened_qpc, folder):
    target, prior = plan.target, plan.baseline.parsed()
    limit = target.app_settings[11]
    # The readiness Mark already occupies its own slot. Preserve a slot for evidence.
    capture_capacity(root, limit, 1)
    for candidate in candidate_marks(root, limit):
        if candidate.folder != folder:
            continue
        app = candidate.parsed()
        boundary = next(row for row in app["rows"] if row["sequence"] == app["boundary"])
        if (matches(app, target) and not app["partial"] and MAP_HASH.fullmatch(app["map"])
                and app["mark_id"] > prior["mark_id"] and app["mark"] > max(prior["mark"], opened_qpc)
                and boundary["context"] & (FOCUSED | MINIMIZED | PLAY | LOADING) == FOCUSED | PLAY):
            return candidate
    raise ValueError("Readiness requires a fresh focused, loaded saved Mark")


@dataclass(frozen=True)
class Snapshot:
    session: str
    plan_sha256: str
    publisher: ProcessObject
    sequence: int
    phase: str
    ms: int
    qpc: int
    readiness_sha256: str | None = None
    start_sha256: str | None = None
    restored: bool = False
    owned_query: bool = False
    loss: int | None = None


@dataclass(frozen=True)
class ExitEvidence:
    process: ProcessObject
    exit: int
    ms: int


@dataclass(frozen=True)
class ReleaseEvidence:
    """Produced by the original-handle observers, never parsed from UI input."""

    session: str
    plan_sha256: str
    issuer: ProcessObject
    controller_exit: ExitEvidence
    watchdog_exit: ExitEvidence
    supervisor_exit: ExitEvidence
    query_ms: int
    query_name: str
    query_guid: str
    query_status: int
    query_only: bool
    target_owned: bool
    stop_status: int
    final_loss: int
    normal: bool
    watchdog_recovery: bool
    stop_qpc: int
    samples: tuple[tuple[int, int], ...]
    cue_exit: ExitEvidence | None = None


@dataclass(frozen=True)
class StartPermit:
    session: str
    plan_sha256: str
    readiness_sha256: str
    registration_sha256: str
    requested_ms: int

    @property
    def sha256(self):
        return digest(canonical(asdict(self)))


@dataclass(frozen=True)
class CueTask:
    preset: str
    active_qpc: int
    requested_ms: int

    def waveform(self):
        rate, frames, ramp = 16_000, 1536, 128
        hz, amplitude = CUE_TONES[self.preset]
        samples = bytearray()
        for index in range(frames):
            envelope = min(1, index / ramp, (frames - 1 - index) / ramp)
            sample = round(32767 * amplitude * envelope * math.sin(math.tau * hz * index / rate))
            samples.extend(struct.pack("<h", sample))
        header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(samples), b"WAVE", b"fmt ", 16,
                             1, 1, rate, 2 * rate, 2, 16, b"data", len(samples))
        return header + samples


@dataclass(frozen=True)
class CueResult:
    disposition: str
    completed_ms: int | None


def deliver_cue(task, runner):
    """Use the same single-request contract for the future isolated normal worker."""
    try:
        reply = runner(task.waveform(), deadline_ms=CUE_MS, memory_bytes=CUE_MEMORY, output_bytes=CUE_OUTPUT)
    except TimeoutError:
        return CueResult("timeout", None)
    except (OSError, ValueError):
        return CueResult("failed", None)
    if (type(reply) is not CueResult or not positive_int(reply.completed_ms)
            or not task.requested_ms <= reply.completed_ms <= task.requested_ms + CUE_MS
            or reply.disposition not in {"api-ok", "failed", "timeout"}):
        return CueResult("invalid-or-late", None)
    return reply


class Session:
    """Operator-facing phase and evidence interface for a single prepared attempt."""

    def __init__(self, plan, supervisor, controller, consent_ms, *, cue_worker=None):
        if (not positive_int(consent_ms) or not 0 < plan.consent_until_ms - consent_ms <= CONSENT_MS
                or len({plan.requester.identity, supervisor.identity, controller.identity}) != 3
                or len({plan.requester.actor.pid, plan.target.pid, supervisor.actor.pid, controller.actor.pid}) != 4
                or any(not proc.identity or proc.actor.elevated is not True or not positive_int(proc.actor.pid)
                       or not positive_int(proc.actor.creation) or proc.actor.account != plan.target.account
                       or proc.actor.desktop != plan.target.desktop
                       or proc.actor.image_sha256 != plan.package.background_sha256
                       for proc in (supervisor, controller))):
            raise PermissionError("Expired consent or unverified operator actors")
        if cue_worker is not None:
            worker = cue_worker.actor
            if (plan.cue == "off" or not cue_worker.identity
                    or cue_worker.identity in {plan.requester.identity, supervisor.identity, controller.identity,
                                               plan.target.process_object, plan.target.thread_object}
                    or worker.pid in {plan.requester.actor.pid, supervisor.actor.pid, controller.actor.pid, plan.target.pid}
                    or not positive_int(worker.pid) or not positive_int(worker.creation)
                    or worker.account != plan.target.account or worker.desktop != plan.target.desktop
                    or worker.elevated is not False or worker.image_sha256 != plan.package.background_sha256):
                raise PermissionError("Unverified normal notification worker")
        self.plan, self.supervisor, self.controller, self.consent_ms = plan, supervisor, controller, consent_ms
        self._plan_hash = plan.sha256
        directory = Path(plan.directory)
        directory.mkdir(exist_ok=False)
        with (directory / "operator-intent.json").open("xb") as claim:
            claim.write(canonical({"version": 1, "session": plan.session, "plan_sha256": self._plan_hash}))
        self._phase = "CONSENT"
        self._snapshot = None
        self._status_current = True
        self._readiness = self._registration = self._start = self._active = self._release = None
        self._pending_stop = self._cue_consumed = False
        self._analysis = None
        self._cue_worker = cue_worker
        self._cue_task = None
        self._cue_result = None
        self._cue = "disabled" if plan.cue == "off" else "unavailable" if cue_worker is None else None

    def mark_ready(self, root, folder):
        if self._phase != "READY" or self._pending_stop or self._readiness is not None:
            raise PermissionError("No waiting readiness phase")
        self._readiness = select_readiness(self._capture_root(root), self.plan, self._snapshot.qpc, folder)
        return self._readiness

    def _capture_root(self, root):
        if root != Path(self.plan.capture_directory):
            raise PermissionError("Capture path differs from the registered target")
        return root

    def register_handles(self, registration):
        if not self._status_current or self._phase != "ARMING" or self._pending_stop or self._registration is not None:
            raise PermissionError("No waiting original-handle registration")
        if registration.supervisor != self.supervisor or registration.controller != self.controller:
            raise PermissionError("Registration changed an original process object")
        registration.validate(self.plan, self.consent_ms)
        if self._cue_worker is not None and (
                registration.watchdog.identity == self._cue_worker.identity
                or registration.watchdog.actor.pid == self._cue_worker.actor.pid):
            raise PermissionError("Watchdog cannot be the notification worker")
        if not self._snapshot.ms <= registration.registered_ms < self._snapshot.ms + self.plan.budget.arm_ms:
            raise PermissionError("Watchdog registration missed the arming bound")
        self._registration = registration

    def watchdog_arm_deadline(self):
        if not self._status_current or self._phase != "ARMING":
            raise PermissionError("No current watchdog arm origin")
        return self._snapshot.ms + self.plan.budget.watchdog_ms

    def authorize_start(self, now_ms):
        if (not self._status_current or self._phase != "ARMING" or self._pending_stop or self._registration is None
                or self._start is not None or not positive_int(now_ms)
                or not self._registration.registered_ms <= now_ms < self._snapshot.ms + self.plan.budget.active_ms):
            raise PermissionError("Start requires timely original-handle registration")
        capture_capacity(Path(self.plan.capture_directory), self.plan.target.app_settings[11], 1)
        permit = StartPermit(self.plan.session, self._plan_hash, digest(self._readiness.raw),
                             digest(canonical(asdict(self._registration))), now_ms)
        with (Path(self.plan.directory) / "operator-start-intent.json").open("xb") as claim:
            claim.write(canonical(asdict(permit)))
        self._start = permit
        return permit

    def read_phase(self, raw, publisher, *, properties=None):
        """Ingest bound channel bytes and the publisher's original process object."""
        self.invalidate_phase()
        value = fields_from_json(raw, METADATA_LIMIT)
        if not exact_keys(value, "session plan_sha256 sequence phase ms qpc readiness_sha256 start_sha256 "
                                 "restored owned_query loss"):
            raise ValueError("Malformed operator phase receipt")
        snapshot = Snapshot(**value, publisher=publisher)
        self.observe(snapshot, properties=properties)
        return snapshot

    def invalidate_phase(self):
        """Record a failed channel read without declaring that capture stopped."""
        self._status_current = False

    def observe(self, snapshot, *, properties=None):
        self.invalidate_phase()
        last = self._snapshot
        if (snapshot.session != self.plan.session or snapshot.plan_sha256 != self._plan_hash
                or snapshot.publisher != self.controller or not positive_int(snapshot.sequence)
                or not positive_int(snapshot.ms) or not positive_int(snapshot.qpc)
                or not self.consent_ms <= snapshot.ms < self.consent_ms + self.plan.budget.observer_ms
                or (last and (snapshot.sequence <= last.sequence or snapshot.ms < last.ms or snapshot.qpc < last.qpc))
                or self._phase in {"STOPPED", "FAILED"}):
            raise PermissionError("Stale, foreign or contradictory phase snapshot")
        if snapshot.phase == "READY" and self._phase == "CONSENT":
            if snapshot.ms >= self.consent_ms + self.plan.budget.setup_ms:
                raise PermissionError("Readiness opened after setup deadline")
        elif snapshot.phase == "ARMING" and self._phase == "READY":
            if (self._readiness is None or snapshot.readiness_sha256 != digest(self._readiness.raw)
                    or snapshot.ms >= last.ms + self.plan.budget.readiness_ms):
                raise PermissionError("Arming did not bind a timely readiness Mark")
        elif snapshot.phase == "RECORDING" and self._phase == "ARMING":
            if (self._start is None or self._pending_stop or snapshot.start_sha256 != self._start.sha256
                    or not self._start.requested_ms <= snapshot.ms < last.ms + self.plan.budget.active_ms
                    or snapshot.qpc <= self._readiness.parsed()["mark"]
                    or snapshot.readiness_sha256 != digest(self._readiness.raw)
                    or snapshot.restored is not True or snapshot.owned_query is not True
                    or type(snapshot.loss) is not int or snapshot.loss != 0 or type(properties) is not dict):
                raise PermissionError("RECORDING lacks accepted owned samples and original handles")
            trace_path = Path(self.plan.directory) / "fixture.etl"
            validate_properties(self.plan.budget, self.plan.session, trace_path, properties)
            self._active = snapshot
        elif snapshot.phase == "STOPPING" and self._phase != "STOPPING":
            pass
        elif snapshot.phase == "FAILED":
            pass
        else:
            raise PermissionError("Invalid operator phase transition")
        self._phase, self._snapshot = snapshot.phase, snapshot
        self._status_current = True

    def request_stop(self):
        if self._phase not in {"STOPPED", "FAILED"}:
            self._pending_stop = True

    def take_cue(self, current, now_ms):
        """Called in order with the producer's current-phase/Stop arbitration."""
        if (not self._status_current or self._phase != "RECORDING" or self._pending_stop
                or self._cue_consumed or self._cue_worker is None
                or current != self._snapshot or current != self._active or not positive_int(now_ms)
                or not current.ms <= now_ms <= current.ms + self.plan.budget.poll_ms):
            return None
        self._cue_consumed = True
        self._cue_task = CueTask(self.plan.cue, current.qpc, now_ms)
        self._cue = "requested"
        return self._cue_task

    def finish_cue(self, task, result):
        if self._cue != "requested" or task != self._cue_task or type(result) is not CueResult or result.disposition not in {
                "api-ok", "failed", "timeout", "invalid-or-late"}:
            raise ValueError("Cue receipt does not match the issued request")
        self._cue = result.disposition
        self._cue_result = result

    def finish_release(self, evidence):
        registration, active = self._registration, self._active
        if self._phase != "STOPPING" or registration is None or active is None:
            raise PermissionError("No complete operator capture awaiting proof")
        child, watcher, supervisor = evidence.controller_exit, evidence.watchdog_exit, evidence.supervisor_exit
        worker = evidence.cue_exit
        samples = evidence.samples
        if (evidence.session != self.plan.session or evidence.plan_sha256 != self._plan_hash
                or evidence.issuer != self.supervisor or child.process != self.controller
                or watcher.process != registration.watchdog or supervisor.process != self.supervisor
                or any(type(item.exit) is not int or item.exit != 0 or not positive_int(item.ms)
                       for item in (child, watcher, supervisor))
                or not positive_int(evidence.query_ms) or not self._snapshot.ms <= min(child.ms, watcher.ms)
                or not max(child.ms, watcher.ms) <= evidence.query_ms <= supervisor.ms
                or supervisor.ms >= self.consent_ms + self.plan.budget.observer_ms
                or (worker is None) != (self._cue_worker is None)
                or (worker is not None and (worker.process != self._cue_worker or type(worker.exit) is not int
                    or not self.consent_ms <= worker.ms < self.consent_ms + self.plan.budget.observer_ms))
                or evidence.query_name != "McOsu-Controlled-" + self.plan.session
                or evidence.query_guid != self.plan.session or type(evidence.query_status) is not int
                or evidence.query_status != 4201 or evidence.query_only is not True
                or evidence.target_owned is not False or evidence.normal is not True
                or evidence.watchdog_recovery is not False
                or type(evidence.stop_status) is not int or evidence.stop_status != 0
                or type(evidence.final_loss) is not int or evidence.final_loss != 0
                or not positive_int(evidence.stop_qpc) or not 3 <= len(samples) <= self.plan.budget.max_ms + 1
                or samples[0] != (active.qpc, 0)
                or any(not positive_int(qpc) or type(lost) is not int or lost != 0 for qpc, lost in samples)
                or any(left[0] >= right[0] for left, right in zip(samples, samples[1:]))
                or not samples[-1][0] <= evidence.stop_qpc <= self._snapshot.qpc
                or (evidence.stop_qpc - active.qpc) * 1000 > self.plan.budget.max_ms * self.plan.target.qpf):
            raise PermissionError("Owned normal release or uninterrupted coverage is unverified")
        self._release = evidence
        self._phase = "STOPPED"
        self._pending_stop = False

    def view(self):
        phase = self._phase if self._status_current or self._phase in {"STOPPED", "FAILED"} else "STATUS UNVERIFIED"
        return {
            "version": 1, "session": self.plan.session, "phase": phase, "stop_pending": self._pending_stop,
            "release": "verified" if self._release is not None else "unverified",
            "cue": self._cue, "requested": dict(self.plan.requested),
            "cue_request": asdict(self._cue_task) if self._cue_task is not None else None,
            "cue_result": asdict(self._cue_result) if self._cue_result is not None else None,
            "applied": {"active_cue": self.plan.cue, "baseline_wait_ms": self.plan.baseline_wait_ms},
            "requested_budget": dict(self.plan.requested_budget),
            "budget": asdict(self.plan.budget), "source": self.plan.target.source,
            "app_image_sha256": self.plan.target.image_sha256, "app_settings": self.plan.target.app_settings,
            "owns_app": False, "consent_until_ms": self.plan.consent_until_ms,
            "tools_source": self.plan.package.source, "package_sha256": self.plan.package.manifest_sha256,
            "tools_tree": self.plan.package.tree,
            "reader_pair_sha256": self.plan.package.pair_sha256,
            "marked_answer": "analysis-admitted" if self._analysis is not None else "unavailable",
        }

    def select_evidence(self, root, *, folder=None):
        if self._release is None:
            raise PermissionError("Evidence selection requires verified owned release")
        lower, upper = self._release.samples[0][0], self._release.samples[-2][0]
        prior = self._readiness.parsed()
        limit = self.plan.target.app_settings[11]
        root = self._capture_root(root)
        capture_capacity(root, limit, 0)
        choices = []
        for candidate in candidate_marks(root, limit):
            app = candidate.parsed()
            if (matches(app, self.plan.target) and app["map"] == prior["map"] and app["epoch"] == prior["epoch"]
                    and app["mark_id"] > prior["mark_id"] and lower <= app["mark"] < upper
                    and (folder is None or candidate.folder == folder)):
                choices.append(candidate)
        if len(choices) > 1:
            raise ValueError("Select one eligible evidence Mark")
        return choices[0] if choices else None

    def admit_analysis(self, proof, mark, *, trace_sha256, trace_bytes):
        if self._release is None or self._analysis is not None or mark is None:
            raise PermissionError("No released, unused marked analysis authority")
        if not is_sha(trace_sha256) or not positive_int(trace_bytes) or trace_bytes >= self.plan.budget.etl_mib * MIB:
            raise ValueError("Trace metadata exceeds its declared bounds")
        lower, upper = self._release.samples[0][0], self._release.samples[-2][0]
        app, ready = mark.parsed(), self._readiness.parsed()
        if (not matches(app, self.plan.target) or app["map"] != ready["map"] or app["epoch"] != ready["epoch"]
                or app["mark_id"] <= ready["mark_id"] or not lower <= app["mark"] < upper):
            raise ValueError("Evidence Mark does not bind the verified capture")
        expected = {
            "version": 2, "operation": "operator-marked-analysis", "session": self.plan.session,
            "plan_sha256": self._plan_hash, "release_sha256": digest(canonical(asdict(self._release))),
            "mark_sha256": digest(mark.raw), "trace_sha256": trace_sha256, "trace_bytes": trace_bytes,
            "wire_schema": WIRE_SCHEMA, "pair_sha256": self.plan.package.pair_sha256,
            "reader_sha256": self.plan.package.reader_sha256,
        }
        if type(proof) is not dict or canonical(proof) != canonical(expected):
            raise PermissionError("Exact operator producer proof v2 required")
        raw = canonical(expected)
        report_directory = Path(self.plan.report_directory)
        report_directory.mkdir(exist_ok=False)
        with (report_directory / "operator-analysis-intent.json").open("xb") as claim:
            claim.write(raw)
        self._analysis = AnalysisAdmission(self.plan, lower, upper, mark, digest(raw))
        return self._analysis

    def save_marked_report(self, admission, slices):
        if admission is not self._analysis or self._analysis is None:
            raise PermissionError("Report needs this attempt's marked analysis admission")
        report = marked_report(admission, slices) | {"capture": self.view()}
        raw = canonical(report)
        if len(raw) > METADATA_LIMIT:
            raise ValueError("Operator report exceeded its byte bound")
        directory = Path(self.plan.report_directory)
        with (directory / REPORT_FILE).open("xb") as stream:
            stream.write(raw)
        return report


@dataclass(frozen=True)
class AnalysisAdmission:
    plan: AttemptPlan
    lower: int
    upper: int
    mark: Mark
    proof_sha256: str


def marked_report(admission, slices):
    """Summarize verified reducer spans after a separately qualified reader run."""
    app = admission.mark.parsed()
    rows = app["rows"]
    if len(slices) > admission.plan.budget.slices:
        raise ValueError("Scheduler slice budget exceeded")
    tail = admission.lower
    for span in slices:
        if (span["state"] not in STATES[:3] or not tail <= span["start"] < span["end"] <= admission.upper):
            raise ValueError("Scheduler slices escape their trusted interval")
        tail = span["end"]
    index = 0
    marked = None
    totals = dict.fromkeys(STATES, 0)
    durations = []
    scope_durations = {}
    complete = 0
    for row in rows:
        while index < len(slices) and slices[index]["end"] <= row["start"]:
            index += 1
        right = index
        while right < len(slices) and slices[right]["start"] < row["end"]:
            right += 1
        visible = slices[index:right]
        frame = reduce_span(row["start"], row["end"], visible)["ticks"]
        scopes = []
        marked_row = row["sequence"] == app["boundary"]
        edge = row["start"]
        for name, start, end in row["scopes"]:
            scope_durations.setdefault(name, []).append(end - start)
            if marked_row:
                if edge < start:
                    scopes.append({"name": "outside-recorded-app-scopes",
                                   "ticks": reduce_span(edge, start, visible)["ticks"]})
                scopes.append({"name": name, "ticks": reduce_span(start, end, visible)["ticks"]})
            edge = end
        if marked_row and edge < row["end"]:
            scopes.append({"name": "outside-recorded-app-scopes",
                           "ticks": reduce_span(edge, row["end"], visible)["ticks"]})
        durations.append(row["end"] - row["start"])
        for state in STATES:
            totals[state] += frame[state]
        complete += not frame["unknown"]
        if marked_row:
            status = "complete" if not frame["unknown"] else "partial" if visible else "unavailable"
            marked = {"status": status, "sequence": row["sequence"], "ticks": frame, "scopes": scopes}

    def distribution(values):
        ordered = sorted(values)
        return {"count": len(ordered), **{f"p{p}": ordered[math.ceil(len(ordered) * p / 100) - 1]
                                        for p in (50, 95, 99)}}

    return {
        "version": 1, "session": admission.plan.session, "source": app["source"],
        "proof_sha256": admission.proof_sha256, "qpf": app["qpf"],
        "trusted_qpc": [admission.lower, admission.upper], "app_qpc": [rows[0]["start"], rows[-1]["end"]],
        "mark_id": app["mark_id"], "marked_frame": marked,
        "history": {"observed_frames": app["observed"], "retained_frames": len(rows),
                    "complete_frames": complete, "partial_frames": len(rows) - complete,
                    "app_partial": app["partial"], "evicted_frames": app["evicted"],
                    "wall_ticks": sum(durations), "scheduler_ticks": totals,
                    "frame_ticks": distribution(durations),
                    "scope_ticks": {name: distribution(values) for name, values in scope_durations.items()}},
    }


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    show = commands.add_parser("settings", help="Show requested and effective operator preferences")
    show.add_argument("--preferences", type=Path, metavar="DIRECTORY",
                      help=f"Read {PREFERENCES_FILE} from a local preferences directory")
    show.add_argument("--save", action="store_true", help="Save the requested settings to the preferences directory")
    for spec in SETTINGS:
        show.add_argument(spec.flag, type=type(spec.default), choices=spec.choices or None,
                          help=f"{spec.help} Default {spec.default} {spec.unit}. Accepted {spec.domain}.")
    commands.add_parser("start", help="Check whether the protected capture route is available")
    reopen = commands.add_parser("reopen", help="Read an archived report without starting or resuming capture")
    reopen.add_argument("directory", type=Path)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "start":
            print(UNAVAILABLE)
            return 2
        if args.command == "reopen":
            report = fields_from_json(bounded_read(args.directory / REPORT_FILE, METADATA_LIMIT), METADATA_LIMIT)
            if (type(report) is not dict or type(report.get("version")) is not int or report["version"] != 1
                    or not uuid_text(report.get("session"))):
                raise ValueError("Unsupported archived operator report")
            output = {"mode": "read-only archive", "live_release": "unverified", "report": report}
        else:
            requested = read_preferences(args.preferences) if args.preferences is not None else {}
            requested.update({spec.key: getattr(args, spec.key) for spec in SETTINGS
                              if getattr(args, spec.key) is not None})
            output = {"version": 1, "requested": requested, "effective": settings(requested)}
            if args.save:
                if args.preferences is None:
                    raise ValueError("--save requires --preferences")
                save_preferences(args.preferences, requested)
        print(json.dumps(output, indent=2))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

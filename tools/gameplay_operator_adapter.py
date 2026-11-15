"""Offline call gates for the future owned capture and local status transport."""

from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from gameplay_operator import ProcessObject, ReleaseEvidence, Session, positive_int, prepare_attempt
from gameplay_operator_bootstrap import load_fixed
from gameplay_operator_package import canonical, is_sha
from gameplay_operator_route import WatchdogArm, verify_arm


@dataclass(frozen=True)
class OriginalEntry:
    supervisor: ProcessObject
    controller: ProcessObject
    consent_ms: int
    cue_worker: ProcessObject | None = None


def open_attempt(directory, approved_manifest, request, *, installation, target_inputs, consent):
    """Compose the exact package, target and intent before asking the injected consent port."""
    if not callable(installation) or not callable(consent):
        raise PermissionError("Required installed-route capability is missing")

    def launch(fixed):
        plan = prepare_attempt(request, package=fixed.package, **target_inputs)
        if Path(plan.directory).exists():
            raise FileExistsError("Protected capture attempt already exists")
        claim = Path(plan.report_directory).parent / (".capture-intent-" + plan.session + ".json")
        with claim.open("xb") as stream:
            stream.write(canonical(dict(session=plan.session, plan_sha256=plan.sha256)))
        entry = consent(fixed, plan)
        if type(entry) is not OriginalEntry:
            raise PermissionError("No original consent process objects")
        return Session(plan, entry.supervisor, entry.controller, entry.consent_ms, cue_worker=entry.cue_worker)

    return load_fixed(directory, approved_manifest, installation, launch)


@dataclass(frozen=True)
class LocalPeer:
    """Observation by the endpoint adapter, not a declaration in wire bytes."""

    endpoint: str
    original: ProcessObject
    local: bool
    protected: bool


@dataclass(frozen=True)
class Message:
    peer: LocalPeer
    session: str
    plan_sha256: str
    sequence: int
    kind: str
    payload: object = None


class CaptureChannel:
    """One ordered arbitration point for controller status, operator Stop and cue."""

    def __init__(self, session, endpoint, start_owned, stop_owned):
        if not is_sha(endpoint) or not callable(start_owned) or not callable(stop_owned):
            raise ValueError("Expected a registered local endpoint and owned controller capabilities")
        self.session, self.endpoint = session, endpoint
        self.start_owned, self.stop_owned = start_owned, stop_owned
        self._plan_hash = session.plan.sha256
        self._sequences = {}
        self._last_phase = None
        self._stop_sent = False
        self._lock = Lock()

    def receive(self, read):
        with self._lock:
            try:
                message = read()
                return self._consume(message)
            except (OSError, ValueError, TypeError, KeyError, OverflowError):
                self.session.invalidate_phase()
                self._last_phase = None
                raise

    def _consume(self, message):
        if type(message) is not Message or type(message.peer) is not LocalPeer:
            raise PermissionError("No authenticated local channel peer")
        peer = message.peer
        session = self.session
        authorities = {
            "phase": session.controller, "arm": session.supervisor, "start": session.controller,
            "stop": session.plan.requester, "release": session.supervisor,
        }
        if (type(message.kind) is not str or message.kind not in authorities
                or peer.original != authorities[message.kind] or peer.endpoint != self.endpoint
                or peer.local is not True or peer.protected is not True
                or message.session != session.plan.session or message.plan_sha256 != self._plan_hash
                or not positive_int(message.sequence)
                or message.sequence <= self._sequences.get(peer.original.identity, 0)):
            raise PermissionError("Foreign, substituted or replayed capture message")
        self._sequences[peer.original.identity] = message.sequence
        payload = message.payload
        if message.kind == "phase":
            raw, properties = payload
            self._last_phase = session.read_phase(raw, peer.original, properties=properties)
            return self._last_phase
        if message.kind == "arm":
            if type(payload) is not WatchdogArm:
                raise ValueError("Missing original watchdog arm evidence")
            session.register_handles(verify_arm(payload, session.watchdog_arm_deadline()))
            return None
        if message.kind == "start":
            permit = session.authorize_start(payload)
            return self.start_owned(permit)
        if message.kind == "release":
            if type(payload) is not ReleaseEvidence:
                raise ValueError("Missing independent release observation")
            session.finish_release(payload)
            self._last_phase = None
            return None
        if payload is not None or self._stop_sent or session.view()["phase"] in {"STOPPED", "FAILED"}:
            raise PermissionError("Stop cannot be replayed or issued after capture")
        self._stop_sent = True
        session.request_stop()
        self._last_phase = None
        return self.stop_owned(session.plan.session)

    def take_cue(self, now_ms):
        with self._lock:
            return self.session.take_cue(self._last_phase, now_ms)

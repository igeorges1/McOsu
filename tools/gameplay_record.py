"""Separately granted Windows gameplay route, reusing the reviewed 015 bindings."""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gameplay_attribution import APP_LIMIT, checked, read_app, read_app_bytes, read_json, HEX_ID
from gameplay_budget import Budget, MIB
from gameplay_collector import collect

PROFILE_HASH = "17e0fcb9c97f84c617180690305ae8b34026952a14f87825205f3f19ece91cdb"
BASE_HASH = "c41726676675ad2acf252bda678d7f48371073d286ce3ad4c77ae2e936647ae8"
OPS_HASH = "2c75ba54a6cf7686461c3fe0216d016607bf76dd7a29e92627e780c876c5e962"
TOKEN_HASH = "4e48b66801ca039705b734d435ad5aae1a4b8738ab7197aa2c0160f65ce5ac25"
SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
THREAD_QUERY_LIMITED_INFORMATION = 0x0800
MARK_FOLDER = re.compile(r"mark-[0-9]{1,20}-[0-9]{2}\Z")
MAP_HASH = re.compile(r"[0-9a-f]{32}\Z")
FOCUSED, MINIMIZED, PLAY, LOADING = 1, 2, 4, 16  # OsuPerformanceHistory::Context


def capture_entries(root, limit):
    """The app publishes into a small flat directory of exclusively created Mark folders."""
    try:
        attributes = root.lstat()
        if not stat.S_ISDIR(attributes.st_mode) or is_reparse(attributes):
            raise ValueError("Diagnostic capture folder is a reparse point")
        with os.scandir(root) as entries:
            return [entry for _, entry in zip(range(limit + 1), entries)]
    except FileNotFoundError:
        return []


def is_reparse(attributes):
    return getattr(attributes, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT


def ready_mark(root, spec, opened_qpc, checked_paths, receipt_directory=None):
    candidates = capture_entries(root, 12)
    if len(candidates) > 12:
        raise ValueError("Diagnostic capture folder exceeds the supported Mark inventory")
    for entry in sorted(candidates, key=lambda entry: entry.name):
        if not MARK_FOLDER.fullmatch(entry.name):
            continue
        path = Path(entry.path) / "gameplay.qpc"
        receipt = path.with_name("export.txt")
        if path in checked_paths:
            continue
        try:
            if (not entry.is_dir(follow_symlinks=False)
                    or is_reparse(entry.stat(follow_symlinks=False))):
                continue
            files = (path.lstat(), receipt.lstat())
            if any(not stat.S_ISREG(file.st_mode) or is_reparse(file) for file in files):
                continue
        except FileNotFoundError:
            continue  # The App has not yet atomically published this sidecar.
        checked_paths.add(path)
        try:
            with receipt.open("rb") as stream:
                report = stream.read(4097)
            if len(report) > 4096 or b"gameplay_qpc=saved" not in report.splitlines():
                continue
            with path.open("rb") as stream:
                companion = stream.read(APP_LIMIT + 1)
            mark = read_app_bytes(companion)
        except (OSError, ValueError):
            continue
        context = next(row["context"] for row in mark["rows"] if row["sequence"] == mark["boundary"])
        if (all(mark[key] == value for key, value in spec["identity"].items())
                and mark["mark_id"] > spec["baseline_mark"]["id"]
                and max(opened_qpc, spec["baseline_mark"]["qpc"]) < mark["mark"]
                and mark["status"] == "recording" and not mark["partial"] and MAP_HASH.fullmatch(mark["map"])
                and (context & (FOCUSED | MINIMIZED | PLAY | LOADING)) == (FOCUSED | PLAY)):
            if receipt_directory is not None:
                write_bytes(receipt_directory / "readiness.qpc", companion)
            return dict(id=mark["mark_id"], qpc=mark["mark"], epoch=mark["epoch"], folder=entry.name)
    return None


def open_app_thread(abi, tid, pid):
    handle = abi.OpenThread(SYNCHRONIZE | THREAD_QUERY_LIMITED_INFORMATION, False, tid)
    if not handle or abi.GetProcessIdOfThread(handle) != pid:
        if handle:
            abi.CloseHandle(handle)
        raise ValueError("App thread does not belong to the authenticated game process")
    return handle


def now_ms():
    return time.monotonic_ns() // 1_000_000


def write(path, obj):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(obj, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def write_bytes(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def grant_fields(config, session):
    source = Path(__file__).resolve().parent
    paths = [source / name for name in ("gameplay_record.py", "gameplay_collector.py", "gameplay_budget.py",
                                         "gameplay_attribution.py", "gameplay_process.py", "verification_process.py")]
    paths.append(source / "gameplay_raw.py")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with Path(sys.executable).open("rb") as stream:
        hashes["python.exe"] = hashlib.file_digest(stream, "sha256").hexdigest()
    return dict(operation="one-conditional-gameplay-recording", session=session,
                config_sha256=hashlib.sha256(config if isinstance(config, bytes) else config.read_bytes()).hexdigest(), source=hashes,
                profile_sha256=PROFILE_HASH, scope="present-disabled-SeSystemProfilePrivilege")


def authorize(config, grant):
    with config.open("rb") as stream:
        config_bytes = stream.read(65537)
    if len(config_bytes) > 65536:
        raise ValueError("Recording config exceeds its bound")
    spec = json.loads(config_bytes)
    budget = Budget.parse(spec["budget"])
    session = str(uuid.UUID(spec["session"]))
    if session != spec["session"] or session in (
        "8419329d-58bd-4aff-94fd-4a97c54b4d7e", "f9d206fc-7e8d-44ec-b3eb-f4b77d4c8a90",
        "042cbef8-bdc0-4247-94a0-9f9e7da28eaa",
    ):
        raise ValueError("A fresh canonical gameplay session is required")
    if "owns_app" in spec and type(spec["owns_app"]) is not bool:
        raise ValueError("Recording App ownership must be boolean")
    keys = ("pid", "tid", "creation", "qpf", "source")
    identity = spec["identity"]
    if set(identity) != set(keys) or any(type(identity[k]) is not int or identity[k] <= 0 for k in keys[:4]):
        raise ValueError("Incomplete gameplay process identity")
    if not isinstance(identity["source"], str) or not HEX_ID.fullmatch(identity["source"]):
        raise ValueError("Unknown gameplay build source")
    baseline = spec["baseline_mark"]
    if set(baseline) != {"id", "qpc", "folder_limit"} or (
            type(baseline["id"]) is not int or baseline["id"] <= 0
            or type(baseline["qpc"]) is not int or baseline["qpc"] <= 0
            or type(baseline["folder_limit"]) is not int or not 2 <= baseline["folder_limit"] <= 12):
        raise ValueError("Bound baseline Mark identity and report quota required")
    image = Path(spec["image"]).resolve(strict=True)
    checked(image, spec["image_sha256"], 128 * 1024 * 1024)
    with grant.open("rb") as stream:
        grant_bytes = stream.read(65537)
    if len(grant_bytes) > 65536 or json.loads(grant_bytes) != grant_fields(config_bytes, session):
        raise PermissionError("Exact gameplay run grant is missing or does not match")
    route = Path(spec["profile_route"]).resolve(strict=True)
    base = route.parent
    for folder, expected_hash, relative in (
        (route, PROFILE_HASH, True), (base, BASE_HASH, False),
        (base / "operations-007", OPS_HASH, False), (base / "token-preflight-013", TOKEN_HASH, True),
    ):
        manifest = folder / "FROZEN.json"
        checked(manifest, expected_hash, 128 * 1024)
        for entry in read_json(manifest, 128 * 1024)["files"]:
            member = folder / entry["path"] if relative else Path(entry["path"])
            if (member.stat().st_size != entry["bytes"]
                    or hashlib.sha256(member.read_bytes()).hexdigest() != entry["sha256"]):
                raise ValueError("Pinned route input length changed")
    return spec, budget, image, route, config_bytes, grant_bytes


def native_route(route, session):
    # Each mode is a separate pinned Python process. Only this new process's
    # module globals select the fresh UUID. The controlled files stay frozen.
    sys.path.insert(0, str(route))
    import profile_controller as native
    native.SESSION = session
    native.prior.nonmodal()
    return native


class WindowsAdapter:
    def __init__(self, native, spec, image, directory, invocation):
        self.native, self.spec, self.image = native, spec, image
        self.directory, self.invocation = directory, invocation
        self.watcher = None
        self.game = None
        self.thread = None
        self.token = None
        self.begin = None

    def prepare(self, session, path, budget):
        import ctypes as c
        from ctypes import wintypes as w
        from windows_scope import TokenQueries, prepare_start
        from sequence import eligible

        prior, etw = self.native.prior, self.native.etw
        game = prior.ABI.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, self.spec["identity"]["pid"])
        if not game:
            raise c.WinError(c.get_last_error())
        self.game = game
        try:
            query = prior.ABI.QueryFullProcessImageNameW
            query.argtypes = (w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD))
            query.restype = w.BOOL
            buffer = c.create_unicode_buffer(32768)
            size = w.DWORD(len(buffer))
            creation = prior.creation(game)
            if (creation != self.spec["identity"]["creation"]
                    or not query(game, 0, buffer, c.byref(size)) or Path(buffer.value).resolve() != self.image
                    or prior.ABI.WaitForSingleObject(game, 0) != 258):
                raise ValueError("Original running game process did not match its identity")
            abi = prior.ABI
            abi.OpenThread.argtypes, abi.OpenThread.restype = (w.DWORD, w.BOOL, w.DWORD), w.HANDLE
            abi.GetProcessIdOfThread.argtypes, abi.GetProcessIdOfThread.restype = (w.HANDLE,), w.DWORD
            self.thread = open_app_thread(abi, self.spec["identity"]["tid"], self.spec["identity"]["pid"])
            if os.getpid() == self.spec["identity"]["pid"]:
                raise ValueError("Controller cannot be the game process")
            frequency = c.c_int64()
            if not abi.QueryPerformanceFrequency(c.byref(frequency)) or frequency.value != self.spec["identity"]["qpf"]:
                raise ValueError("Collector and game QPC frequency did not match")
            checked(self.image, self.spec["image_sha256"], 128 * MIB)
            self.live_identity = dict(pid=self.spec["identity"]["pid"], creation=creation,
                                      tid=self.spec["identity"]["tid"], qpf=frequency.value,
                                      image=str(self.image), image_sha256=self.spec["image_sha256"])
            self.token = TokenQueries().observe()
            if (not eligible(self.token) or self.token["process"]["privilege"]["state"] != "disabled"):
                raise ValueError("Present-disabled profile privilege in an elevated administrator is required")
            name, guid, _ = self.native.identity(self.directory)
            self.ckcl = prior.check_inventory(self.directory, "before", etw.inventory(), name, guid, path)
            attempt = prepare_start(etw, guid, path)
            props = attempt.properties.props
            props.buffer_kib = budget.buffer_kib
            props.minimum = props.maximum = budget.buffers
            props.file_mib = budget.etl_mib
            attempt.restored = False
            return attempt
        except BaseException:
            self.close()
            raise

    def free_space(self):
        system = Path(os.environ["SystemRoot"]).anchor
        return shutil.disk_usage(self.directory).free, shutil.disk_usage(system).free

    def require_game(self):
        if any(self.native.prior.ABI.WaitForSingleObject(handle, 0) != 258 for handle in (self.game, self.thread)):
            raise ValueError("Original game process or App thread no longer active")

    def await_ready(self, setup_deadline, budget):
        root = self.image.parent / "timing-captures"
        if len(capture_entries(root, 12)) > self.spec["baseline_mark"]["folder_limit"] - 2:
            raise ValueError("Diagnostic capture folder must have room for readiness and trial Marks")
        self.require_game()
        opened_qpc, waiting = self.stop_clock()
        if waiting >= setup_deadline:
            raise ValueError("Readiness setup deadline missed")
        deadline = waiting + budget.readiness_ms
        write(self.directory / "gameplay-waiting.json", dict(session=self.spec["session"],
              identity=self.spec["identity"], origin_ms=waiting, origin_qpc=opened_qpc, deadline_ms=deadline))
        checked_paths = set()
        while now_ms() < deadline:
            self.require_game()
            mark = ready_mark(root, self.spec, opened_qpc, checked_paths, self.directory)
            if mark is not None:
                qpc, acknowledged = self.stop_clock()
                if mark["qpc"] <= qpc and acknowledged < deadline:
                    if min(self.free_space()) < budget.initial_free_mib * MIB:
                        raise ValueError("Initial free-space requirement was not met after readiness")
                    return waiting, acknowledged, mark
            self.wait_until(min(deadline, now_ms() + budget.poll_ms))
        return waiting, None, None

    def arm(self, attempt, latest, budget):
        prior = self.native.prior
        self.begin = now_ms()
        if self.begin >= latest:
            raise ValueError("Pre-arm deadline missed")
        self.deadline = (self.begin + budget.watchdog_ms) / 1000
        owner = self.token["caller"]
        args = [*self.invocation, "--watchdog", str(owner["pid"]), str(owner["creation_filetime"]), str(self.deadline)]
        flags = prior.watchdog_flags()
        prior.write(self.directory, "watchdog-request", {"argv": args})
        with (self.directory / "watchdog.stdout").open("xb") as stdout, (self.directory / "watchdog.stderr").open("xb") as stderr:
            self.watcher = subprocess.Popen(args, cwd=self.directory, stdin=subprocess.DEVNULL,
                                            stdout=stdout, stderr=stderr, creationflags=flags)
        actual = prior.watch_identity(self.watcher)
        limit = min(latest, self.begin + budget.arm_ms)
        arm = self.directory / "watchdog-armed.json"
        while not arm.is_file() and self.watcher.poll() is None and now_ms() < limit:
            time.sleep(.02)
        if not arm.is_file() or now_ms() >= limit:
            raise ValueError("Independent watchdog arm timed out")
        self.native.verify_arm(read_json(arm, 64 * 1024), actual, owner["pid"], owner["creation_filetime"], self.deadline)
        if prior.watch_identity(self.watcher) != actual:
            raise ValueError("Watchdog handle identity changed")
        self.watcher_identity = actual
        return self.begin

    def start_scoped(self, attempt, latest):
        from sequence import scoped_start
        native = self.native
        name, guid, output = native.identity(self.directory)
        if native.prior.check_inventory(self.directory, "armed-inventory", native.etw.inventory(), name, guid, output) != self.ckcl:
            raise ValueError("CKCL presence changed")
        self.require_game()
        self.control = native.Recording(self.directory, latest / 1000, self.watcher, self.watcher_identity)
        self.scope = {}
        try:
            scoped_start(self.control, attempt, self.token, self.scope)
            attempt.restored = self.scope.get("restored") is True
            if attempt.status != 0 or not attempt.handle.value:
                raise ValueError("Raw Start did not return an owned handle")
            self.control.record_start(attempt)
        finally:
            self.scope["raw_start"] = dict(invoked=attempt.invoked, status=attempt.status, handle=attempt.handle.value)
            self.native.prior.write(self.directory, "profile-scope", self.scope)

    def observe(self, attempt):
        self.control.require_restored(self.token)
        self.require_game()
        etw = self.native.etw
        _, guid, output = self.native.identity(self.directory)
        status, actual = etw.control(etw.QUERY, handle=attempt.handle.value, guid=guid)
        if status != 0 or actual["context"] != attempt.handle.value:
            raise ValueError("Owned handle query did not match")
        output_free, system_free = self.free_space()
        return actual, dict(ms=now_ms(), qpc=self.qpc(), written=actual["written"],
                            file_bytes=output.stat().st_size if output.exists() else 0,
                            output_free=output_free, system_free=system_free,
                            lost=sum(actual[k] for k in ("events_lost", "log_lost", "real_time_lost")))

    def qpc(self):
        import ctypes as c
        kernel = c.WinDLL("kernel32", use_last_error=True)
        tick = c.c_int64()
        if not kernel.QueryPerformanceCounter(c.byref(tick)):
            raise c.WinError(c.get_last_error())
        return tick.value

    def stop_clock(self):
        return self.qpc(), now_ms()

    def active_receipt(self, result):
        self.native.prior.write(self.directory, "gameplay-active", {
            **result, "identity": self.spec["identity"], "image_sha256": self.spec["image_sha256"],
            "live_identity": self.live_identity,
        })

    def wait_until(self, when):
        time.sleep(max(0, when - now_ms()) / 1000)

    def release(self, attempt):
        native = self.native
        result = {}
        if attempt.status == 0 and attempt.handle.value:
            native_stop = {}
            self.control.cleanup(attempt.handle.value, self.token, native_stop)
            result.update(stop=native_stop.get("status"), after_query=native_stop.get("after_query"),
                          final_loss=sum(native_stop["properties"][k] for k in ("events_lost", "log_lost", "real_time_lost")))
        if self.watcher is not None and not (self.directory / "start-intent.json").exists():
            native.prior.cleanup_unstarted(self.directory, self.watcher)
        result["start_invoked"] = attempt.invoked
        if result.get("stop") == 0 and result.get("after_query") == 4201:
            result["watchdog_exit"] = self.watcher.wait(timeout=max(1, self.deadline + 3 - time.monotonic()))
            name, guid, output = native.identity(self.directory)
            inventory = native.prior.classify_inventory(native.etw.inventory(), name, guid, output)
            native.prior.write(self.directory, "after-policy", inventory)
            if inventory["conflicts"] or bool(inventory["expected_coexistence"]) != self.ckcl:
                raise ValueError("Final collector inventory differed")
            result["etl_bytes"] = output.stat().st_size
        return result

    def close(self):
        for handle in (self.thread, self.game):
            if handle:
                self.native.prior.ABI.CloseHandle(handle)
        self.thread = self.game = None


def main():
    entry_ms = now_ms()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("grant", type=Path)
    parser.add_argument("output", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--observe", action="store_true")
    modes.add_argument("--describe-grant", action="store_true")
    modes.add_argument("--child", type=int)
    modes.add_argument("--watchdog", nargs=3)
    args = parser.parse_args()
    config, grant, output = (p.resolve() for p in (args.config, args.grant, args.output))
    if args.describe_grant:
        spec = read_json(config, 64 * 1024)
        Budget.parse(spec["budget"])
        print(json.dumps(grant_fields(config, str(uuid.UUID(spec["session"]))), indent=2))
        return 0
    spec, budget, image, route, config_bytes, grant_bytes = authorize(config, grant)
    if os.name != "nt":
        raise ValueError("Windows gameplay collector required")
    invocation = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), str(config), str(grant), str(output)]
    pins = dict(config_sha256=hashlib.sha256(config_bytes).hexdigest(),
                grant_sha256=hashlib.sha256(grant_bytes).hexdigest())
    if args.observe:
        return observe(invocation, output, budget, route, pins)
    if not (output / "request.json").is_file() or Path.cwd() != output:
        raise PermissionError("No matching one-shot observer")
    request = read_json(output / "request.json", 64 * 1024)
    if request["invocation"] != invocation or request["recording_inputs"] != pins:
        raise PermissionError("Observer command or recording inputs did not match")
    native = native_route(route, spec["session"])
    if args.watchdog:
        expected = read_json(output / "watchdog-request.json", 64 * 1024)
        if expected["argv"] != [*invocation, "--watchdog", *args.watchdog] or not (output / "child.intent").is_file():
            raise PermissionError("Watchdog command did not match")
        (output / "watchdog.intent").touch(exist_ok=False)
        pid, creation, deadline = args.watchdog
        return native.recovery(output, int(pid), int(creation), float(deadline))
    if args.child is None or args.child != request["origin_ms"]:
        raise PermissionError("Use the one-shot observer")
    (output / "child.intent").touch(exist_ok=False)
    adapter = WindowsAdapter(native, spec, image, output, invocation)
    try:
        _, _, path = native.identity(output)
        write_bytes(output / "recording-config.json", config_bytes)
        write_bytes(output / "recording-grant.json", grant_bytes)
        child = dict(pid=os.getpid(), creation=native.prior.creation(native.prior.ABI.GetCurrentProcess()),
                     entry_ms=entry_ms, session=spec["session"], **pins)
        write(output / "child-identity.json", child)
        result = collect(adapter, budget, spec["session"], path, entry_ms)
        result["producer"] = child
        result["controller_entry_ms"] = entry_ms
        result["controller_end_ms"] = now_ms()
        if result.get("ledger") and result["controller_end_ms"] > result["ledger"]["watchdog_ms"]:
            result.update(stop_reason="finalization-deadline", incomplete=True)
        write(output / "controller.json", result)
        return 0 if not result["incomplete"] else 3
    finally:
        adapter.close()


def observe(invocation, output, budget, route, pins):
    import ctypes as c
    import importlib.util
    from ctypes import wintypes as w
    from verification_process import nonmodal
    nonmodal()
    # Reviewed ShellExecute structure and process observer declarations.
    entry = importlib.util.spec_from_file_location("profile_observer", route / "launch_profile.py")
    prior = importlib.util.module_from_spec(entry)
    entry.loader.exec_module(prior)
    shape = prior.load_shell_shape()
    shell = prior.api(c.WinDLL("shell32", use_last_error=True), "ShellExecuteExW", w.BOOL, c.POINTER(shape))
    output.mkdir(exist_ok=False)
    origin = now_ms()
    write(output / "request.json", dict(invocation=invocation, origin_ms=origin, budget=asdict(budget),
                                        recording_inputs=pins))
    info = shape()
    info.cbSize, info.fMask = c.sizeof(info), 0x140
    info.lpVerb, info.lpFile = "runas", invocation[0]
    info.lpParameters = subprocess.list2cmdline([*invocation[1:], "--child", str(origin)])
    info.lpDirectory, info.nShow = str(output), 0
    report = dict(disposition="pending-cleanup")
    try:
        if not shell(c.byref(info)):
            report.update(disposition="elevation-refused", error=c.get_last_error())
            return 2
        after_prompt = now_ms()
        report.update(pid=prior.pid_of(info.hProcess), creation=prior.creation(info.hProcess),
                      after_prompt_ms=after_prompt, observer_deadline_ms=after_prompt + budget.observer_ms,
                      termination_wait_ms=budget.termination_ms)
        wait = prior.wait(info.hProcess, budget.observer_ms)
        if wait == 258:
            report["timeout"] = True
            if prior.terminate(info.hProcess, 124):
                wait = prior.wait(info.hProcess, budget.termination_ms)
        report["wait"] = wait
        code = w.DWORD()
        if wait == 0 and prior.exit_code(info.hProcess, c.byref(code)):
            report.update(exit=code.value, disposition="controller-exited-review-release")
            child = output / "child-identity.json"
            if child.is_file():
                child_id = read_json(child, 64 * 1024)
                if ((child_id["pid"], child_id["creation"]) != (report["pid"], report["creation"])
                        or any(child_id[key] != value for key, value in pins.items())):
                    raise ValueError("Observed controller identity does not match the child")
                report["child"] = child_id
            elif code.value == 0:
                raise ValueError("Successful controller is missing its identity")
            return code.value
        return 1
    except Exception as error:
        report["error"] = repr(error)
        if info.hProcess and "wait" not in report:
            status = prior.wait(info.hProcess, budget.observer_ms)
            if status == 258 and prior.terminate(info.hProcess, 124):
                status = prior.wait(info.hProcess, budget.termination_ms)
            report["wait"] = status
        return 1
    finally:
        if info.hProcess:
            prior.close(info.hProcess)
        write(output / "observer.json", report)


def collection_summary(controller, observer, qpf):
    if not controller:
        reason = "consent declined or unavailable" if observer.get("disposition") == "elevation-refused" else (
            "observer deadline passed" if observer.get("timeout") else "controller receipt unavailable")
        return f"INCOMPLETE — {reason}. Capture time unavailable. Contact the coordinator before any retry."
    reason = controller.get("stop_reason", "unknown")
    label = {
        "target": "target reached",
        "trace-budget-forecast": "near-term forecast reached the trace budget",
        "trace-budget-observed": "observed trace bytes plus buffer allowance reached the trace budget",
        "low-space": "output or system disk free space fell below the live floor",
        "readiness-timeout": "no eligible in-game readiness Mark saved before the deadline",
        "etl-cap": "final ETL reached the file cap",
        "reported-loss": "logger reported event or buffer loss",
        "final-reported-loss": "logger reported loss at finalization",
    }.get(reason, reason.replace("-", " "))
    elapsed = ("Capture did not record an active timestamp." if controller.get("start_invoked") is not False
               else "Capture did not become active.")
    if "active_qpc" in controller and "stop_request_qpc" in controller:
        duration = (controller["stop_request_qpc"] - controller["active_qpc"]) / qpf
        if duration >= 0:
            elapsed = f"Active to Stop request {duration:.3f} s."
    released = controller.get("status") == "controller-reports-release"
    have_trace = released and controller.get("etl_bytes", 0) > 0
    if controller.get("incomplete") or observer.get("exit") != 0 or observer.get("timeout"):
        outcome = "INCOMPLETE (partial trace retained)" if have_trace else "INCOMPLETE"
    else:
        outcome = "Collection target reached"
    space = ""
    polls = controller.get("polls", [])
    last = polls[-1] if polls else controller.get("active_sample", {})
    pressure = controller.get("trace_pressure", {})
    if reason.startswith("trace-budget-") and pressure:
        forecast = pressure["projected_bytes"]
        projected = f", projected {forecast / MIB:.1f} MiB" if forecast is not None else ""
        space = (f" Trace occupancy incl. buffers {pressure['occupied_bytes'] / MIB:.1f} MiB{projected},"
                 f" threshold {pressure['early_bytes'] / MIB:.1f} MiB.")
    if reason.startswith("trace-budget-") or reason == "low-space":
        if last:
            space += f" Lowest disk free {min(last['output_free'], last['system_free']) / MIB:.1f} MiB."
    if controller.get("start_invoked") is False and not controller.get("cleanup_error"):
        next_step = "Start was never invoked. Report the result to the coordinator before any retry."
    elif released:
        next_step = "Controller reports release. Wait for independent release verification. Do not retry."
    else:
        next_step = "Release unconfirmed. Contact the coordinator for independent verification. Do not retry."
    return f"{outcome} — {label}. {elapsed}{space} {next_step}"


def seal(directory, app, absence, bundle, *, raw_query=None):
    """Bind saved outputs to a coordinator's fresh exact-session query receipt."""
    from gameplay_attribution import read_app

    controller = read_json(directory / "controller.json", 1024 * 1024)
    active = read_json(directory / "gameplay-active.json", 64 * 1024)
    observer = read_json(directory / "observer.json", 64 * 1024)
    independent = read_json(absence, 64 * 1024)
    session = controller["session"]
    etl = directory / "fixture.etl"
    budget = Budget.parse(controller["budget"])
    def hash_file(path, maximum):
        if path.is_symlink() or not 0 < path.stat().st_size <= maximum:
            raise ValueError(f"Unusable capture input: {path}")
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    if (controller["status"] != "controller-reports-release" or controller["incomplete"]
            or controller["stop"] != 0 or controller["after_query"] != 4201
            or observer.get("exit") != 0 or observer.get("timeout")
            or independent["session"] != session or independent["name"] != "McOsu-Controlled-" + session
            or independent["status"] != 4201 or independent["remaining_owned_processes"] != []
            or active["session"] != session or active["budget"] != controller["budget"]
            or etl.stat().st_size != controller["etl_bytes"] or etl.stat().st_size >= budget.etl_mib * 1024**2):
        raise ValueError("Exact independently verified normal release is required")
    if app.parent != directory or bundle.parent != directory:
        raise ValueError("Stage the companion in the owned collection directory")
    sidecar = read_app(app)
    if active["identity"] != {key: sidecar[key] for key in ("pid", "creation", "tid", "qpf", "source")}:
        raise ValueError("App sidecar does not match authenticated active process")
    if (active["readiness"] != controller["readiness"]
            or not controller["readiness"]["mark"]["id"] < sidecar["mark_id"]
            or not controller["readiness"]["mark"]["qpc"] < active["active_qpc"] <= sidecar["mark"] < controller["stop_request_qpc"]):
        raise ValueError("Trial Mark must follow readiness inside the actual capture window")
    etl_sha = hash_file(etl, budget.etl_mib * 1024**2)
    release = directory / "gameplay-release.json"
    result = {**controller, "status": "normal-owned-release-verified", "etl_sha256": etl_sha,
              "identity": active["identity"], "image_sha256": active["image_sha256"],
              "independent_query": independent["status"], "independent_receipt_sha256": hash_file(absence, 64 * 1024)}
    # Poll details remain in controller.json; the analysis receipt stays small.
    result.pop("polls", None)
    payload = dict(session=session, budget=controller["budget"], etl=etl.name, etl_sha256=etl_sha,
                   app=app.name, app_sha256=hash_file(app, APP_LIMIT), release=release.name)
    if raw_query is not None:
        from gameplay_raw import collect_proof, validate_proof
        proof = collect_proof(directory, absence, raw_query)
        validate_proof(directory, proof, payload, budget, etl, result, sidecar)
        payload["raw_evidence"] = proof
    write(release, result)
    payload["release_sha256"] = hash_file(release, 64 * 1024)
    write(bundle, payload)



if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--seal":
        seal(*(Path(arg).resolve() for arg in sys.argv[2:]))
    elif len(sys.argv) == 7 and sys.argv[1] == "--seal-raw":
        directory, app, absence, query, bundle = (Path(arg).resolve() for arg in sys.argv[2:])
        seal(directory, app, absence, bundle, raw_query=query)
    else:
        raise SystemExit(main())

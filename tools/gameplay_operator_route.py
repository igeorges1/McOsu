"""Runtime-only policy extracted from the controlled 015 route.

The origin and intentional differences are listed in the package provenance.
No legacy fixture or native bindings are imported.
"""

from dataclasses import dataclass

from gameplay_operator import HandleRegistration


def eligible(report):
    """Equivalent to sequence.eligible for well-formed token observations."""
    if type(report) is not dict or type(report.get("thread")) is not dict or type(report.get("process")) is not dict:
        return False
    process = report["process"]
    return (report.get("status") == "observed" and report.get("effective_source") == "process"
            and report["thread"].get("status") == "no-token" and type(process.get("token_type")) is int
            and process["token_type"] == 1 and process.get("elevated") is True
            and report.get("enabled_administrator") is True)


@dataclass(frozen=True)
class WatchdogArm:
    registration: HandleRegistration
    controller_pid: int
    controller_creation: int
    watchdog_pid: int
    watchdog_creation: int
    deadline_ms: int
    outside_all_jobs: bool
    context: dict


def verify_arm(arm, expected_deadline_ms):
    """Adapt profile_controller.verify_arm to the new original-object roles."""
    controller = arm.registration.controller.actor
    watchdog = arm.registration.watchdog.actor
    caller = arm.context.get("caller") if type(arm.context) is dict else None
    if (arm.outside_all_jobs is not True or type(arm.deadline_ms) is not int
            or arm.deadline_ms != expected_deadline_ms or not eligible(arm.context) or type(caller) is not dict
            or (arm.controller_pid, arm.controller_creation) != (controller.pid, controller.creation)
            or (arm.watchdog_pid, arm.watchdog_creation) != (watchdog.pid, watchdog.creation)
            or (caller.get("pid"), caller.get("creation_filetime")) != (watchdog.pid, watchdog.creation)):
        raise PermissionError("Watchdog arm or control role identity mismatch")
    return arm.registration

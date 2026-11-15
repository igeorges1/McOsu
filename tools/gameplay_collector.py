"""Gameplay-specific collection contract for the separately granted Windows route.

The operating adapter owns elevation, token restoration, independent watchdog,
native handles and filesystem publication. The policy owns gameplay limits and
normal/emergency release disposition. Importing or validating config is offline.
"""

import argparse
from collections import deque
from dataclasses import asdict
import json
from pathlib import Path
import uuid

from gameplay_budget import Budget, MIB, poll_decision, trace_pressure

PROFILE = 0x01000817
MODE = 0x02000001
MODE_RETURNED = 0x02400001  # Windows may add the system logger's internal flag.


def validate_properties(budget, session, path, properties):
    if (properties["name"] != "McOsu-Controlled-" + session or properties["guid"] != session
            or Path(properties["file"]).resolve() != path.resolve()
            or properties["context"] <= 0 or properties["clock"] != 1
            or properties["mode"] not in (MODE, MODE_RETURNED) or properties["keywords"] != PROFILE
            or properties["file_mib"] != budget.etl_mib or properties["buffer_kib"] != budget.buffer_kib
            or properties["minimum"] != budget.buffers or properties["maximum"] != budget.buffers
            or not 0 < properties["number"] <= budget.buffers):
        raise ValueError("Effective gameplay logger properties changed or are unsupported")


def collect(adapter, budget, session, path, entry):
    """Run one owned attempt through an adapter with the 015 scope/recovery contract."""
    budget.validate()
    if str(uuid.UUID(session)) != session or path.exists():
        raise ValueError("Invalid session or occupied ETL path")
    result = {"session": session, "budget": asdict(budget), "status": "pending-cleanup",
              "incomplete": True, "polls": []}
    attempt = None
    phase = "setup"
    try:
        attempt = adapter.prepare(session, path, budget)
        if min(adapter.free_space()) < budget.initial_free_mib * MIB:
            raise ValueError("Initial free-space requirement was not met")
        phase = "readiness"
        waiting, acknowledged, ready_mark = adapter.await_ready(entry + budget.setup_ms, budget)
        result["readiness"] = dict(origin_ms=waiting, deadline_ms=waiting + budget.readiness_ms,
                                   acknowledged_ms=acknowledged, mark=ready_mark)
        if ready_mark is None:
            result["stop_reason"] = "readiness-timeout"
            return result
        phase = "arm"
        latest_arm = entry + budget.setup_ms + acknowledged - waiting
        if not entry <= waiting < entry + budget.setup_ms or not waiting <= acknowledged < waiting + budget.readiness_ms:
            raise ValueError("Readiness deadline missed")
        arm = adapter.arm(attempt, latest_arm, budget)
        if not acknowledged <= arm < latest_arm:
            raise ValueError("Pre-arm deadline missed")
        phase = "start"
        adapter.start_scoped(attempt, arm + budget.active_ms)
        if not attempt.restored:
            raise ValueError("Privilege restoration was not verified")
        properties, sample = adapter.observe(attempt)
        validate_properties(budget, session, path, properties)
        if (any(type(sample.get(key)) is not int or sample[key] < 0
                for key in ("ms", "qpc", "written", "file_bytes", "output_free", "system_free", "lost"))
                or sample["qpc"] <= ready_mark["qpc"]):
            raise ValueError("Invalid initial counters or active QPC")
        ledger = budget.ledger(entry, waiting, acknowledged, arm, sample["ms"])
        result.update(ledger=ledger, active_qpc=sample["qpc"], active_properties=properties, active_sample=sample)
        result["trace_pressure"] = trace_pressure(budget, ledger, sample)
        if sample["lost"]:
            result["stop_reason"] = "reported-loss"
            return result
        if min(sample["output_free"], sample["system_free"]) < budget.live_free_mib * MIB:
            result["stop_reason"] = "low-space"
            return result
        if result["trace_pressure"]["occupied_bytes"] >= budget.early_mib * MIB:
            result["stop_reason"] = "trace-budget-observed"
            return result
        phase = "collect"
        adapter.active_receipt(result)
        history = deque([sample])
        previous = sample
        while True:
            adapter.wait_until(min(previous["ms"] + budget.poll_ms, ledger["stop_request_ms"]))
            properties, sample = adapter.observe(attempt)
            validate_properties(budget, session, path, properties)
            # Keep the newest anchor at least one forecast window old.
            while len(history) > 1 and history[1]["ms"] <= sample["ms"] - budget.forecast_window_ms:
                history.popleft()
            reason = poll_decision(budget, ledger, previous, sample, history[0])
            if type(sample.get("qpc")) is not int or sample["qpc"] <= previous["qpc"]:
                reason = "invalid-qpc"
            result["polls"].append(sample)
            if reason in (None, "target", "trace-budget-observed", "trace-budget-forecast"):
                result["trace_pressure"] = trace_pressure(budget, ledger, sample, history[0])
            if reason is not None:
                result.update(stop_reason=reason, incomplete=reason != "target")
                break
            history.append(sample)
            previous = sample
    except Exception as error:
        result.setdefault("stop_reason", phase + "-failed")
        result["error"] = repr(error)
    finally:
        # The adapter must keep the native out-handle in attempt, including
        # when the Start/restore path throws. Ambiguous starts go to watchdog.
        try:
            result["stop_request_qpc"], result["stop_request_ms"] = adapter.stop_clock()
            if result.get("ledger") and result["stop_request_ms"] > result["ledger"]["hard_collection_ms"]:
                result.update(stop_reason="hard-deadline", incomplete=True)
            if result.get("active_qpc") is not None and result["stop_request_qpc"] <= result["active_qpc"]:
                result.update(stop_reason="invalid-stop-qpc", incomplete=True)
        except Exception as error:
            result["stop_clock_error"] = repr(error)
            result.update(stop_reason="stop-clock-failed", incomplete=True)
        if attempt is not None:
            try:
                result.update(adapter.release(attempt))
            except Exception as error:
                result["cleanup_error"] = repr(error)
        if result.get("stop") == 0 and result.get("after_query") == 4201 and result.get("watchdog_exit") == 0:
            result["status"] = "controller-reports-release"
            if result.get("final_loss") != 0:
                result.update(stop_reason="final-reported-loss", incomplete=True)
            elif result.get("etl_bytes", 0) >= budget.etl_mib * MIB:
                result.update(stop_reason="etl-cap", incomplete=True)
            elif not result.get("etl_bytes"):
                result.update(stop_reason="missing-etl", incomplete=True)
        else:
            result["incomplete"] = True
            if result.get("stop_reason") == "target":
                result["stop_reason"] = "release-unconfirmed"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate", type=Path, help="Validate and print resolved gameplay budget JSON", required=True)
    args = parser.parse_args()
    try:
        budget = Budget.parse(json.loads(args.validate.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        parser.exit(2, str(error) + "\n")
    print(json.dumps(asdict(budget), indent=2))


if __name__ == "__main__":
    main()

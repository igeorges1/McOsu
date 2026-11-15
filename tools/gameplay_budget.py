"""Validated settings and monotonic decisions for an owned gameplay logger."""

from dataclasses import asdict, dataclass, field, fields

MIB = 1024 * 1024


def setting(default, unit, minimum, maximum, help_text, *, choices=()):
    return field(default=default, metadata=dict(unit=unit, minimum=minimum,
                 maximum=maximum, choices=choices, help=help_text))


@dataclass(frozen=True)
class Budget:
    target_ms: int = setting(20000, "ms", 1000, 30000, "Normal Stop target from active-ready.")
    max_ms: int = setting(25000, "ms", 1000, 30000, "Hard collection ceiling from active-ready.")
    setup_ms: int = setting(5000, "ms", 1000, 10000, "Combined pre-readiness setup and watchdog arm-origin allowance from elevated child entry, excluding the readiness wait.")
    readiness_ms: int = setting(45000, "ms", 1000, 120000, "Maximum wait for a new saved in-game Mark after elevated setup, before watchdog arm or ETW Start.")
    arm_ms: int = setting(2000, "ms", 250, 3000, "Maximum authenticated watchdog handshake.")
    active_ms: int = setting(3000, "ms", 251, 5000, "Latest Start, restoration and active-ready from watchdog origin.")
    finalize_ms: int = setting(6000, "ms", 3000, 10000, "Normal Stop and finalization reserve before watchdog intervention.")
    watchdog_ms: int = setting(34000, "ms", 4251, 50000, "Independent watchdog intervention deadline from its origin.")
    observer_ms: int = setting(90000, "ms", 9251, 185000, "Original controller handle wait after consent returns.")
    termination_ms: int = setting(3000, "ms", 2000, 5000, "Observer termination follow-up wait.")
    poll_ms: int = setting(250, "ms", 100, 1000, "Interval between effective logger and storage checks.")
    poll_late_ms: int = setting(250, "ms", 1, 1000, "Permitted poll lateness before stopping incomplete.")
    etl_mib: int = setting(256, "MiB", 32, 256, "Sequential logger file cap and exclusive reader admission limit.")
    early_mib: int = setting(128, "MiB", 1, 255, "Observed or near-term projected written and buffered ETL early-stop threshold.")
    forecast_window_ms: int = setting(1000, "ms", 250, 5000, "Minimum history for a rolling trace-growth forecast. Before this, only observed occupancy applies.")
    forecast_horizon_ms: int = setting(2000, "ms", 250, 5000, "Maximum forecast lookahead, clipped to remaining target time.")
    buffer_kib: int = setting(64, "KiB", 32, 64, "Requested logger buffer size.", choices=(32, 64))
    buffers: int = setting(128, "buffers", 16, 128, "Requested minimum and maximum logger buffer count.")
    initial_free_mib: int = setting(1024, "MiB", 234, 16384, "Pre-start free floor on both output and system volumes.")
    live_free_mib: int = setting(640, "MiB", 234, 16384, "In-capture free floor on both volumes.")
    rundown_mib: int = setting(64, "MiB", 8, 128, "File-cap headroom for stop and rundown growth.")
    app_mib: int = setting(64, "MiB", 1, 128, "Free-space reserve for the App capture.")
    copy_mib: int = setting(0, "MiB", 0, 256, "Additional free-space reserve for any authorized artifact copy.")
    report_mib: int = setting(16, "MiB", 1, 32, "Combined retained analysis streams, frames and receipts. Also bounds retained raw event rows.")
    slices: int = setting(65536, "slices", 1, 131072, "Maximum retained scheduler state slices.")
    analysis_ms: int = setting(15000, "ms", 1000, 60000, "Owned decoder process deadline.")
    analysis_memory_mib: int = setting(1024, "MiB", 256, 2048, "Owned Windows Job memory limit.")

    RELATIONSHIPS = (
        "Target must not exceed the hard collection duration. Arm must fit setup and precede active-ready.",
        "Watchdog must cover active-ready, maximum collection and finalization. Observer must cover setup, readiness, watchdog, termination observation and a 1000 ms margin.",
        "Buffer size times count cannot exceed 8 MiB. The early threshold plus one full buffer backlog and rundown reserve must fit strictly below the ETL cap.",
        "Forecast uses the newest sample at least one window old and looks ahead at most the configured horizon or remaining target time. Observed occupancy is checked every sample, including startup.",
        "Initial free space must cover the live floor. The live floor must reserve the ETL cap, app output, copies, report and 200 MiB for system storage.",
    )

    @classmethod
    def parse(cls, values):
        defaults = asdict(cls())
        if not isinstance(values, dict) or values.keys() - defaults.keys():
            raise ValueError("Unknown gameplay budget setting")
        if any(type(value) is not int for value in values.values()):
            raise ValueError("Gameplay budgets use integer units")
        result = cls(**values)
        result.validate()
        return result

    @property
    def backlog_bytes(self):
        return self.buffer_kib * 1024 * self.buffers

    def validate(self):
        for spec in fields(self):
            value = getattr(self, spec.name)
            domain = spec.metadata
            if (type(value) is not int or not domain["minimum"] <= value <= domain["maximum"]
                    or (domain["choices"] and value not in domain["choices"])):
                raise ValueError(f"Unsupported gameplay budget value: {spec.name}")
        if not (self.target_ms <= self.max_ms and self.arm_ms <= self.setup_ms
                and self.arm_ms < self.active_ms
                and self.active_ms + self.max_ms + self.finalize_ms <= self.watchdog_ms
                and self.setup_ms + self.readiness_ms + self.watchdog_ms + self.termination_ms + 1000 <= self.observer_ms):
            raise ValueError("Incoherent gameplay deadline ledger")
        if not (self.backlog_bytes <= 8 * MIB
                and self.early_mib * MIB + self.backlog_bytes + self.rundown_mib * MIB < self.etl_mib * MIB):
            raise ValueError("Incoherent ETL or poll budget")
        reserve = self.etl_mib + self.app_mib + self.copy_mib + self.report_mib + 200
        if not reserve <= self.live_free_mib <= self.initial_free_mib:
            raise ValueError("Free space must cover ETL, app, copy, report and system reserve")

    def ledger(self, entry, waiting, acknowledged, arm, active):
        """Timestamps are integer milliseconds in one monotonic clock domain."""
        if not (entry <= waiting < entry + self.setup_ms
                and waiting <= acknowledged < waiting + self.readiness_ms
                and acknowledged <= arm < entry + self.setup_ms + acknowledged - waiting
                and arm <= active <= arm + self.active_ms):
            raise ValueError("Gameplay setup, readiness or active deadline missed")
        watchdog = arm + self.watchdog_ms
        return {
            "controller_entry_ms": entry, "readiness_origin_ms": waiting,
            "readiness_deadline_ms": waiting + self.readiness_ms, "readiness_ack_ms": acknowledged,
            "arm_ms": arm, "active_ready_ms": active,
            "setup_deadline_ms": entry + self.setup_ms + acknowledged - waiting,
            "active_deadline_ms": arm + self.active_ms,
            "stop_request_ms": min(active + self.target_ms, watchdog - self.finalize_ms),
            "hard_collection_ms": min(active + self.max_ms, watchdog - self.finalize_ms),
            "watchdog_ms": watchdog,
        }


def trace_pressure(budget, ledger, sample, rate_origin=None):
    def written(point):
        return max(point["file_bytes"], point["written"] * budget.buffer_kib * 1024)

    occupied = written(sample) + budget.backlog_bytes
    remaining = max(0, ledger["stop_request_ms"] - sample["ms"])
    horizon = min(remaining, budget.forecast_horizon_ms)
    projected = None
    window = None
    if rate_origin is not None and sample["ms"] - rate_origin["ms"] >= budget.forecast_window_ms:
        window = sample["ms"] - rate_origin["ms"]
        projected = occupied + (written(sample) - written(rate_origin)) * horizon // window
    return dict(occupied_bytes=occupied, projected_bytes=projected, window_ms=window,
                horizon_ms=horizon, early_bytes=budget.early_mib * MIB)


def poll_decision(budget, ledger, previous, sample, rate_origin=None):
    """Return a stop reason or None. File and written-buffer counters are sampled."""
    fields = ("ms", "written", "file_bytes", "output_free", "system_free", "lost")
    if any(type(sample.get(key)) is not int or sample[key] < 0 for key in fields):
        return "invalid-counter"
    if sample["ms"] > ledger["hard_collection_ms"]:
        return "hard-deadline"
    elapsed = sample["ms"] - previous["ms"]
    if not 0 < elapsed <= budget.poll_ms + budget.poll_late_ms:
        return "missed-poll"
    if any(sample[key] < previous[key] for key in ("written", "file_bytes")):
        return "decreasing-counter"
    if sample["lost"]:
        return "reported-loss"
    if min(sample["output_free"], sample["system_free"]) < budget.live_free_mib * MIB:
        return "low-space"
    pressure = trace_pressure(budget, ledger, sample, rate_origin)
    if pressure["occupied_bytes"] >= pressure["early_bytes"]:
        return "trace-budget-observed"
    if pressure["projected_bytes"] is not None and pressure["projected_bytes"] >= pressure["early_bytes"]:
        return "trace-budget-forecast"
    if sample["ms"] >= ledger["stop_request_ms"]:
        return "target"
    return None

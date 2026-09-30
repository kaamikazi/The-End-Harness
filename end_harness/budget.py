"""Attempts are hard limits; token totals are provenance-labelled observations."""
from dataclasses import asdict, dataclass
import math
import time
from uuid import uuid4


class BudgetExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class BudgetLimits:
    model_attempts: int = 100
    check_attempts: int = 20
    deadline_seconds: float = 60.0

    def __post_init__(self):
        for value in (self.model_attempts, self.check_attempts):
            if type(value) is not int or value < 0:
                raise ValueError("Attempt limits must be nonnegative integers")
        if isinstance(self.deadline_seconds, bool) or not isinstance(self.deadline_seconds, (float, int)) or not math.isfinite(self.deadline_seconds) or self.deadline_seconds < 0:
            raise ValueError("Deadline must be finite and nonnegative")


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    unit: str
    ordinal: int


@dataclass(frozen=True)
class TokenUsage:
    provenance: str
    tokens: tuple[tuple[str, int], ...] | None

    def __post_init__(self):
        if self.provenance not in ("reported", "estimated", "unknown"):
            raise ValueError("Invalid usage provenance")
        if self.provenance == "unknown":
            if self.tokens is not None:
                raise ValueError("Unknown usage cannot carry a measured value")
        elif (not self.tokens or len(dict(self.tokens)) != len(self.tokens) or
              any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in self.tokens)):
            raise ValueError("Known usage must contain nonnegative integer counters")

    @classmethod
    def from_report(cls, usage):
        if not isinstance(usage, dict) or not usage or any(
                not isinstance(k, str) or type(v) is not int or v < 0 for k, v in usage.items()):
            return cls("unknown", None)
        return cls("reported", tuple(sorted(usage.items())))


class Budget:
    def __init__(self, limits: BudgetLimits, *, clock=time.monotonic, parent=None):
        self.limits, self.clock = limits, clock
        self.deadline = clock() + limits.deadline_seconds
        self.attempts = {"model": 0, "check": 0}
        self.pending = {}
        self.usage = []
        self.stop_cause = None
        self.parent, self.parent_reservations = parent, {}

    def boundary(self):
        if self.stop_cause:
            raise BudgetExhausted(self.stop_cause)
        if self.clock() >= self.deadline:
            self.stop_cause = "deadline_exhausted"
            raise BudgetExhausted(self.stop_cause)
        if self.parent is not None:
            try:
                self.parent.boundary()
            except BudgetExhausted as exc:
                self.stop_cause = 'experiment_' + self.parent.stop_cause
                raise BudgetExhausted(self.stop_cause) from exc

    def reserve(self, unit: str) -> Reservation:
        if unit not in self.attempts:
            raise ValueError("Unknown budget unit")
        self.boundary()
        if self.attempts[unit] >= getattr(self.limits, unit + "_attempts"):
            self.stop_cause = unit + "_attempts_exhausted"
            raise BudgetExhausted(self.stop_cause)
        outer = None
        if self.parent is not None:
            try:
                outer = self.parent.reserve(unit)
            except BudgetExhausted as exc:
                self.stop_cause = 'experiment_' + self.parent.stop_cause
                raise BudgetExhausted(self.stop_cause) from exc
        self.attempts[unit] += 1
        reservation = Reservation(str(uuid4()), unit, self.attempts[unit])
        self.pending[reservation.reservation_id] = reservation
        if outer:
            self.parent_reservations[reservation.reservation_id] = outer
        return reservation

    def settle(self, reservation: Reservation, usage: TokenUsage | None = None):
        if self.pending.get(reservation.reservation_id) != reservation:
            raise ValueError("Unknown or already settled reservation")
        del self.pending[reservation.reservation_id]
        if reservation.unit == "model":
            usage = usage or TokenUsage("unknown", None)
            self.usage.append(usage)
        if self.parent is not None:
            self.parent.settle(self.parent_reservations.pop(reservation.reservation_id), usage)
        return usage

    def snapshot(self) -> dict:
        totals, estimates = {}, {}
        for usage in self.usage:
            if usage.provenance == "reported":
                for key, value in usage.tokens:
                    totals[key] = totals.get(key, 0) + value
            elif usage.provenance == "estimated":
                for key, value in usage.tokens:
                    estimates[key] = estimates.get(key, 0) + value
        return {"limits": asdict(self.limits), "attempts": dict(self.attempts),
                "reported_token_totals": totals or None,
                "estimated_token_totals": estimates or None,
                "unknown_usage_calls": sum(u.provenance == "unknown" for u in self.usage),
                "pending_reservations": [asdict(r) for r in self.pending.values()],
                "token_ceiling_enforced": False, "stop_cause": self.stop_cause}

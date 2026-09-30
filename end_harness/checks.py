"""Trusted Python checkers operate on inert JSON data, without generated code execution."""
from dataclasses import asdict, dataclass
from pathlib import Path
import time
from typing import Callable
from uuid import uuid4
from .artifacts import ArtifactStore, CandidateArtifact
from .budget import Budget, BudgetExhausted
from .encoding import canonical, diagnostic, digest, strict_loads, write_once
from .coverage import check_outcome
from .events import EngineRef, Journal, utc_now


POLICY_CLAIM = "All enumerated deployment transitions retain at least one healthy replica."
FIXTURE = {"replica_counts": [2, 3], "initial_healthy": [1, 2, 3], "depth": 3}


@dataclass(frozen=True)
class CheckOutput:
    verdict: str
    supported_scopes: tuple[str, ...]
    observations_json: str


@dataclass(frozen=True)
class RegisteredCheck:
    check_id: str
    version: str
    input_schema: str
    supported_scopes: tuple[str, ...]
    configuration_json: str
    validate_input: Callable[[dict, dict], None]
    execute: Callable[[dict, dict], CheckOutput]
    output_contract: str = "CheckOutput/pass-or-fail/1"

    @property
    def fixture_hash(self):
        return digest(canonical(strict_loads(self.configuration_json)))


@dataclass(frozen=True)
class ExecutionReceipt:
    schema_version: str
    run_id: str
    execution_id: str
    engine: EngineRef | None
    artifact: CandidateArtifact
    check_id: str
    check_version: str
    fixture_hash: str
    status: str
    verdict: str | None
    supported_scopes: tuple[str, ...]
    targets: tuple[str, ...]
    observations_json: str
    started_at: str
    ended_at: str
    elapsed_seconds: float
    call_seq: int
    task_hash: str | None = None
    task_input_hash: str | None = None


class CheckRegistry:
    def __init__(self, checks=()):
        self._checks = {}
        for check in checks:
            self.register(check)

    def register(self, check: RegisteredCheck):
        if check.check_id in self._checks or not check.check_id or not check.version:
            raise ValueError("Duplicate/invalid check registration")
        if not check.supported_scopes or len(set(check.supported_scopes)) != len(check.supported_scopes):
            raise ValueError("Check must declare distinct supported scopes")
        if not isinstance(strict_loads(check.configuration_json), dict):
            raise ValueError("Check configuration must be a JSON object")
        self._checks[check.check_id] = check

    def get(self, check_id: str) -> RegisteredCheck | None:
        return self._checks.get(check_id)


class CheckExecutor:
    def __init__(self, journal: Journal, budget: Budget, store: ArtifactStore, registry: CheckRegistry):
        self.journal, self.budget, self.store, self.registry = journal, budget, store, registry
        self.receipts = {}
        self.last_outcome = None

    def execute(self, check_id: str, artifact: CandidateArtifact, *, engine=None,
                target_scopes: tuple[tuple[str, str], ...] = ()) -> ExecutionReceipt | None:
        self.last_outcome = check_outcome(check_id)
        check = self.registry.get(check_id)
        if check is None:
            self.last_outcome["reason"] = "unknown_check"
            self.journal.append("check/unexecuted", {"check_id": check_id, "reason": "unknown_check"}, engine=engine)
            return None
        if artifact.schema_version != check.input_schema:
            raise ValueError("Check input schema mismatch")
        if any(scope not in check.supported_scopes for _, scope in target_scopes):
            raise ValueError("Unsupported claim target scope")
        data = self.store.load(artifact)
        configuration = strict_loads(check.configuration_json)
        try:
            check.validate_input(data, configuration)
            if digest(canonical(data)) != artifact.tested_hash or digest(canonical(configuration)) != check.fixture_hash:
                raise ValueError("Input validator mutated bound input/configuration")
        except Exception as exc:
            self.last_outcome["reason"] = "invalid_input"
            self.journal.append("check/unexecuted", {"check_id": check_id, "artifact": asdict(artifact),
                                "reason": "invalid_input", "error": diagnostic(exc)}, engine=engine)
            return None
        try:
            reservation = self.budget.reserve("check")
        except BudgetExhausted:
            self.last_outcome.update(status="NOT_DISPATCHED", reason=self.budget.stop_cause)
            self.journal.append("budget/exhausted", self.budget.snapshot(), engine=engine)
            raise
        execution_id = str(uuid4())
        self.last_outcome.update(execution_id=execution_id, check_version=check.version, fixture_hash=check.fixture_hash)
        started = utc_now()
        call = self.journal.append("check/call", {"artifact": asdict(artifact), "check_id": check_id,
            "version": check.version, "fixture_hash": check.fixture_hash, "configuration": configuration,
            "target_scopes": target_scopes, "reservation": asdict(reservation)}, call_id=execution_id, engine=engine)
        # Check again after persistence; a slow fsync must not bypass the deadline.
        try:
            self.budget.boundary()
        except BudgetExhausted:
            self.last_outcome.update(status="NOT_DISPATCHED", reason=self.budget.stop_cause)
            self.budget.settle(reservation)
            self.journal.append("check/result", {"status": "NOT_DISPATCHED", "reason": self.budget.stop_cause},
                                call_id=execution_id, parent_seq=call.seq, engine=engine)
            raise
        clock_start = time.monotonic()
        self.last_outcome.update(status="UNKNOWN", reason="no_durable_result")
        status, verdict, scopes, targets = "COMPLETED", None, (), ()
        try:
            output = check.execute(data, configuration)
            if not isinstance(output, CheckOutput) or output.verdict not in ("PASS", "FAIL"):
                raise ValueError("Malformed checker output")
            if type(output.supported_scopes) is not tuple or not output.supported_scopes or not set(output.supported_scopes) <= set(check.supported_scopes):
                raise ValueError("Checker output exceeds registered scope")
            observations = strict_loads(output.observations_json)
            if not isinstance(observations, dict):
                raise ValueError("Checker observations must be an object")
            # Trusted checker code must not mutate the tested artifact/configuration.
            if digest(canonical(data)) != artifact.tested_hash or digest(canonical(configuration)) != check.fixture_hash:
                raise ValueError("Checker mutated its bound input")
            verdict, scopes = output.verdict, output.supported_scopes
            targets = tuple(target for target, scope in target_scopes if scope in scopes)
        except Exception as exc:
            status = "TIMEOUT" if isinstance(exc, TimeoutError) else "ERROR"
            observations = diagnostic(exc)
        receipt = ExecutionReceipt("1.0", self.journal.run_id, execution_id, engine, artifact,
            check_id, check.version, check.fixture_hash, status, verdict, scopes, targets,
            canonical(observations).decode(), started, utc_now(), time.monotonic()-clock_start, call.seq,
            task_hash=configuration.get('task_hash'), task_input_hash=configuration.get('task_input_hash'))
        self.budget.settle(reservation)
        try:
            write_once(self.journal.directory / "receipts" / (execution_id + ".json"), canonical(asdict(receipt)))
        except Exception:
            self.journal.failed = True
            raise
        self.journal.append("check/result", {"receipt": asdict(receipt)}, call_id=execution_id,
                            parent_seq=call.seq, engine=engine)
        self.receipts[execution_id] = receipt
        self.last_outcome.update(status=status, verdict=verdict, reason=None if status == "COMPLETED" else "checker_failure",
            receipt=f"harness:{receipt.run_id}:receipts/{execution_id}.json")
        return receipt

    def validate_receipt(self, receipt: ExecutionReceipt, artifact: CandidateArtifact, engine: EngineRef,
                         target_scopes: tuple[tuple[str, str], ...]):
        check = self.registry.get(receipt.check_id)
        if self.receipts.get(receipt.execution_id) != receipt or receipt.run_id != self.journal.run_id:
            raise ValueError("Unissued or foreign receipt")
        stored = self.journal.directory / "receipts" / (receipt.execution_id + ".json")
        if stored.read_bytes() != canonical(asdict(receipt)):
            raise ValueError("Persisted receipt mismatch")
        if receipt.artifact != artifact or receipt.engine != engine:
            raise ValueError("Stale or mismatched candidate receipt")
        self.store.load(artifact)
        if check is None or receipt.check_version != check.version or receipt.fixture_hash != check.fixture_hash:
            raise ValueError("Receipt registration/configuration mismatch")
        if receipt.status != "COMPLETED" or receipt.verdict not in ("PASS", "FAIL"):
            raise ValueError("Incomplete execution cannot become evidence")
        allowed = {target for target, scope in target_scopes if scope in receipt.supported_scopes}
        if not set(receipt.targets) <= allowed or not set(receipt.supported_scopes) <= set(check.supported_scopes):
            raise ValueError("Unsupported receipt targets")


def validate_policy(data, fixture):
    if set(data) != {"schema_version", "max_unavailable", "require_healthy_before_stop", "rollback_on_failure"}:
        raise ValueError("Deployment policy fields must match deployment-policy/1 exactly")
    if data["schema_version"] != 1 or type(data["schema_version"]) is not int:
        raise ValueError("Unsupported policy version")
    if type(data["max_unavailable"]) is not int or not 1 <= data["max_unavailable"] <= 3:
        raise ValueError("max_unavailable must be an integer in [1,3]")
    for key in ("require_healthy_before_stop", "rollback_on_failure"):
        if type(data[key]) is not bool:
            raise ValueError(f"{key} must be boolean")
    if fixture != FIXTURE:
        raise ValueError("Checker v1 requires its fixed enumeration fixture")


def deployment_policy(data, fixture):
    """Explore bounded stop/success/failure transitions, checking healthy replicas."""
    examined, failures = 0, []
    for replicas in fixture["replica_counts"]:
        for initial in fixture["initial_healthy"]:
            if initial > replicas:
                continue
            frontier = [(initial, [], 0)]
            while frontier:
                healthy, trace, depth = frontier.pop()
                if depth == fixture["depth"]:
                    continue
                batch = min(data["max_unavailable"], healthy)
                if data["require_healthy_before_stop"]:
                    batch = min(batch, max(0, healthy-1))
                if batch == 0:
                    continue
                stopped = healthy - batch
                examined += 1
                if stopped < 1:
                    failures.append({"replicas": replicas, "initial_healthy": initial, "trace": trace+["stop"], "healthy": stopped})
                for outcome in ("success", "failure"):
                    after = healthy if outcome == "success" or data["rollback_on_failure"] else stopped
                    frontier.append((after, trace+["stop", outcome], depth+1))
    return CheckOutput("FAIL" if failures else "PASS", (POLICY_CLAIM,),
        canonical({"transitions_checked": examined, "counterexamples": failures,
                   "scope": "abstract model; 2-3 replicas; initial healthy 1..N; depth 3; safety only, not liveness"}).decode())


def default_registry():
    return CheckRegistry([RegisteredCheck("deployment.safety", "1", "deployment-policy/1", (POLICY_CLAIM,),
        canonical(FIXTURE).decode(), validate_policy, deployment_policy)])

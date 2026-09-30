"""Own run lifecycle; preserve partial outcomes through ordinary finalization failures."""
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4
from .adapters import EngineAdapter, INTEGRATION_GAPS, HarnessToolVerifier, import_trajectory, load_engine, wrap_judge
from .artifacts import ArtifactStore
from .budget import Budget, BudgetLimits
from .checks import CheckExecutor, default_registry
from .coverage import final_coverage
from .encoding import canonical, diagnostic, write_once
from .events import Journal, JournalError
from .providers import BudgetedModel


@dataclass(frozen=True)
class RunConfig:
    engine_source: Path
    output_root: Path
    limits: BudgetLimits = BudgetLimits()
    max_retries: int = 1
    max_cycles: int = 2
    post_acceptance_cycles: int = 0

    def __post_init__(self):
        for field in (self.max_retries, self.max_cycles, self.post_acceptance_cycles):
            if type(field) is not int or field < 0:
                raise ValueError("Run counts must be nonnegative integers")


@dataclass(frozen=True)
class RunResult:
    run_id: str
    directory: str
    engine_result: dict | None
    harness_stop_cause: str | None
    budget: dict
    evidence_coverage: tuple[dict, ...]
    final_candidate: dict | None
    final_candidate_coverage: dict
    limitations: tuple[str, ...]
    engine_identity: dict
    engine_execution: str
    trajectory_snapshot: str
    trajectory_import: str
    journal_closure: str
    summary_persistence: str
    cleanup: str
    failures: tuple[dict, ...]
    schema_version: str = "1.1"
    status_view: str = "caller_observed"
    engine_result_source: str | None = None

    @property
    def journal_complete(self) -> bool:
        """Compatibility accessor: closure confirmation, not trajectory import."""
        return self.journal_closure == "confirmed"

    def persisted_payload(self, phase: str) -> dict:
        """Record only facts observable before this write; never self-certify it."""
        data = asdict(self)
        data["status_view"] = phase
        data.pop("summary_persistence")
        data.pop("cleanup")
        if phase == "before_journal_closure":
            data.pop("journal_closure")
        return data


def run_task(task: str, config: RunConfig, *, generator, judge, secondary_judge=None,
             adversarial_judge=None, registry=None, claim_extractor=None,
             required_checks=("deployment.safety",), check_binding=None, resource_budget=None) -> RunResult:
    # Preflight provenance/configuration errors occur before a run is started.
    identity = load_engine(config.engine_source)
    run_id = str(uuid4())
    directory = (Path(config.output_root) / run_id).resolve()
    budget = resource_budget if resource_budget is not None else Budget(config.limits)
    if resource_budget is not None and budget.limits != config.limits:
        raise ValueError('Injected budget must match declared run limits')
    artifact_schema = check_binding.artifact_schema if check_binding else 'deployment-policy/1'
    if check_binding:
        required_checks = check_binding.required_checks
    limitations = list(INTEGRATION_GAPS)
    journal = engine = verifier = None
    result = trajectory = None
    result_source = None
    failures = []
    state = {"engine_execution": "not_started", "trajectory_snapshot": "not_attempted",
             "trajectory_import": "not_attempted", "journal_closure": "not_attempted",
             "summary_persistence": "not_attempted", "cleanup": "not_needed"}

    def failure(stage, cause, exc=None):
        failures.append({"stage": stage, "cause": cause,
                         "diagnostic": diagnostic(exc) if exc is not None else None})

    def note_budget():
        if budget.stop_cause and not any(f["cause"] == budget.stop_cause for f in failures):
            failure("execution", budget.stop_cause)

    def ref():
        return engine.reference() if engine else None

    def snapshot():
        history = tuple(verifier.coverage) if verifier else ()
        coverage = final_coverage(run_id, result, trajectory, history, required_checks, artifact_schema)
        return RunResult(run_id, str(directory), result, failures[0]["cause"] if failures else None,
            budget.snapshot(), history, coverage["engine"], coverage, tuple(limitations), identity,
            **state, failures=tuple(failures), engine_result_source=result_source)

    stage = "journal_open"
    try:
        try:
            journal = Journal(directory, run_id)
            executor = CheckExecutor(journal, budget, ArtifactStore(directory / "artifacts", artifact_schema),
                                     registry if registry is not None else default_registry())
            verifier = HarnessToolVerifier(executor, ref, required_checks=required_checks, binding=check_binding)
            stage = "run_start"
            journal.append("run/start", {"task": task, "engine": identity, "limits": asdict(config.limits),
                "max_retries": config.max_retries, "max_cycles": config.max_cycles,
                "post_acceptance_cycles": config.post_acceptance_cycles, "required_checks": required_checks,
                "harness_version": "0.2.0", "result_schema_version": "1.1", "artifact_schema": artifact_schema})
            model = BudgetedModel(generator, budget, journal, max_retries=config.max_retries, engine_ref=ref)
            def wrap(value, role):
                return wrap_judge(value, budget, journal, role=role, max_retries=config.max_retries,
                                  engine_ref=ref, limitations=limitations)
            stage = "engine_setup"
            engine = EngineAdapter(directory=directory, model=model, max_cycles=config.max_cycles,
                post_acceptance_cycles=config.post_acceptance_cycles,
                primary_judge=wrap(judge, "primary_judge"),
                secondary_judge=wrap(secondary_judge, "secondary_judge") if secondary_judge else None,
                adversarial_judge=wrap(adversarial_judge or judge, "adversarial_judge"),
                tool_verifier=verifier, claim_extractor=claim_extractor)
            stage = "engine_execution"
            state["engine_execution"] = "started"
            result = engine.run(task)
            result_source = "returned"
            state["engine_execution"] = "returned"
            note_budget()
            if journal.failed:
                raise JournalError("Engine returned after persistence failure")
            stage = "trajectory_read"
            trajectory = engine.trajectory
            stage = "trajectory_snapshot"
            state["trajectory_snapshot"] = "unconfirmed"
            write_once(directory / "trajectory.json", canonical(trajectory))
            state["trajectory_snapshot"] = "confirmed"
            stage = "trajectory_import"
            state["trajectory_import"] = "unconfirmed"
            import_trajectory(journal, trajectory)
            state["trajectory_import"] = "confirmed"
        except Exception as exc:
            note_budget()
            if state["engine_execution"] == "started":
                state["engine_execution"] = "raised"
            cause = "journal_failure" if journal and journal.failed or isinstance(exc, JournalError) else f"{stage}_failure"
            failure(stage, cause, exc)
            # END may have computed a result before its own ledger save raised.
            if result is None and engine is not None:
                try:
                    available = engine.trajectory
                    if available and available.get("final_result"):
                        trajectory, result = available, available["final_result"]
                        result_source = "public_trajectory.final_result"
                except Exception as recovery_error:
                    failure("trajectory_recovery", "trajectory_recovery_failure", recovery_error)
            if journal is not None and not journal.failed:
                try:
                    journal.append("run/error", {"failure": failures[-1], "harness_stop_cause": failures[0]["cause"]})
                except Exception as record_error:
                    journal.failed = True
                    failure("failure_record", "journal_failure", record_error)

        # A poisoned writer is never used again, including for an error/closure record.
        if journal is not None and not journal.failed:
            state["journal_closure"] = "unconfirmed"
            try:
                journal.append("run/end", snapshot().persisted_payload("before_journal_closure"))
                state["journal_closure"] = "confirmed"
            except Exception as exc:
                journal.failed = True
                failure("journal_closure", "journal_failure", exc)
        else:
            state["journal_closure"] = "skipped_unavailable_writer"
        state["summary_persistence"] = "unconfirmed"
        try:
            write_once(directory / "result.json", canonical(snapshot().persisted_payload("before_summary_write")))
            state["summary_persistence"] = "confirmed"
        except Exception as exc:
            failure("summary_persistence", "summary_persistence_failure", exc)
    finally:
        if journal is not None:
            try:
                journal.close()
                state["cleanup"] = "confirmed"
            except Exception as exc:
                state["cleanup"] = "failed"
                failure("cleanup", "cleanup_failure", exc)
    return snapshot()

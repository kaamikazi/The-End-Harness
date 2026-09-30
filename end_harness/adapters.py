"""All END-specific translation is concentrated here; END itself remains unchanged."""
from dataclasses import asdict, dataclass
import importlib
from copy import deepcopy
from pathlib import Path
import sys
import tomllib
from uuid import uuid4
from .checks import POLICY_CLAIM, CheckExecutor
from .encoding import canonical, diagnostic, digest, strict_loads
from .artifacts import original_identity
from .coverage import check_outcome, coverage_record
from .events import EngineRef
from .budget import BudgetExhausted
from .providers import BudgetedModel


INTEGRATION_GAPS = (
    "END 0.3.0 maps Harness budget exceptions to EXTERNAL_BLOCKER; Harness stop cause is separate.",
    "END has no required-check manifest: absent checks can allow provisional acceptance, or verified acceptance if other evidence exists.",
    "END has no durable live cognitive event sink; cognitive history is imported only after run return.",
)


_ENGINE_IDENTITY = None
_ENGINE_DRIFTED = False


def _source_identity(source: Path) -> dict:
    manifest = {p.relative_to(source).as_posix(): digest(p.read_bytes())
                for p in sorted((source / "end_engine").rglob("*.py"))}
    project = (source / "pyproject.toml").read_bytes()
    manifest["pyproject.toml"] = digest(project)
    return {"version": tomllib.loads(project.decode("utf-8"))["project"]["version"],
            "source": str(source), "source_sha256": digest(canonical(manifest)),
            "source_manifest": manifest, "fingerprint_scope": "end_engine/**/*.py and pyproject.toml",
            "commit": None, "provenance": "harness_controlled_initial_load"}


def load_engine(source: Path) -> dict:
    """Load only the explicitly selected source tree; never install globally."""
    global _ENGINE_IDENTITY, _ENGINE_DRIFTED
    source = Path(source).resolve()
    if _ENGINE_DRIFTED:
        raise ValueError("END Engine provenance invalidated by source drift; use a fresh process")
    if not (source / "end_engine" / "engine.py").is_file():
        raise ValueError("Engine source must contain end_engine/engine.py")
    if _ENGINE_IDENTITY is not None:
        if str(source) != _ENGINE_IDENTITY["source"]:
            raise ValueError("A different END Engine source is already loaded; use a fresh process")
        try:
            current = _source_identity(source)
        except (OSError, ValueError) as exc:
            _ENGINE_DRIFTED = True
            raise ValueError("END Engine source no longer matches controlled load; use a fresh process") from exc
        if current != _ENGINE_IDENTITY:
            _ENGINE_DRIFTED = True
            raise ValueError("END Engine source drift since controlled load; use a fresh process")
        return deepcopy(_ENGINE_IDENTITY)
    if any(name == "end_engine" or name.startswith("end_engine.") for name in sys.modules):
        raise ValueError("END Engine was imported before Harness-controlled loading; provenance unavailable; use a fresh process")
    before = _source_identity(source)
    sys.dont_write_bytecode = True
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    module = importlib.import_module("end_engine")
    if Path(module.__file__).resolve().parent.parent != source:
        raise ValueError("Imported Engine does not match selected source; use a fresh process")
    after = _source_identity(source)
    if before != after:
        _ENGINE_DRIFTED = True
        raise ValueError("END Engine source changed during initial load; use a fresh process")
    _ENGINE_IDENTITY = before
    return deepcopy(before)


class EngineAdapter:
    """Public-interface composition; serialized END results remain unmodified."""
    def __init__(self, *, directory: Path, model, primary_judge, secondary_judge,
                 adversarial_judge, tool_verifier, claim_extractor, max_cycles: int,
                 post_acceptance_cycles: int):
        from end_engine import EndEngine
        from end_engine.config import EngineConfig
        self.max_cycles = max_cycles
        self.engine = EndEngine(EngineConfig(ledger_dir=str(directory / "engine"), quality_evaluation=True,
            enable_branching=False, post_acceptance_cycles=post_acceptance_cycles), provider=model,
            judge_provider=primary_judge, secondary_judge_provider=secondary_judge,
            adversarial_judge_provider=adversarial_judge, tool_verifier=tool_verifier,
            claim_extractor=claim_extractor)

    @property
    def trajectory(self) -> dict | None:
        return self.engine.last_trajectory

    def reference(self) -> EngineRef | None:
        trajectory = self.trajectory
        return EngineRef(trajectory["trajectory_id"]) if trajectory else None

    def run(self, task: str) -> dict:
        return self.engine.run(task, mode="normal", max_cycles=self.max_cycles).as_dict()


class MeteredModelJudge:
    """Preserve the model wrapper when END asks judges for run-local clones."""
    def __init__(self, model):
        self.model = model

    def metadata(self):
        return self.model.metadata()

    def evaluate(self, request):
        return self.model.generate_structured(request)

    def for_run(self):
        return MeteredModelJudge(self.model.for_run())


class ObservedOpaqueJudge:
    """Invocation visibility only; hidden internal model requests cannot be metered."""
    def __init__(self, judge, budget, journal, role, ref):
        self.judge, self.budget, self.journal, self.role, self.ref = judge, budget, journal, role, ref

    def metadata(self):
        return {**self.judge.metadata(), "harness_coverage": "opaque_judge_invocations_only"}

    def for_run(self):
        return ObservedOpaqueJudge(self.judge.for_run(), self.budget, self.journal, self.role, self.ref)

    def evaluate(self, request):
        self.budget.boundary()
        call_id = str(uuid4())
        call = self.journal.append("judge/call", {"role": self.role, "request": asdict(request),
            "coverage": "opaque; underlying model attempt/token limits cannot be enforced"}, call_id=call_id, engine=self.ref())
        try:
            self.budget.boundary()
        except BudgetExhausted:
            self.journal.append("judge/result", {"status": "NOT_DISPATCHED", "reason": self.budget.stop_cause},
                call_id=call_id, parent_seq=call.seq, engine=self.ref())
            raise
        try:
            result = self.judge.evaluate(request)
        except Exception as exc:
            self.journal.append("judge/result", {"status": "ERROR", **diagnostic(exc)},
                call_id=call_id, parent_seq=call.seq, engine=self.ref())
            raise
        self.journal.append("judge/result", {"status": "COMPLETED", "response": asdict(result)},
            call_id=call_id, parent_seq=call.seq, engine=self.ref())
        return result


def wrap_judge(judge, budget, journal, *, role, max_retries, engine_ref, limitations):
    from end_engine.quality.providers import ModelJudgeProvider
    if type(judge) is ModelJudgeProvider:
        return MeteredModelJudge(BudgetedModel(judge.provider, budget, journal,
            role=role, max_retries=max_retries, engine_ref=engine_ref))
    limitation = f"{role}: opaque judge; internal model requests/tokens unobservable and not bounded by model-attempt limit"
    limitations.append(limitation)
    journal.append("coverage/limitation", {"message": limitation})
    return ObservedOpaqueJudge(judge, budget, journal, role, engine_ref)


class PolicyClaimExtractor:
    """Trusted claim vocabulary; support applies only to the bounded policy model."""
    def extract(self, candidate):
        return (POLICY_CLAIM,)


@dataclass(frozen=True)
class CheckBinding:
    artifact_schema: str = "deployment-policy/1"
    required_checks: tuple[str, ...] = ("deployment.safety",)
    scopes: tuple[str, ...] = (POLICY_CLAIM,)
    requests: tuple[tuple[str, str, str], ...] = (("registered:deployment.safety", "deployment.safety", POLICY_CLAIM),)
    description: str = "Bounded deployment-policy transition enumeration; see receipt for scope and observations"
    include_observations: bool = False

    def extract(self, candidate):
        return self.scopes


class HarnessToolVerifier:
    def __init__(self, executor: CheckExecutor, engine_ref, *, required_checks=("deployment.safety",), binding=None):
        self.executor, self.engine_ref, self.required_checks = executor, engine_ref, required_checks
        self.binding = binding or CheckBinding()
        self.coverage = []

    def mappings(self, claims):
        # Claim IDs originate in END, but support is assigned only by exact trusted text.
        return tuple((c.claim_id, c.text) for c in claims if c.text in self.binding.scopes)

    def evidence(self, receipt, artifact, ref, mappings):
        from end_engine.quality.state import EvidenceArtifact
        self.executor.validate_receipt(receipt, artifact, ref, mappings)
        description = self.binding.description
        if self.binding.include_observations:
            description += '\n' + canonical({'development_feedback': {'status': receipt.status,
                'verdict': receipt.verdict, 'observations': strict_loads(receipt.observations_json)}}).decode()
        return EvidenceArtifact(receipt.execution_id, ref.local_id, "EXECUTED_EVIDENCE",
            f"harness:{receipt.run_id}:receipts/{receipt.execution_id}.json", receipt.verdict == "PASS",
            description,
            receipt.targets)

    def collect(self, task, candidate, tests, claims):
        trajectory = self.engine_ref()
        ref = EngineRef(trajectory.trajectory_id, candidate.candidate_id) if trajectory else None
        binding = original_identity(candidate.content)
        mappings = self.mappings(claims)
        supported_targets = {target for target, _ in mappings}
        optional, unsupported, mapped = set(), [], []
        for test in tests:
            mapping = next(((check_id, scope) for scenario, check_id, scope in self.binding.requests
                if scenario == test.scenario and scope == test.expected_property), None)
            if (mapping and test.candidate_id == candidate.candidate_id and test.target in supported_targets
                    and (test.target, mapping[1]) in mappings):
                optional.add(mapping[0])
                mapped.append({'test_id': test.test_id, 'check_id': mapping[0], 'scope': mapping[1]})
            else:
                unsupported.append({"test_id": test.test_id,
                    "reason": "Unsupported scenario/property/target; model description is inert"})
        optional -= set(self.required_checks)
        requested = sorted(set(self.required_checks) | optional)
        outcomes = {check_id: check_outcome(check_id) for check_id in requested}
        artifact, status, reason = None, "unavailable", "collection_interrupted"
        evidence = []
        try:
            if ref is None:
                reason = "trajectory_identity_unavailable"
                return ()
            for claim in claims:
                if claim.claim_id not in supported_targets:
                    self.executor.journal.append("claim/unsupported", {"claim_id": claim.claim_id,
                        "reason": "No trusted scope mapping for claim text"}, engine=ref)
            for item in unsupported:
                self.executor.journal.append("check/unexecuted", item, engine=ref)
            for item in mapped:
                self.executor.journal.append("check/request_mapped", item, engine=ref)
            try:
                artifact = self.executor.store.capture(candidate.content)
            except (ValueError, UnicodeError) as exc:
                status, reason = "invalid", "invalid_candidate_json_or_unicode"
                for outcome in outcomes.values():
                    outcome["reason"] = reason
                self.executor.journal.append("artifact/rejected", {**binding, "reason": reason,
                    "error": diagnostic(exc), "content_diagnostic": {"encoding": "python_ascii_repr", "value": ascii(candidate.content)}}, engine=ref)
                return ()
            except OSError:
                self.executor.journal.failed = True
                raise
            self.executor.journal.append("artifact/captured", asdict(artifact), engine=ref)
            for check_id in requested:
                self.executor.last_outcome = None
                try:
                    receipt = self.executor.execute(check_id, artifact, engine=ref, target_scopes=mappings)
                finally:
                    if self.executor.last_outcome is not None:
                        outcomes[check_id] = dict(self.executor.last_outcome)
                if receipt and receipt.status == "COMPLETED":
                    try:
                        evidence.append(self.evidence(receipt, artifact, ref, mappings))
                    except Exception:
                        outcomes[check_id].update(status="ERROR", verdict=None, reason="receipt_validation_failed")
                        raise
            status, reason = "recorded", None
            return tuple(evidence)
        finally:
            coverage = coverage_record(self.executor.journal.run_id, asdict(ref) if ref else None,
                artifact=asdict(artifact) if artifact else None, **binding,
                required=self.required_checks, optional=optional, checks=outcomes.values(),
                unsupported_requests=unsupported, status=status, reason=reason)
            self.coverage.append(coverage)
            if not self.executor.journal.failed:
                self.executor.journal.append("checks/coverage", coverage, engine=ref)


def import_trajectory(journal, trajectory):
    """Append original Engine steps with honest import time and original timestamps."""
    for step in trajectory["steps"]:
        data = step["data"]
        local_id = next((data[k] for k in ("candidate_id", "judgment_id") if isinstance(data, dict) and k in data), None)
        journal.append("engine/" + step["type"], {"provenance": "post_run_import", "original_step": step},
                       engine=EngineRef(trajectory["trajectory_id"], local_id))
    journal.append("engine/import_complete", {"provenance": "post_run_import", "steps": len(trajectory["steps"]),
        "best_candidate_id": trajectory.get("best_candidate_id"), "latest_candidate_id": trajectory.get("latest_candidate_id")},
        engine=EngineRef(trajectory["trajectory_id"]))

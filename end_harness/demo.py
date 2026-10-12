"""SYNTHETIC model/judge fixtures with real END control flow and executed checks."""
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
from .adapters import POLICY_CLAIM, PolicyClaimExtractor, load_engine
from .budget import BudgetLimits
from .encoding import canonical, strict_loads, write_once
from .events import Journal, close_interrupted
from .runtime import RunConfig, run_task


def candidate_text(name):
    return files("end_harness").joinpath("fixtures", name + ".json").read_text(encoding="utf-8").strip()


class SyntheticGenerator:
    def metadata(self):
        return {"provider": "synthetic-generator", "model": "policy-fixture-v1", "offline": True}

    def generate(self, request):
        raise ValueError("Fixture only supports structured requests")

    def generate_structured(self, request):
        from end_engine.models.base import ModelResponse
        context, purpose = request.context, request.purpose
        if purpose in ("initial_candidate", "revision"):
            name = ("faulty", "improved", "regressed")[context.get("iteration", 0)]
            response = {"content": candidate_text(name), "known_strengths": [], "confidence": None}
        elif purpose == "verification":
            response = {"passed": True, "score": .95, "dimensions": {d: .95 for d in context["dimensions"]},
                        "remaining_issues": [], "weakness_updates": []}
        elif purpose == "critique":
            response = {"summary": "Synthetic fixture advances the bounded regression probe", "findings": []}
        elif purpose == "revision_plan":
            response = {"changes": []}
        else:
            raise ValueError(f"Unsupported synthetic generator purpose: {purpose}")
        return ModelResponse(response)  # Deliberately unknown token usage, not a fake measurement.


class SyntheticJudgeModel:
    def for_run(self):
        return SyntheticJudgeModel()

    def metadata(self):
        return {"provider": "synthetic-judge", "model": "policy-judge-fixture-v1", "offline": True}

    def generate(self, request):
        raise ValueError("Fixture only supports structured requests")

    def generate_structured(self, request):
        from end_engine.models.base import ModelResponse
        from end_engine.quality.mock import judgment_fixture
        context, purpose = request.context, request.purpose
        if purpose in ("judgment", "adversarial_judgment"):
            response = judgment_fixture(context["dimensions"])
            # C2's fatal regression is grounded in the actual failed, candidate-bound
            # development check supplied to this judge. Comparison scores remain advisory.
            if strict_loads(context['candidate']['content']) == strict_loads(candidate_text('regressed')):
                failures = [e for e in context['evidence'] if e['evidence_type'] == 'EXECUTED_EVIDENCE'
                            and not e['passed'] and e.get('contract')]
                if failures:
                    evidence = failures[0]
                    scope = evidence['contract']['claims'][0]
                    response = judgment_fixture(context['dimensions'], verdict='FAIL', fatal=True,
                        issues=[{'category': 'safety', 'description': 'The bounded safety check failed',
                            'target': evidence['targets'][0], 'fatal': True,
                            'evidence': [evidence['artifact_id']], 'claim_type': 'CANDIDATE_INTERNAL',
                            'candidate_quote': context['candidate']['content'],
                            'source_claim': scope, 'alleged_defect': 'Not ' + scope,
                            'basis': 'Executed candidate-bound checker receipt'}])
        elif purpose == "adversarial_tests":
            response = {"tests": [{"target": context["claims"][0]["claim_id"] if context["claims"] else "candidate",
                "scenario": "registered:deployment.safety", "expected_property": POLICY_CLAIM,
                "execution_status": "UNEXECUTED"}]}
        elif purpose == "comparison":
            # Comparison preference is advisory; executed-check-grounded findings drive rejection.
            improving = strict_loads(context["candidates"]["B"])["require_healthy_before_stop"]
            preferred, delta = ("B", .3) if improving else ("A", -.4)
            response = {"preferred": preferred, "dimensions": {d: preferred for d in context["dimensions"]},
                "delta": {d: 0 if d == "complexity_cost" else delta for d in context["dimensions"]},
                "reason": "SYNTHETIC preference fixture: preserve the healthy-before-stop invariant"}
        else:
            raise ValueError(f"Unsupported synthetic judge purpose: {purpose}")
        return ModelResponse(response)


def demo_providers(engine_source):
    load_engine(engine_source)
    from end_engine.quality.providers import ModelJudgeProvider
    return SyntheticGenerator(), ModelJudgeProvider(SyntheticJudgeModel())


def run_demo(engine_source: Path, output: Path) -> dict:
    output = Path(output)
    generator, judge = demo_providers(engine_source)
    normal = run_task("Evaluate the bounded abstract deployment policy.", RunConfig(engine_source, output, post_acceptance_cycles=1),
                      generator=generator, judge=judge, claim_extractor=PolicyClaimExtractor())
    generator, judge = demo_providers(engine_source)
    exhausted = run_task("Demonstrate shared request budget exhaustion.",
        RunConfig(engine_source, output, limits=BudgetLimits(model_attempts=3)),
        generator=generator, judge=judge, claim_extractor=PolicyClaimExtractor())
    # Manufacture only the crash evidence, never fake an Engine integration result.
    from uuid import uuid4
    interrupted_id = str(uuid4())
    interrupted = output / interrupted_id
    journal = Journal(interrupted, interrupted_id)
    journal.append("run/start", {"synthetic_interruption_fixture": True})
    journal.append("model/call", {"fixture": "process ended before a durable result"}, call_id="interrupted-call")
    journal.close()
    with (interrupted / "events.jsonl").open("ab") as stream:
        stream.write(b'{"schema_version":"1.0","run_id":')
    recovery = close_interrupted(interrupted)
    summary = {"disclaimer": "SYNTHETIC model/judge responses; real END Engine and real bounded checker. No intelligence, judge accuracy, or production safety claim.",
        "normal": asdict(normal), "budget_exhaustion": asdict(exhausted),
        "interrupted_directory": str(interrupted.resolve()), "recovery": recovery}
    write_once(output / ("demo-" + normal.run_id + ".json"), canonical(summary))
    return summary

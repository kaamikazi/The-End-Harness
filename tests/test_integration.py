from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import tomllib
import unittest
from unittest.mock import patch
from end_harness.adapters import PolicyClaimExtractor, load_engine
from end_harness.budget import BudgetLimits
from end_harness.demo import candidate_text, demo_providers, SyntheticGenerator
from end_harness.encoding import strict_loads
from end_harness.events import Journal, close_interrupted, inspect_run
from end_harness.runtime import RunConfig, run_task


class RealEngineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(os.environ["END_ENGINE_SOURCE"])
        self.output = Path(self.temp.name)
        self.config = RunConfig(self.source, self.output, post_acceptance_cycles=1)

    def run_fixture(self, config=None, **kwargs):
        generator, judge = demo_providers(self.source)
        return run_task("Evaluate the bounded abstract deployment policy.", config or self.config,
                        generator=generator, judge=judge, claim_extractor=PolicyClaimExtractor(), **kwargs)

    def test_real_engine_restores_better_candidate_and_retains_failures(self):
        result = self.run_fixture()
        self.assertIsNone(result.harness_stop_cause)
        self.assertEqual(result.engine_result["best_candidate_id"], "C1")
        self.assertEqual(result.engine_result["latest_candidate_id"], "C2")
        self.assertEqual(result.engine_result["answer"], candidate_text("improved"))
        self.assertEqual(result.engine_result["termination_reason"], "ACCEPTED_VERIFIED")
        directory = Path(result.directory)
        trajectory = strict_loads((directory / "trajectory.json").read_bytes())
        self.assertEqual([c["candidate_id"] for c in trajectory["candidates"]], ["C0", "C1", "C2"])
        self.assertEqual(trajectory["rollback_events"][0]["from_candidate"], "C2")
        self.assertEqual(trajectory["rollback_events"][0]["to_candidate"], "C1")
        receipts = [strict_loads(p.read_bytes()) for p in (directory / "receipts").glob('*.json')]
        self.assertEqual({r["engine"]["local_id"]: r["verdict"] for r in receipts}, {"C0": "FAIL", "C1": "PASS", "C2": "FAIL"})
        self.assertTrue(all(r["engine"]["trajectory_id"] == trajectory["trajectory_id"] for r in receipts))
        self.assertTrue(inspect_run(directory)["completed"])
        self.assertEqual(result.budget["attempts"], {"model": 21, "check": 3})
        # All underlying generator/verifier/judge/adversary requests are counted once.
        self.assertEqual(len(trajectory["model_calls"]), result.budget["attempts"]["model"])

    def test_final_engine_events_explicitly_post_run_imports(self):
        result = self.run_fixture()
        events = [strict_loads(line) for line in (Path(result.directory) / "events.jsonl").read_bytes().splitlines()]
        imported = [e for e in events if e["type"].startswith("engine/")]
        self.assertTrue(imported)
        self.assertTrue(all(e["payload"]["provenance"] == "post_run_import" for e in imported))
        for kind in ("engine/candidate", "engine/judgment", "engine/quality_gate", "engine/candidate_rollback"):
            self.assertTrue(any(e["type"] == kind for e in imported))
        last_model = max(e["seq"] for e in events if e["type"] == "model/result")
        self.assertGreater(min(e["seq"] for e in imported), last_model)

    def test_harness_budget_cause_is_separate_from_engine_blocker(self):
        result = self.run_fixture(replace(self.config, limits=BudgetLimits(model_attempts=3)))
        self.assertEqual(result.harness_stop_cause, "model_attempts_exhausted")
        self.assertEqual(result.engine_result["termination_reason"], "EXTERNAL_BLOCKER")
        self.assertEqual(result.budget["attempts"]["model"], 3)
        self.assertEqual(result.budget["unknown_usage_calls"], 3)

    def test_check_exhaustion_preserves_missing_coverage_and_engine_blocker(self):
        result = self.run_fixture(replace(self.config, limits=BudgetLimits(check_attempts=0)))
        self.assertEqual(result.harness_stop_cause, "check_attempts_exhausted")
        self.assertEqual(result.engine_result["termination_reason"], "EXTERNAL_BLOCKER")
        self.assertEqual(result.evidence_coverage[0]["missing"], ["deployment.safety"])

    def test_run_deadline_exhaustion_is_preserved_separately(self):
        result = self.run_fixture(replace(self.config, limits=BudgetLimits(deadline_seconds=0)))
        self.assertEqual(result.harness_stop_cause, "deadline_exhausted")
        self.assertEqual(result.engine_result["termination_reason"], "EXTERNAL_BLOCKER")
        self.assertEqual(result.budget["attempts"], {"model": 0, "check": 0})

    def test_missing_required_check_gap_is_visible_without_overriding_engine(self):
        result = self.run_fixture(required_checks=("deployment.safety", "missing.required"))
        self.assertEqual(result.engine_result["quality_gate"], "ACCEPT_VERIFIED")
        self.assertTrue(all("missing.required" in item["missing"] for item in result.evidence_coverage))
        self.assertTrue(any("required-check manifest" in gap for gap in result.limitations))

    def test_no_completed_check_can_only_receive_provisional_acceptance_here(self):
        from end_harness.checks import CheckRegistry
        result = self.run_fixture(registry=CheckRegistry())
        self.assertEqual(result.engine_result["quality_gate"], "ACCEPT_PROVISIONALLY")
        self.assertEqual(result.evidence_coverage[0]["completed"], [])

    def test_journal_failure_is_reported_despite_engine_exception_translation(self):
        original = Journal.checkpoint
        calls = []
        def fail_first_model(journal):
            if journal.seq == 1:
                raise OSError("simulated checkpoint failure")
            original(journal)
        class NeverCalled(SyntheticGenerator):
            def generate_structured(self, request):
                calls.append(request)
                return super().generate_structured(request)
        _, judge = demo_providers(self.source)
        with patch.object(Journal, "checkpoint", fail_first_model):
            result = run_task("task", self.config, generator=NeverCalled(), judge=judge)
        self.assertEqual(result.harness_stop_cause, "journal_failure")
        self.assertEqual(result.engine_result["termination_reason"], "EXTERNAL_BLOCKER")
        self.assertFalse(result.journal_complete)
        self.assertEqual(calls, [])

    def test_real_process_exit_keeps_intent_but_loses_engine_cognitive_state(self):
        script = '''
import os, sys
from pathlib import Path
from end_harness.demo import SyntheticGenerator, demo_providers
from end_harness.runtime import RunConfig, run_task
class Crash(SyntheticGenerator):
    def generate_structured(self, request):
        os._exit(7)
source, output = map(Path, sys.argv[1:])
_, judge = demo_providers(source)
run_task("crash boundary", RunConfig(source, output), generator=Crash(), judge=judge)
'''
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent))
        process = subprocess.run([sys.executable, '-B', '-c', script, str(self.source), str(self.output)],
                                 env=env, cwd=self.output, capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 7, process.stderr.decode())
        directory = next(self.output.iterdir())
        recovery = close_interrupted(directory)
        self.assertEqual(recovery["unfinished_calls"][0]["status"], "OUTCOME_UNKNOWN")
        self.assertIn("unavailable", recovery["engine_state"])
        self.assertFalse((directory / "trajectory.json").exists())

    def test_engine_source_fingerprint_is_reproducible(self):
        first, second = load_engine(self.source), load_engine(self.source)
        self.assertEqual(first["source_sha256"], second["source_sha256"])
        # The expected version is read independently from the explicitly selected checkout, not hard-coded.
        with (self.source / "pyproject.toml").open("rb") as stream:
            expected = tomllib.load(stream)["project"]["version"]
        self.assertRegex(expected, r"^\d+\.\d+\.\d+$")
        self.assertEqual(first["version"], expected)
        self.assertEqual(first["source"], str(self.source.resolve()))

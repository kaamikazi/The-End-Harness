from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch
from end_engine.core.state import Candidate, now
from end_engine.cognition.state import Claim
from end_engine.quality.state import AdversarialTest
from end_harness.adapters import HarnessToolVerifier
from end_harness.checks import CheckOutput, CheckRegistry, POLICY_CLAIM
from end_harness.coverage import final_coverage
from end_harness.demo import candidate_text
from end_harness.encoding import canonical, strict_loads
from end_harness.events import EngineRef, inspect_run
from end_harness.runtime import RunConfig
from support import RuntimeCase
import test_integration as baseline


class CoverageTests(RuntimeCase):
    def setUp(self):
        super().setUp()
        self.ref = EngineRef("trajectory")
        self.verifier = HarnessToolVerifier(self.executor, lambda: self.ref)
        self.claims = (Claim("CL001", POLICY_CLAIM, "technical", "C1"),)

    def collect(self, content=None, candidate_id="C1", tests=()):
        content = candidate_text("improved") if content is None else content
        candidate = Candidate(candidate_id, None, 0, content, now())
        return self.verifier.collect("task", candidate, tests, self.claims)

    def summary(self, candidate_id="C1", content=None, history=None):
        content = candidate_text("improved") if content is None else content
        return final_coverage("test-run", {"trajectory_id": "trajectory", "best_candidate_id": candidate_id,
            "answer": content}, None, self.verifier.coverage if history is None else history, ("deployment.safety",))

    def test_actual_unpaired_surrogate_is_structured_rejection_without_fake_hash(self):
        self.assertEqual(self.collect('{"x":"' + chr(0xd800) + '"}'), ())
        rejection = next(e["payload"] for e in self.events() if e["type"] == "artifact/rejected")
        self.assertIsNone(rejection["candidate_hash"])
        self.assertIn("original_utf8_unavailable", rejection["hash_unavailable_reason"])
        self.assertEqual(rejection["content_diagnostic"]["encoding"], "python_ascii_repr")
        self.assertIn("\\ud800", rejection["content_diagnostic"]["value"])
        self.assertEqual(self.verifier.coverage[-1]["passed"], [])
        canonical(rejection)

    def test_invalid_json_and_valid_unicode_have_uniform_coverage_shape(self):
        self.collect('{oops')
        invalid = self.verifier.coverage[-1]
        self.assertIsNotNone(invalid["candidate_hash"])
        self.assertIsNone(invalid["artifact"])
        self.collect('{"message":"বাংলা"}')  # Valid Unicode JSON, unsupported policy schema.
        unicode = self.verifier.coverage[-1]
        self.assertIsNotNone(unicode["artifact"])
        self.assertEqual(unicode["passed"], [])
        self.collect()
        valid = self.verifier.coverage[-1]
        self.assertEqual(set(valid), set(invalid))
        self.assertEqual(set(valid), set(unicode))
        self.assertEqual(set(valid), set(self.summary("C99")))

    def test_other_candidate_run_or_artifact_pass_cannot_fill_final_evidence(self):
        self.collect(candidate_id="C2")
        self.assertEqual(self.summary()["passed"], [])
        self.assertEqual(self.summary()["missing"], ["deployment.safety"])
        self.collect()
        foreign = deepcopy(self.verifier.coverage[-1])
        foreign["run_id"] = "other-run"
        self.assertEqual(self.summary(history=[foreign])["passed"], [])
        foreign = deepcopy(self.verifier.coverage[-1])
        foreign["artifact"]["tested_hash"] = "other-artifact"
        self.assertEqual(self.summary(history=[foreign])["passed"], [])

    def test_completed_fail_is_not_passed(self):
        self.collect(candidate_text("faulty"))
        view = self.summary(content=candidate_text("faulty"))
        self.assertEqual(view["completed"], ["deployment.safety"])
        self.assertEqual(view["failed"], ["deployment.safety"])
        self.assertEqual(view["passed"], [])
        self.assertEqual(view["missing"], [])

    def test_optional_model_request_does_not_become_required(self):
        self.verifier.required_checks = ("missing.required",)
        test = AdversarialTest("AT1", "C1", "CL001", "registered:deployment.safety", POLICY_CLAIM)
        self.collect(tests=(test,))
        view = self.verifier.coverage[-1]
        self.assertEqual(view["required"], ["missing.required"])
        self.assertEqual(view["optional"], ["deployment.safety"])
        self.assertEqual(view["missing"], ["missing.required"])
        self.assertEqual(view["passed"], ["deployment.safety"])

    def test_latest_conflicting_collection_wins_and_history_is_preserved(self):
        self.collect()
        spec = self.executor.registry.get("deployment.safety")
        self.executor.registry = CheckRegistry([replace(spec,
            execute=lambda data, config: CheckOutput("FAIL", (POLICY_CLAIM,), '{}'))])
        self.collect()
        view = self.summary()
        self.assertEqual(view["passed"], [])
        self.assertEqual(view["failed"], ["deployment.safety"])
        self.assertEqual(view["repeat_count"], 2)
        self.assertEqual(view["conflicting_checks"], ["deployment.safety"])
        self.assertNotEqual(self.verifier.coverage[0]["checks"][0]["receipt"], view["checks"][0]["receipt"])

    def test_later_unknown_cannot_reuse_earlier_pass(self):
        self.collect()
        original = self.journal.append
        def fail_result(kind, *args, **kwargs):
            if kind == "check/result":
                with patch.object(self.journal, "checkpoint", side_effect=OSError("result fsync")):
                    return original(kind, *args, **kwargs)
            return original(kind, *args, **kwargs)
        with patch.object(self.journal, "append", fail_result), self.assertRaises(Exception):
            self.collect()
        view = self.summary()
        self.assertEqual(view["unknown"], ["deployment.safety"])
        self.assertEqual(view["passed"], [])
        self.assertEqual(view["missing"], ["deployment.safety"])

    def test_no_final_identity_has_explicit_unavailable_shape(self):
        self.collect()
        view = final_coverage("test-run", {"trajectory_id": "trajectory", "answer": "", "best_candidate_id": None},
                              None, self.verifier.coverage, ("deployment.safety",))
        self.assertIsNone(view["engine"])
        self.assertEqual(view["status"], "unavailable")
        self.assertEqual(view["passed"], [])

    def test_receipt_rejected_at_translation_is_not_reported_as_passed(self):
        with patch.object(self.verifier, 'evidence', side_effect=ValueError('receipt mismatch')):
            with self.assertRaises(ValueError):
                self.collect()
        view = self.summary()
        self.assertEqual(view['passed'], [])
        self.assertEqual(view['errored'], ['deployment.safety'])
        self.assertEqual(view['checks'][0]['reason'], 'receipt_validation_failed')


class CoverageIntegrationTests(unittest.TestCase):
    setUp = baseline.RealEngineIntegrationTests.setUp
    run_fixture = baseline.RealEngineIntegrationTests.run_fixture

    def test_native_rollback_selects_c1_coverage_not_last_checked_c2(self):
        result = self.run_fixture()
        self.assertEqual(result.final_candidate["local_id"], "C1")
        self.assertEqual(result.final_candidate_coverage["passed"], ["deployment.safety"])
        self.assertEqual(result.evidence_coverage[-1]["engine"]["local_id"], "C2")
        self.assertEqual(result.evidence_coverage[-1]["failed"], ["deployment.safety"])
        view = inspect_run(Path(result.directory))["result"]
        self.assertEqual(view["final_candidate_coverage"], result.final_candidate_coverage)

    def test_missing_required_stays_missing_despite_verified_engine_acceptance(self):
        result = self.run_fixture(required_checks=("deployment.safety", "missing.required"))
        self.assertEqual(result.engine_result["quality_gate"], "ACCEPT_VERIFIED")
        self.assertEqual(result.final_candidate_coverage["missing"], ["missing.required"])

    def test_default_does_not_probe_but_explicit_demo_configuration_does(self):
        default = self.run_fixture(RunConfig(self.source, self.output))
        self.assertEqual(default.engine_result["latest_candidate_id"], "C1")
        self.assertEqual(len(default.evidence_coverage), 2)
        self.assertEqual(default.budget["attempts"]["model"], 13)
        explicit = self.run_fixture()
        self.assertEqual(explicit.engine_result["latest_candidate_id"], "C2")
        self.assertEqual(explicit.engine_result["best_candidate_id"], "C1")
